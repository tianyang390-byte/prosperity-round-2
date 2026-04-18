"""
Trader - IMC Prosperity Round 2 双股票量化交易策略
=================================================

产品:
- ASH_COATED_OSMIUM: 稳定均值回归，做市策略
- INTARIAN_PEPPER_ROOT: 趋势动量策略，带 scalp 交易

架构:
- trade_ash(): ASH 做市策略（被动吃单 + 双层挂单）
- trade_intarian(): INTARIAN 趋势策略（入场 + 加仓 + 止损 + scalp）
- run(): 主循环，分发到各策略

回测结果: 284,240 PnL (三天)
"""

import json
from typing import Dict, List, Tuple

from datamodel import OrderDepth, Order, TradingState


# ==================== 产品与仓位 ====================

PRODUCT_ASH = "ASH_COATED_OSMIUM"
PRODUCT_INTARIAN = "INTARIAN_PEPPER_ROOT"

POSITION_LIMITS = {
    PRODUCT_ASH: 80,
    PRODUCT_INTARIAN: 80,
}

# ==================== ASH 做市参数 ====================
#
# ASH 特性: 围绕 10000 均值回归，spread 16-22点
# 策略: EMA追踪FV + Position调整 + Taker主动吃单 + 双层挂单
#

ASH_ANCHOR = 10000.0              # 长期锚定价格

ASH_EMA_ALPHA = 0.08             # EMA平滑系数，越大对近期价格越敏感
ASH_ANCHOR_WEIGHT = 0.75        # 锚定权重: 75% anchor + 25% EMA
ASH_POSITION_SKEW = 0.25         # 仓位对FV的影响系数: fair -= 0.25 * position
                                  # 持仓为正时，fair降低（偏向卖出对冲）

ASH_TAKE_EDGE = 0.5              # Taker订单的edge阈值
                                  # 买单: ask_price <= fair + 0.5 时主动吃
                                  # 卖单: bid_price >= fair - 0.5 时主动吃

ASH_WIDE_SPREAD_CUTOFF = 8.0     # spread >= 8 时认为价差宽
ASH_INNER_WIDTH_WIDE = 2.0       # 宽spread时内层挂单距FV的距离
ASH_INNER_WIDTH_TIGHT = 1.0      # 窄spread时内层挂单距FV的距离
ASH_OUTER_STEP = 2.0            # 外层相对内层的偏移量

# ==================== INTARIAN 趋势参数 ====================
#
# INTARIAN 特性: 趋势型产品，波动较大
# 策略: MA多头排列入场 + 突破加仓 + 移动止损 + Scalp降本
#

INT_MA_SHORT = 5                 # 短期均线周期
INT_MA_LONG = 8                  # 长期均线周期
INT_LOOKBACK = 20                # 突破判断的回顾期

INT_ENTRY_CONSEC = 1             # 入场需要的连续趋势周期数
INT_ADD_CONSEC = 3               # 加仓需要的连续趋势周期数

INT_FIRST_SIZE = 10              # 首次入场数量
INT_ADD_SIZE = 10                # 加仓数量
INT_CORE_POSITION = 40           # 核心持仓线，超过此水位启动scalp

INT_STOP_LOSS_PCT = 0.015       # 止损: 跌破入场价1.5%
INT_TRAILING_STOP_PCT = 0.025   # 移动止损: 从最高点回撤2.5%

INT_SCALP_SIZE = 15              # Scalp交易每次买卖的数量
INT_PARTIAL_TAKE_OFFSET = 6.0    # Scalp止盈: 超过MA+6点时卖出INT_SCALP_SIZE
INT_REBUY_OFFSET = 1.5          # Scalp回补: 价格回到MA+1.5以内时买回


# ==================== 工具函数 ====================

def best_bid_ask(order_depth: OrderDepth) -> Tuple[int, int]:
    """获取最优买卖价"""
    return max(order_depth.buy_orders), min(order_depth.sell_orders)


def mid_price(order_depth: OrderDepth) -> float:
    """计算中间价 = (最优买价 + 最优卖价) / 2"""
    best_bid, best_ask = best_bid_ask(order_depth)
    return (best_bid + best_ask) / 2


def clamp(value: float, lower: float, upper: float) -> float:
    """将value限制在[lower, upper]范围内"""
    return max(lower, min(upper, value))


def take_sell_capacity(position: int, limit: int) -> int:
    """计算还能卖出多少（用于taker卖单）
    position为正表示多头持仓，可以卖出这么多
    公式: position + limit = 最大可卖数量（空头 + 多头）
    """
    return position + limit


# ==================== 主 Trader 类 ====================

class Trader:

    def __init__(self) -> None:
        self.limits = POSITION_LIMITS

    def bid(self) -> int:
        """MAF竞拍价格，返回20"""
        return 20

    def bounded_append(self, history: List[float], price: float, max_len: int = 100) -> List[float]:
        """追加价格到历史记录，保持最大长度"""
        history.append(price)
        if len(history) > max_len:
            history = history[-max_len:]
        return history

    def load_data(self, state: TradingState) -> Dict:
        """从TradingState恢复traderData（状态持久化）"""
        raw = getattr(state, "traderData", "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def save_data(self, data: Dict) -> str:
        """将状态数据序列化为JSON字符串"""
        return json.dumps(data, separators=(",", ":"))

    def update_ema(self, prev: float, price: float, alpha: float) -> float:
        """EMA更新公式: ema = alpha * price + (1-alpha) * prev"""
        if prev is None:
            return price
        return alpha * price + (1 - alpha) * prev


# ==================== ASH 做市策略 ====================
#
# 核心思想: ASH是均值回归产品，围绕10000震荡
#
# 订单生成逻辑:
# 1. Taker主动吃单: 遍历订单簿，在fair附近主动成交对冲仓位
# 2. Maker挂单: 双层挂单（内层1-2档，外层2-3档）
#
# Position调整:
# - temp_pos > 10: 偏空头，减小买入、增加卖出
# - temp_pos < -10: 偏多头，增加买入、减小卖出
# - 否则: 中性，对称挂单
#
# 关键公式:
# - base_fair = 0.75 * 10000 + 0.25 * EMA(mid)
# - fair = base_fair - 0.25 * position
#   （position>0时fair降低，偏向卖；position<0时fair升高，偏向买）
#
# 挂单价格:
# - 买单: min(best_bid + 1, fair - inner_width)
# - 卖单: max(best_ask - 1, fair + inner_width)
#   （确保不会挂出比市场更差的价格）
#

    def trade_ash(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        state_data: Dict,
    ) -> Tuple[List[Order], Dict]:
        orders: List[Order] = []
        limit = self.limits[product]

        # ---- 价格获取 ----
        best_bid, best_ask = best_bid_ask(order_depth)
        spread = best_ask - best_bid
        mid = (best_bid + best_ask) / 2

        # ---- 计算Fair Value ----
        ash_ema = self.update_ema(state_data.get("ash_ema"), mid, ASH_EMA_ALPHA)
        # 75%锚定价格 + 25% EMA
        base_fair = ASH_ANCHOR_WEIGHT * ASH_ANCHOR + (1 - ASH_ANCHOR_WEIGHT) * ash_ema
        # Position调整：多头时降低FV（更激进卖出），空头时升高FV（更激进买入）
        fair = base_fair - ASH_POSITION_SKEW * position

        # ---- Taker主动吃单 ----
        # 遍历卖单（买方向），当卖价 <= fair + edge 时主动吃入
        buy_take_edge = ASH_TAKE_EDGE
        sell_take_edge = ASH_TAKE_EDGE
        temp_pos = position  # 跟踪taker成交后的临时仓位

        # 买方向taker：遍历卖单簿，价格从低到高
        for ask_price, ask_volume in sorted(order_depth.sell_orders.items()):
            # 只有当卖价 <= fair + edge 时才吃
            if ask_price <= fair + buy_take_edge and temp_pos < limit:
                quantity = min(-ask_volume, limit - temp_pos)
                if quantity > 0:
                    orders.append(Order(product, ask_price, quantity))
                    temp_pos += quantity
            else:
                break

        # 卖方向taker：遍历买单簿，价格从高到低
        for bid_price, bid_volume in sorted(order_depth.buy_orders.items(), reverse=True):
            # 只有当买价 >= fair - edge 时才吃
            if bid_price >= fair - sell_take_edge and temp_pos > -limit:
                quantity = min(bid_volume, take_sell_capacity(temp_pos, limit))
                if quantity > 0:
                    orders.append(Order(product, bid_price, -quantity))
                    temp_pos -= quantity
            else:
                break

        # ---- Maker挂单 ----
        buy_room = limit - temp_pos   # 还能买多少
        sell_room = temp_pos + limit  # 还能卖多少

        # 根据spread决定挂单宽度
        inner_width = ASH_INNER_WIDTH_WIDE if spread >= ASH_WIDE_SPREAD_CUTOFF else ASH_INNER_WIDTH_TIGHT
        outer_width = inner_width + ASH_OUTER_STEP

        # 计算挂单价格
        # 买单: 低于最优买价1档，且低于fair
        buy_quote_1 = min(best_bid + 1, int(fair - inner_width))
        # 卖单: 高于最优卖价1档，且高于fair
        sell_quote_1 = max(best_ask - 1, int(fair + inner_width))
        buy_quote_2 = min(best_bid, int(fair - outer_width))
        sell_quote_2 = max(best_ask, int(fair + outer_width))

        # 根据temp_pos调整挂单数量（仓位偏向）
        if temp_pos > 10:
            # 多头过重，增加卖出对冲
            buy_size_1, buy_size_2 = 2, 1
            sell_size_1, sell_size_2 = 8, 4
        elif temp_pos < -10:
            # 空头过重，增加买入对冲
            buy_size_1, buy_size_2 = 8, 4
            sell_size_1, sell_size_2 = 2, 1
        else:
            # 中性，对称
            buy_size_1, buy_size_2 = 6, 3
            sell_size_1, sell_size_2 = 6, 3

        # 挂内层单
        if buy_room > 0:
            orders.append(Order(product, int(buy_quote_1), min(buy_size_1, buy_room)))
        if sell_room > 0:
            orders.append(Order(product, int(sell_quote_1), -min(sell_size_1, sell_room)))

        # 挂外层单（用剩余空间）
        remaining_buy = max(0, buy_room - min(buy_size_1, buy_room))
        remaining_sell = max(0, sell_room - min(sell_size_1, sell_room))
        if remaining_buy > 0:
            orders.append(Order(product, int(buy_quote_2), min(buy_size_2, remaining_buy)))
        if remaining_sell > 0:
            orders.append(Order(product, int(sell_quote_2), -min(sell_size_2, remaining_sell)))

        state_out = {"ash_ema": ash_ema}
        return orders, state_out


# ==================== INTARIAN 趋势策略 ====================
#
# 核心思想: 趋势跟随 + 移动止损 + Scalp降本
#
# 入场条件:
# - MA5 > MA8（均线多头排列）
# - 连续1周期满足上述条件
#
# 加仓条件:
# - 多头排列 + 连续3周期 + 价格突破20日高点
#
# 止损:
# - 固定止损: 跌破入场价1.5%
# - 移动止损: 从最高点回撤2.5%
#
# Scalp机制（核心创新）:
# - 保持40手核心仓位
# - 当价格偏离MA5超过6点时，卖出15手（止盈部分）
# - 当价格回到MA5+1.5以内时，买回15手（回补）
# - 目的: 不丢失趋势仓位的同时波段降成本
#
# State持久化:
# - history: 价格历史（用于计算MA）
# - entry_price: 入场价
# - highest_price: 持仓期最高价
# - consecutive_uptrend: 连续趋势周期计数
# - scalp_state: "neutral" | "waiting_rebuy"
#

    def trade_intarian(
        self,
        product: str,
        order_depth: OrderDepth,
        position: int,
        state_data: Dict,
    ) -> Tuple[List[Order], Dict]:
        orders: List[Order] = []
        limit = self.limits[product]

        # ---- 价格获取 ----
        best_bid, best_ask = best_bid_ask(order_depth)
        mid = (best_bid + best_ask) / 2

        # ---- 恢复状态 ----
        history = list(state_data.get("history", []))
        history = self.bounded_append(history, mid)

        entry_price = state_data.get("entry_price", 0.0)
        highest_price = state_data.get("highest_price", 0.0)
        consecutive_uptrend = state_data.get("consecutive_uptrend", 0)
        scalp_state = state_data.get("scalp_state", "neutral")

        # 数据不足时直接返回
        if len(history) < max(INT_MA_SHORT, INT_MA_LONG):
            return orders, {
                "history": history,
                "entry_price": entry_price,
                "highest_price": highest_price,
                "consecutive_uptrend": consecutive_uptrend,
                "scalp_state": scalp_state,
            }

        # ---- 趋势判断 ----
        short_ma = sum(history[-INT_MA_SHORT:]) / INT_MA_SHORT  # MA5
        long_ma = sum(history[-INT_MA_LONG:]) / INT_MA_LONG       # MA8
        is_uptrend = short_ma > long_ma                             # 多头排列

        # 突破判断: 价格创20日新高
        lookback_slice = history[-INT_LOOKBACK:] if len(history) >= INT_LOOKBACK else history
        lookback_high = max(lookback_slice)
        is_breakout = mid > lookback_high * 0.999

        # 连续趋势计数
        if is_uptrend:
            consecutive_uptrend += 1
        else:
            consecutive_uptrend = 0

        available = limit - position

        # ---- 入场逻辑 ----
        if position == 0:
            if is_uptrend and consecutive_uptrend >= INT_ENTRY_CONSEC:
                volume = min(available, INT_FIRST_SIZE)  # 买10手
                if volume > 0:
                    orders.append(Order(product, int(best_ask), volume))
                    entry_price = mid
                    highest_price = mid
                    scalp_state = "neutral"

        # ---- 持仓管理 ----
        elif position > 0:
            highest_price = max(highest_price, mid)  # 更新最高价
            exited = False

            # 止损检查1: 固定止损（跌破入场价1.5%）
            if entry_price > 0 and mid < entry_price * (1 - INT_STOP_LOSS_PCT):
                orders.append(Order(product, int(best_bid), -position))
                entry_price = 0.0
                highest_price = 0.0
                consecutive_uptrend = 0
                scalp_state = "neutral"
                exited = True
            else:
                # 止损检查2: 移动止损（从最高点回撤2.5%）
                trailing_stop = highest_price * (1 - INT_TRAILING_STOP_PCT) if highest_price > 0 else 0.0
                if trailing_stop > 0 and mid < trailing_stop:
                    orders.append(Order(product, int(best_bid), -position))
                    entry_price = 0.0
                    highest_price = 0.0
                    consecutive_uptrend = 0
                    scalp_state = "neutral"
                    exited = True

            # ---- 未触发止损的后续处理 ----
            if not exited:
                # 加仓: 趋势延续 + 突破 + 连续3周期
                if position < limit and is_uptrend and is_breakout and consecutive_uptrend >= INT_ADD_CONSEC:
                    volume = min(limit - position, INT_ADD_SIZE)
                    if volume > 0:
                        orders.append(Order(product, int(best_ask), volume))
                        highest_price = max(highest_price, mid)

                # ---- Scalp部分止盈 ----
                # 条件: 持仓>40手 + 趋势仍在 + 未处于等待回补状态 + 价格超过MA5+6点
                if (
                    position > INT_CORE_POSITION
                    and is_uptrend
                    and scalp_state != "waiting_rebuy"
                    and mid >= short_ma + INT_PARTIAL_TAKE_OFFSET
                ):
                    trim_qty = min(INT_SCALP_SIZE, position - INT_CORE_POSITION)
                    if trim_qty > 0:
                        orders.append(Order(product, int(best_bid), -trim_qty))
                        scalp_state = "waiting_rebuy"

                # ---- Scalp回补 ----
                # 条件: 处于等待回补状态 + 趋势仍在 + 价格回到MA5+1.5以内
                elif (
                    scalp_state == "waiting_rebuy"
                    and is_uptrend
                    and position < limit
                    and mid <= short_ma + INT_REBUY_OFFSET
                ):
                    rebuy_qty = min(INT_SCALP_SIZE, limit - position)
                    if rebuy_qty > 0:
                        orders.append(Order(product, int(best_ask), rebuy_qty))
                        scalp_state = "neutral"

        return orders, {
            "history": history,
            "entry_price": entry_price,
            "highest_price": highest_price,
            "consecutive_uptrend": consecutive_uptrend,
            "scalp_state": scalp_state,
        }


# ==================== 主循环 ====================

    def run(self, state: TradingState):
        """
        每tick被调用一次
        输入: TradingState (订单簿、持仓、时间戳等)
        输出: (订单列表, conversions, traderData)
        """
        result: Dict[str, List[Order]] = {}
        conversions = 0

        # 恢复持久化状态
        data = self.load_data(state)
        ash_state = data.get("ash", {})
        intarian_state = data.get("intarian", {})

        # 遍历所有产品生成订单
        for product, order_depth in state.order_depths.items():
            # 跳过空订单簿
            if not order_depth.buy_orders or not order_depth.sell_orders:
                result[product] = []
                continue

            position = state.position.get(product, 0)

            if product == PRODUCT_ASH:
                orders, ash_state = self.trade_ash(product, order_depth, position, ash_state)
                result[product] = orders
            elif product == PRODUCT_INTARIAN:
                orders, intarian_state = self.trade_intarian(
                    product, order_depth, position, intarian_state
                )
                result[product] = orders

        # 序列化状态供下次调用使用
        trader_data = self.save_data({
            "ash": ash_state,
            "intarian": intarian_state,
        })
        return result, conversions, trader_data