"""
基于模拟器数据的回测框架
用模拟器log中的价格数据来回测策略
"""

import json
import csv
from io import StringIO
from typing import List, Dict, Tuple
import sys
sys.path.insert(0, '/Users/minimx/Downloads/ROUND_2')


def load_simulator_data(json_path: str) -> Tuple[List[dict], List[dict]]:
    """从模拟器json加载价格数据"""
    with open(json_path, 'r') as f:
        data = json.load(f)

    activities = data.get('activitiesLog', '')
    reader = csv.DictReader(StringIO(activities), delimiter=';')

    intarian_data = []
    ash_data = []

    for row in reader:
        if row['product'] == 'INTARIAN_PEPPER_ROOT' and row['mid_price']:
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
        elif row['product'] == 'ASH_COATED_OSMIUM' and row['mid_price']:
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

    return intarian_data, ash_data


class SimpleBacktester:
    """简单回测器"""

    def __init__(self, data_path: str):
        self.intarian, self.ash = load_simulator_data(data_path)

    def backtest_swing(self,
                       buy_threshold: float,
                       sell_threshold: float,
                       stop_loss: float,
                       position_size: int = 80) -> dict:
        """
        波段策略回测

        Args:
            buy_threshold: 买入价格（低于中心价多少）
            sell_threshold: 卖出价格（高于中心价多少）
            stop_loss: 止损价格（低于买入价多少）
            position_size: 仓位大小
        """
        # 使用ASH的中心价作为参考
        ash_prices = [d['mid_price'] for d in self.ash]
        center = sum(ash_prices) / len(ash_prices)

        # INTARIAN波段回测
        intarian_center = 13050  # 从数据观察

        cash = 0
        position = 0
        entry_price = 0
        trades = 0
        pnl_history = []

        for i, row in enumerate(self.intarian):
            mid = row['mid_price']

            # 买入逻辑
            if position == 0:
                if mid <= intarian_center - buy_threshold:
                    # 买入
                    position = position_size
                    entry_price = mid
                    cash -= mid * position_size
                    trades += 1

            # 持仓逻辑
            elif position > 0:
                sell_price = entry_price + sell_threshold
                stop_price = entry_price - stop_loss

                # 止盈
                if mid >= sell_price:
                    cash += mid * position
                    pnl = cash
                    pnl_history.append(pnl)
                    position = 0
                    entry_price = 0
                    trades += 1

                # 止损
                elif mid <= stop_price:
                    cash += mid * position
                    pnl = cash
                    pnl_history.append(pnl)
                    position = 0
                    entry_price = 0
                    trades += 1

        # 如果还有持仓，按最后价格计算
        if position > 0:
            final_price = self.intarian[-1]['mid_price']
            cash += final_price * position

        return {
            'final_pnl': cash,
            'trades': trades,
            'position': position
        }

    def grid_search(self):
        """网格搜索最优参数"""
        best_pnl = -float('inf')
        best_params = None

        print("网格搜索最优波段参数...")
        print(f"{'Buy':>8} {'Sell':>8} {'Stop':>8} {'PnL':>12} {'Trades':>8}")

        for buy in range(10, 80, 10):
            for sell in range(10, 80, 10):
                for stop in range(5, 30, 5):
                    result = self.backtest_swing(buy, sell, stop)
                    pnl = result['final_pnl']

                    if pnl > best_pnl:
                        best_pnl = pnl
                        best_params = (buy, sell, stop)
                        print(f"{buy:8d} {sell:8d} {stop:8d} {pnl:12.0f} {result['trades']:8d}")

        print(f"\n最优参数: buy={best_params[0]}, sell={best_params[1]}, stop={best_params[2]}")
        print(f"最优PnL: {best_pnl:.0f}")

        return best_params, best_pnl


if __name__ == '__main__':
    # 使用模拟器数据回测
    backtester = SimpleBacktester('/Users/minimx/Downloads/276946/276946.json')

    # 先做网格搜索找最优参数
    best_params, best_pnl = backtester.grid_search()

    # 用最优参数回测
    print("\n=== 最优参数回测结果 ===")
    result = backtester.backtest_swing(*best_params)
    print(f"最终PnL: {result['final_pnl']:.0f}")
    print(f"交易次数: {result['trades']}")
