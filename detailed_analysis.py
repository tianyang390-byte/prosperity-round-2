"""
详细分析v13策略的交易细节
"""

import json
import csv
import os
import sys
from io import StringIO
from typing import List, Dict, Tuple

sys.path.insert(0, '/Users/minimx/Downloads/ROUND_2')
from datamodel import OrderDepth, TradingState, Order


def get_mid_price(order_depth: OrderDepth) -> float:
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return 0.0
    best_bid = max(order_depth.buy_orders.keys())
    best_ask = min(order_depth.sell_orders.keys())
    return (best_bid + best_ask) / 2


class MomentumStrategy:
    def __init__(self):
        self.position_limit = 80
        self.price_history: Dict[str, List[float]] = {'INTARIAN_PEPPER_ROOT': []}
        self.entry_price: Dict[str, float] = {}
        self.highest_price: Dict[str, float] = {}
        self.consecutive_uptrend = 0
        self.trade_log = []

    def update_history(self, product: str, price: float):
        if price <= 0:
            return
        if product not in self.price_history:
            self.price_history[product] = []
        self.price_history[product].append(price)
        if len(self.price_history[product]) > 100:
            self.price_history[product] = self.price_history[product][-100:]

    def signal(self, state: TradingState, product: str, position: int, timestamp: int) -> List[Order]:
        orders = []
        od = state.order_depths.get(product)
        if od is None or not od.buy_orders or not od.sell_orders:
            return orders

        mid_price = get_mid_price(od)
        if mid_price <= 0:
            return orders

        self.update_history(product, mid_price)
        best_bid, best_ask = get_best_bid_ask(od)

        if product not in self.entry_price:
            self.entry_price[product] = mid_price
        if product not in self.highest_price:
            self.highest_price[product] = mid_price

        history = self.price_history.get(product, [])
        if len(history) < 5:
            return orders

        short_ma = sum(history[-5:]) / 5
        long_ma = sum(history[-10:]) / 10 if len(history) >= 10 else short_ma
        is_uptrend = short_ma > long_ma
        lookback_high = max(history[-20:]) if len(history) >= 20 else max(history)
        is_breakout = mid_price > lookback_high * 0.999

        if is_uptrend:
            self.consecutive_uptrend += 1
        else:
            self.consecutive_uptrend = 0

        available = self.position_limit - position

        if position == 0:
            if is_uptrend and self.consecutive_uptrend >= 3:
                best_ask = min(od.sell_orders.keys())
                volume = min(available, 20)
                if volume > 0:
                    orders.append(Order(product, int(best_ask), volume))
                    self.entry_price[product] = mid_price
                    self.highest_price[product] = mid_price
                    self.trade_log.append({
                        'timestamp': timestamp,
                        'action': 'BUY',
                        'price': int(best_ask),
                        'volume': volume,
                        'mid_price': mid_price,
                        'position': position + volume,
                        'reason': f'entry: MA5={short_ma:.1f}>MA10={long_ma:.1f}, consecutive={self.consecutive_uptrend}'
                    })
        elif 0 < position < self.position_limit:
            if is_uptrend and is_breakout and self.consecutive_uptrend >= 5:
                best_ask = min(od.sell_orders.keys())
                volume = min(available, 20)
                if volume > 0:
                    orders.append(Order(product, int(best_ask), volume))
                    self.trade_log.append({
                        'timestamp': timestamp,
                        'action': 'BUY_ADD',
                        'price': int(best_ask),
                        'volume': volume,
                        'mid_price': mid_price,
                        'position': position + volume,
                        'reason': f'add: breakout, consecutive={self.consecutive_uptrend}'
                    })
        elif position > 0:
            if mid_price > self.highest_price[product]:
                self.highest_price[product] = mid_price

            entry = self.entry_price[product]
            peak = self.highest_price[product]

            stop_price = entry * 0.985
            trailing_stop = peak * 0.975

            if mid_price < stop_price:
                orders.append(Order(product, int(mid_price), -position))
                self.trade_log.append({
                    'timestamp': timestamp,
                    'action': 'SELL_STOP',
                    'price': int(mid_price),
                    'volume': position,
                    'mid_price': mid_price,
                    'position': 0,
                    'reason': f'stop_loss: {mid_price:.1f} < {stop_price:.1f}'
                })
                self.entry_price[product] = 0
                self.consecutive_uptrend = 0
                return orders

            if mid_price < trailing_stop:
                orders.append(Order(product, int(mid_price), -position))
                self.trade_log.append({
                    'timestamp': timestamp,
                    'action': 'SELL_TRAILING',
                    'price': int(mid_price),
                    'volume': position,
                    'mid_price': mid_price,
                    'position': 0,
                    'reason': f'trailing_stop: {mid_price:.1f} < {trailing_stop:.1f} (peak={peak:.1f})'
                })
                self.entry_price[product] = 0
                self.consecutive_uptrend = 0
                return orders
        return orders


def get_best_bid_ask(order_depth: OrderDepth) -> tuple:
    if not order_depth.buy_orders or not order_depth.sell_orders:
        return 0, 0
    best_bid = max(order_depth.buy_orders.keys())
    best_ask = min(order_depth.sell_orders.keys())
    return best_bid, best_ask


def load_simulator_data(json_path: str) -> Tuple[List[dict], List[dict]]:
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
                    'mid_price': mp,
                    'bid_price_1': row.get('bid_price_1', ''),
                    'bid_volume_1': row.get('bid_volume_1', ''),
                    'ask_price_1': row.get('ask_price_1', ''),
                    'ask_volume_1': row.get('ask_volume_1', ''),
                })

    return intarian_data, ash_data


class SimulatedExchange:
    def __init__(self, position_limit: int = 80):
        self.position_limit = position_limit
        self.position: Dict[str, int] = {'INTARIAN_PEPPER_ROOT': 0}
        self.cash: float = 0.0

    def reset(self):
        self.position = {p: 0 for p in self.position}
        self.cash = 0.0

    def execute_orders(self, orders: List[Order], order_depths: Dict[str, OrderDepth]) -> float:
        for order in orders:
            product = order.symbol
            od = order_depths.get(product)
            if od is None:
                continue

            qty = order.quantity
            if qty > 0:
                if od.sell_orders:
                    best_ask = min(od.sell_orders.keys())
                    available_qty = abs(od.sell_orders[best_ask])
                    exec_qty = min(qty, available_qty)
                    if exec_qty > 0:
                        self.position[product] += exec_qty
                        self.cash -= best_ask * exec_qty
            elif qty < 0:
                if od.buy_orders:
                    best_bid = max(od.buy_orders.keys())
                    available_qty = od.buy_orders[best_bid]
                    exec_qty = min(abs(qty), available_qty)
                    if exec_qty > 0:
                        new_position = self.position[product] - exec_qty
                        if abs(new_position) <= self.position_limit:
                            self.position[product] = new_position
                            self.cash += best_bid * exec_qty
        return 0.0

    def get_final_value(self, intarian_data):
        value = self.cash
        for product, pos in self.position.items():
            if pos != 0:
                if intarian_data:
                    value += pos * intarian_data[-1]['mid_price']
        return value


def create_order_depth(data_row: dict) -> OrderDepth:
    od = OrderDepth()
    if data_row.get('bid_price_1') and data_row.get('bid_volume_1'):
        try:
            od.buy_orders[int(data_row['bid_price_1'])] = int(data_row['bid_volume_1'])
        except:
            pass
    if data_row.get('ask_price_1') and data_row.get('ask_volume_1'):
        try:
            od.sell_orders[int(data_row['ask_price_1'])] = -int(data_row['ask_volume_1'])
        except:
            pass
    return od


def analyze_dataset(folder_name, json_file):
    print(f"\n{'='*70}")
    print(f"数据集: {folder_name}")
    print(f"{'='*70}")

    intarian_data, _ = load_simulator_data(json_file)
    if not intarian_data:
        return

    exchange = SimulatedExchange()
    exchange.reset()
    momentum = MomentumStrategy()

    all_timestamps = sorted(set(int(r['timestamp']) for r in intarian_data))

    for timestamp in all_timestamps:
        intarian_row = next((r for r in intarian_data if int(r['timestamp']) == timestamp), None)
        if not intarian_row:
            continue

        order_depths = {'INTARIAN_PEPPER_ROOT': create_order_depth(intarian_row)}

        state = TradingState(
            traderData='',
            timestamp=timestamp,
            listings={},
            order_depths=order_depths,
            own_trades={},
            market_trades={},
            position=dict(exchange.position),
            observations=None
        )

        orders = momentum.signal(state, 'INTARIAN_PEPPER_ROOT', exchange.position.get('INTARIAN_PEPPER_ROOT', 0), timestamp)
        for o in orders:
            o.symbol = 'INTARIAN_PEPPER_ROOT'

        exchange.execute_orders(orders, order_depths)

    final_value = exchange.get_final_value(intarian_data)

    print(f"\n最终PnL: {final_value:.2f}")
    print(f"最终持仓: {exchange.position}")
    print(f"交易次数: {len(momentum.trade_log)}")
    print(f"\n交易明细:")
    print(f"{'Time':<8} {'Action':<10} {'Price':<8} {'Volume':<6} {'MidPrice':<10} {'Position':<8} {'Reason'}")
    print("-" * 90)
    for log in momentum.trade_log:
        print(f"{log['timestamp']:<8} {log['action']:<10} {log['price']:<8} {log['volume']:<6} {log['mid_price']:<10.1f} {log['position']:<8} {log['reason']}")

    return final_value, momentum.trade_log


def main():
    datasets_dir = '/Users/minimx/Downloads'
    datasets = []

    for folder_name in os.listdir(datasets_dir):
        folder_path = os.path.join(datasets_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue
        if not folder_name.isdigit() or len(folder_name) != 6:
            continue
        json_file = os.path.join(folder_path, f'{folder_name}.json')
        if not os.path.exists(json_file):
            continue
        datasets.append((folder_name, json_file))

    results = []
    for folder_name, json_file in sorted(datasets):
        pnl, logs = analyze_dataset(folder_name, json_file)
        results.append((folder_name, pnl))

    print(f"\n{'='*70}")
    print("汇总")
    print(f"{'='*70}")
    for name, pnl in results:
        print(f"{name}: {pnl:.2f}")
    print(f"平均: {sum(p for _, p in results)/len(results):.2f}")


if __name__ == '__main__':
    main()