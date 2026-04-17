"""
批量测试模拟器数据集
遍历所有六位数字文件夹，用trader策略跑回测，计算平均PnL
"""

import json
import csv
import os
import sys
from io import StringIO
from typing import List, Dict, Tuple

sys.path.insert(0, '/Users/minimx/Downloads/ROUND_2')
from datamodel import OrderDepth, TradingState, Order


def load_simulator_data(json_path: str) -> Tuple[List[dict], List[dict]]:
    """从模拟器json加载价格数据"""
    with open(json_path, 'r') as f:
        data = json.load(f)

    activities = data.get('activitiesLog', '')
    reader = csv.DictReader(StringIO(activities), delimiter=';')

    intarian_data = []
    ash_data = []

    for row in reader:
        if row['product'] == 'INTARIAN_PEPPER_ROOT' and row.get('mid_price'):
            mp = float(row['mid_price'])
            if mp > 0:
                intarian_data.append({
                    'timestamp': int(row['timestamp']),
                    'day': int(row.get('day', 1)),
                    'mid_price': mp,
                    'bid_price_1': row.get('bid_price_1', ''),
                    'bid_volume_1': row.get('bid_volume_1', ''),
                    'ask_price_1': row.get('ask_price_1', ''),
                    'ask_volume_1': row.get('ask_volume_1', ''),
                })
        elif row['product'] == 'ASH_COATED_OSMIUM' and row.get('mid_price'):
            mp = float(row['mid_price'])
            if mp > 0:
                ash_data.append({
                    'timestamp': int(row['timestamp']),
                    'day': int(row.get('day', 1)),
                    'mid_price': mp,
                    'bid_price_1': row.get('bid_price_1', ''),
                    'bid_volume_1': row.get('bid_volume_1', ''),
                    'ask_price_1': row.get('ask_price_1', ''),
                    'ask_volume_1': row.get('ask_price_1', ''),
                })

    return intarian_data, ash_data


class SimulatedExchange:
    """模拟交易所"""

    def __init__(self, position_limit: int = 80):
        self.position_limit = position_limit
        self.position: Dict[str, int] = {'ASH_COATED_OSMIUM': 0, 'INTARIAN_PEPPER_ROOT': 0}
        self.cash: float = 0.0

    def reset(self):
        self.position = {p: 0 for p in self.position}
        self.cash = 0.0

    def get_mid_price(self, order_depth: OrderDepth) -> float:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return 0.0
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        return (best_bid + best_ask) / 2

    def execute_orders(self, orders: List[Order], order_depths: Dict[str, OrderDepth]) -> float:
        """执行订单，返回PnL变化"""
        pnl_delta = 0.0

        for order in orders:
            product = order.symbol
            od = order_depths.get(product)
            if od is None:
                continue

            qty = order.quantity

            if qty > 0:  # 买单
                if od.sell_orders:
                    best_ask = min(od.sell_orders.keys())
                    available_qty = abs(od.sell_orders[best_ask])
                    exec_qty = min(qty, available_qty)
                    if exec_qty > 0:
                        self.position[product] += exec_qty
                        self.cash -= best_ask * exec_qty
                        pnl_delta -= best_ask * exec_qty

            elif qty < 0:  # 卖单
                if od.buy_orders:
                    best_bid = max(od.buy_orders.keys())
                    available_qty = od.buy_orders[best_bid]
                    exec_qty = min(abs(qty), available_qty)
                    if exec_qty > 0:
                        new_position = self.position[product] - exec_qty
                        if abs(new_position) <= self.position_limit:
                            self.position[product] = new_position
                            self.cash += best_bid * exec_qty
                            pnl_delta += best_bid * exec_qty

        return pnl_delta

    def get_portfolio_value(self, order_depths: Dict[str, OrderDepth]) -> float:
        value = self.cash
        for product, pos in self.position.items():
            if pos != 0:
                od = order_depths.get(product)
                if od:
                    mid = self.get_mid_price(od)
                    value += pos * mid
        return value


def create_order_depth(data_row: dict) -> OrderDepth:
    """从数据行创建OrderDepth"""
    od = OrderDepth()

    # 解析买单
    if data_row.get('bid_price_1') and data_row.get('bid_volume_1'):
        try:
            od.buy_orders[int(data_row['bid_price_1'])] = int(data_row['bid_volume_1'])
        except (ValueError, TypeError):
            pass

    # 解析卖单
    if data_row.get('ask_price_1') and data_row.get('ask_volume_1'):
        try:
            od.sell_orders[int(data_row['ask_price_1'])] = -int(data_row['ask_volume_1'])
        except (ValueError, TypeError):
            pass

    return od


def run_backtest_on_data(intarian_data: List[dict], ash_data: List[dict], trader_class) -> dict:
    """在模拟器数据上运行回测"""
    from trader import Trader

    exchange = SimulatedExchange()
    exchange.reset()

    trader = trader_class()

    # 按时间戳排序
    all_timestamps = sorted(set(
        int(row['timestamp'])
        for row in intarian_data + ash_data
    ))

    order_log = []

    for timestamp in all_timestamps:
        # 找到当前时间的数据
        intarian_row = next((r for r in intarian_data if int(r['timestamp']) == timestamp), None)
        ash_row = next((r for r in ash_data if int(r['timestamp']) == timestamp), None)

        # 构建order_depths
        order_depths = {}
        listings = {}

        if intarian_row:
            order_depths['INTARIAN_PEPPER_ROOT'] = create_order_depth(intarian_row)
            listings['INTARIAN_PEPPER_ROOT'] = type('Listing', (), {'symbol': 'INTARIAN_PEPPER_ROOT', 'product': 'INTARIAN_PEPPER_ROOT', 'denomination': 'XIRECS'})

        if ash_row:
            order_depths['ASH_COATED_OSMIUM'] = create_order_depth(ash_row)
            listings['ASH_COATED_OSMIUM'] = type('Listing', (), {'symbol': 'ASH_COATED_OSMIUM', 'product': 'ASH_COATED_OSMIUM', 'denomination': 'XIRECS'})

        # 创建TradingState
        state = TradingState(
            traderData='',
            timestamp=timestamp,
            listings=listings,
            order_depths=order_depths,
            own_trades={p: [] for p in order_depths.keys()},
            market_trades={p: [] for p in order_depths.keys()},
            position=dict(exchange.position),
            observations=type('Observation', (), {'plainValueObservations': {}, 'conversionObservations': {}})()
        )

        # 调用trader
        try:
            result, conversions, traderData = trader.run(state)
        except Exception as e:
            continue

        # 执行订单
        all_orders = []
        if result:
            for product, orders in result.items():
                for order in orders:
                    order.symbol = product
                    all_orders.append(order)

        exchange.execute_orders(all_orders, order_depths)

        for order in all_orders:
            order_log.append({
                'timestamp': timestamp,
                'product': order.symbol,
                'direction': 'BUY' if order.quantity > 0 else 'SELL',
                'price': order.price,
                'quantity': abs(order.quantity)
            })

    # 计算最终PnL
    final_value = exchange.cash
    for product, pos in exchange.position.items():
        if pos != 0:
            if product == 'INTARIAN_PEPPER_ROOT' and intarian_data:
                final_value += pos * intarian_data[-1]['mid_price']
            elif product == 'ASH_COATED_OSMIUM' and ash_data:
                final_value += pos * ash_data[-1]['mid_price']

    return {
        'pnl': final_value,
        'trades': len(order_log),
        'final_position': dict(exchange.position),
        'order_log': order_log
    }


def batch_test(datasets_dir: str, trader_class) -> dict:
    """批量测试所有模拟器数据集"""
    results = []

    # 遍历所有六位数字文件夹
    for folder_name in os.listdir(datasets_dir):
        folder_path = os.path.join(datasets_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue

        # 检查是否是六位数字
        if not folder_name.isdigit() or len(folder_name) != 6:
            continue

        json_file = os.path.join(folder_path, f'{folder_name}.json')
        if not os.path.exists(json_file):
            continue

        print(f"\n{'='*60}")
        print(f"测试数据集: {folder_name}")
        print(f"{'='*60}")

        # 加载数据
        intarian_data, ash_data = load_simulator_data(json_file)
        print(f"INTARIAN数据点: {len(intarian_data)}")
        print(f"ASH数据点: {len(ash_data)}")

        if not intarian_data:
            print("无INTARIAN数据，跳过")
            continue

        # 运行回测
        result = run_backtest_on_data(intarian_data, ash_data, trader_class)

        print(f"PnL: {result['pnl']:.2f}")
        print(f"交易次数: {result['trades']}")
        print(f"最终持仓: {result['final_position']}")

        results.append({
            'dataset': folder_name,
            **result
        })

    # 汇总
    if not results:
        print("\n没有找到有效的数据集")
        return {}

    print(f"\n{'='*60}")
    print("汇总统计")
    print(f"{'='*60}")

    pnls = [r['pnl'] for r in results]
    total_trades = sum(r['trades'] for r in results)

    print(f"测试数据集数: {len(results)}")
    print(f"平均PnL: {sum(pnls)/len(pnls):.2f}")
    print(f"总交易次数: {total_trades}")

    print("\n各数据集结果:")
    for r in sorted(results, key=lambda x: x['dataset']):
        print(f"  {r['dataset']}: PnL={r['pnl']:.2f}, 交易={r['trades']}")

    return {
        'results': results,
        'avg_pnl': sum(pnls) / len(pnls),
        'total_trades': total_trades
    }


if __name__ == '__main__':
    from trader import Trader

    datasets_dir = '/Users/minimx/Downloads'
    batch_test(datasets_dir, Trader)