"""
ASH做市策略 - 动态Fair Value版本（更细粒度）
"""

import json
import csv
import os
import sys
from io import StringIO
from typing import List, Dict

sys.path.insert(0, '/Users/minimx/Downloads/ROUND_2')


def load_ash_data(json_path: str) -> List[dict]:
    with open(json_path, 'r') as f:
        data = json.load(f)

    activities = data.get('activitiesLog', '')
    reader = csv.DictReader(StringIO(activities), delimiter=';')

    ash_data = []
    for row in reader:
        if row['product'] == 'ASH_COATED_OSMIUM' and row.get('mid_price'):
            mp = float(row['mid_price'])
            if mp > 0:
                ash_data.append({
                    'timestamp': int(row['timestamp']),
                    'mid_price': mp,
                    'bid_price_1': row.get('bid_price_1', ''),
                    'bid_volume_1': row.get('bid_volume_1', ''),
                    'ask_price_1': row.get('ask_price_1', ''),
                    'ask_volume_1': row.get('ask_volume_1', ''),
                })
    return ash_data


def create_order_depth(data_row: dict) -> tuple:
    buy_orders = {}
    sell_orders = {}

    if data_row.get('bid_price_1') and data_row.get('bid_volume_1'):
        try:
            buy_orders[int(data_row['bid_price_1'])] = int(data_row['bid_volume_1'])
        except:
            pass
    if data_row.get('ask_price_1') and data_row.get('ask_volume_1'):
        try:
            sell_orders[int(data_row['ask_price_1'])] = -int(data_row['ask_volume_1'])
        except:
            pass

    return buy_orders, sell_orders


def calc_fair_value(prices: List[float], idx: int, window: int) -> float:
    if idx < window:
        return sum(prices[:idx+1]) / (idx + 1)
    return sum(prices[idx-window+1:idx+1]) / window


def simulate_market_making(data: List[dict], fv_window: int, buy_thresh: float,
                          sell_thresh: float, max_position: int = 30) -> dict:

    prices = [d['mid_price'] for d in data]

    position = 0
    cash = 0
    buy_trades = 0
    sell_trades = 0
    entry_price = 0
    entry_idx = 0

    for i, d in enumerate(data):
        mid_price = d['mid_price']
        fv = calc_fair_value(prices, i, fv_window)

        buy_orders, sell_orders = create_order_depth(d)

        buy_line = fv - buy_thresh
        sell_line = fv + sell_thresh

        # 买入
        if position < max_position:
            if mid_price <= buy_line:
                if sell_orders:
                    best_ask = min(sell_orders.keys())
                    if best_ask <= buy_line + 1:
                        qty = min(10, max_position - position)
                        position += qty
                        cash -= best_ask * qty
                        buy_trades += 1
                        entry_price = best_ask
                        entry_idx = i

        # 卖出
        if position > 0:
            if mid_price >= sell_line:
                if buy_orders:
                    best_bid = max(buy_orders.keys())
                    cash += best_bid * position
                    position = 0
                    sell_trades += 1

            elif mid_price - entry_price >= sell_thresh:
                if buy_orders:
                    best_bid = max(buy_orders.keys())
                    cash += best_bid * position
                    position = 0
                    sell_trades += 1

            elif entry_price > 0 and mid_price < entry_price * 0.98:
                if buy_orders:
                    best_bid = max(buy_orders.keys())
                    cash += best_bid * position
                    position = 0
                    sell_trades += 1

            elif i - entry_idx > 50:
                if buy_orders:
                    best_bid = max(buy_orders.keys())
                    cash += best_bid * position
                    position = 0
                    sell_trades += 1

    if position > 0:
        cash += prices[-1] * position

    return {
        'buy_trades': buy_trades,
        'sell_trades': sell_trades,
        'position': position,
        'pnl': cash
    }


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

    print("=" * 70)
    print("ASH做市策略 - 动态Fair Value细粒度测试")
    print("=" * 70)

    all_results = []

    for folder_name, json_file in sorted(datasets):
        ash_data = load_ash_data(json_file)
        if not ash_data:
            continue

        print(f"\n数据集: {folder_name}")

        for window in [2, 3, 4, 5, 7, 10, 15, 20]:
            for buy_th in [2, 3, 4, 5]:
                for sell_th in [2, 3, 4, 5]:
                    r = simulate_market_making(ash_data, window, buy_th, sell_th)
                    r['dataset'] = folder_name
                    r['window'] = window
                    r['buy_th'] = buy_th
                    r['sell_th'] = sell_th
                    all_results.append(r)

    # 汇总
    print("\n" + "=" * 70)
    print("汇总：最优配置TOP10")
    print("=" * 70)

    configs = {}
    for r in all_results:
        key = (r['window'], r['buy_th'], r['sell_th'])
        if key not in configs:
            configs[key] = []
        configs[key].append(r)

    best_configs = []
    for key, results in configs.items():
        avg_pnl = sum(r['pnl'] for r in results) / len(results)
        avg_trades = sum(r['buy_trades'] + r['sell_trades'] for r in results) / len(results)
        best_configs.append((*key, avg_pnl, avg_trades))

    best_configs.sort(key=lambda x: -x[4])

    for i, (window, buy_th, sell_th, avg_pnl, avg_trades) in enumerate(best_configs[:10]):
        print(f"TOP{i+1}: FV_window={window}, buy={buy_th}, sell={sell_th}: "
              f"平均PnL={avg_pnl:>8.0f}, 平均交易={avg_trades:.0f}")


if __name__ == '__main__':
    main()