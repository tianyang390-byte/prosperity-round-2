"""
ASH做市策略 - Debug版
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


def simulate_market_making(data: List[dict], threshold: float, max_position: int = 30) -> dict:
    prices = [d['mid_price'] for d in data]
    fair_values = []
    for i in range(len(prices)):
        if i < 20:
            fv = sum(prices[:i+1]) / (i+1)
        else:
            fv = sum(prices[i-19:i+1]) / 20
        fair_values.append(fv)

    position = 0
    cash = 0
    buy_trades = 0
    sell_trades = 0
    debug_trades = []

    for i, d in enumerate(data[:100]):  # 只看前100个
        mid_price = d['mid_price']
        fv = fair_values[i]
        buy_orders, sell_orders = create_order_depth(d)

        # 买入逻辑
        if position < max_position:
            if mid_price <= fv - threshold:
                if sell_orders:
                    best_ask = min(sell_orders.keys())
                    qty = min(10, max_position - position)
                    position += qty
                    cash -= best_ask * qty
                    buy_trades += 1
                    debug_trades.append(('BUY', i, mid_price, fv, best_ask, qty, cash))

        # 卖出逻辑
        if position > 0:
            if mid_price >= fv + threshold:
                if buy_orders:
                    best_bid = max(buy_orders.keys())
                    qty = position  # 全部卖出
                    cash += best_bid * qty
                    position = 0
                    sell_trades += 1
                    debug_trades.append(('SELL', i, mid_price, fv, best_bid, qty, cash))

    # 最终平仓
    final_price = prices[-1]
    if position > 0:
        cash += final_price * position

    return {
        'buy_trades': buy_trades,
        'sell_trades': sell_trades,
        'position': position,
        'pnl': cash,
        'debug': debug_trades
    }


def main():
    # 只用一个数据集
    json_file = '/Users/minimx/Downloads/276946/276946.json'
    ash_data = load_ash_data(json_file)

    print(f"数据点: {len(ash_data)}")

    for threshold in [3, 5]:
        print(f"\n{'='*50}")
        print(f"阈值={threshold}")
        print(f"{'='*50}")

        r = simulate_market_making(ash_data, threshold)
        print(f"买入次数: {r['buy_trades']}")
        print(f"卖出次数: {r['sell_trades']}")
        print(f"最终持仓: {r['position']}")
        print(f"PnL: {r['pnl']}")

        print("\n前10笔交易:")
        for t in r['debug'][:10]:
            print(f"  t={t[1]}: {t[0]}, mid={t[2]:.1f}, fv={t[3]:.1f}, exec={t[4]}, qty={t[5]}, cash={t[6]:.0f}")


if __name__ == '__main__':
    main()