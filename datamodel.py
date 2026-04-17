"""
datamodel.py - 官方API数据模型（本地测试用）

当官方datamodel.py不可用时使用此文件
"""

import json
from typing import Dict, List


class Order:
    def __init__(self, symbol: str, price: int, quantity: int):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

    def __str__(self):
        return f"({self.symbol}, {self.price}, {self.quantity})"

    def __repr__(self):
        return self.__str__()


class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}
        self.sell_orders: Dict[int, int] = {}


class Trade:
    def __init__(self, symbol: str, price: int, quantity: int,
                 buyer: str = None, seller: str = None, timestamp: int = 0):
        self.symbol = symbol
        self.price: int = price
        self.quantity: int = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp

    def __str__(self):
        return f"({self.symbol}, {self.buyer} << {self.seller}, {self.price}, {self.quantity}, {self.timestamp})"

    def __repr__(self):
        return self.__str__()


class Listing:
    def __init__(self, symbol: str, product: str, denomination: str):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination


class ConversionObservation:
    def __init__(self, bidPrice: float, askPrice: float,
                 transportFees: float, exportTariff: float,
                 importTariff: float, sunlight: float, humidity: float):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sunlight = sunlight
        self.humidity = humidity


class Observation:
    def __init__(self, plainValueObservations: Dict = None,
                 conversionObservations: Dict = None):
        self.plainValueObservations = plainValueObservations or {}
        self.conversionObservations = conversionObservations or {}

    def __str__(self):
        return f"(plainValueObservations: {self.plainValueObservations}, conversionObservations: {self.conversionObservations})"


class TradingState:
    def __init__(self,
                 traderData: str,
                 timestamp: int,
                 listings: Dict,
                 order_depths: Dict,
                 own_trades: Dict,
                 market_trades: Dict,
                 position: Dict,
                 observations: Observation):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations

    def toJSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)
