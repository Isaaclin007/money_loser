# -*- coding: utf-8 -*-
"""
三号策略
网格交易法，方法如下，起始10w
初始买入5w，涨x%卖出5k，跌x%买入5k

后记： 这个策略如果钱没有限制，回测起来效果还是不错的。
但对于比特币之类的，很容易就能想到，如果一次性涨了很多，或者一次性跌了很多，就立马炸了。（止盈但是不止损，分分钟就会爆炸）

再记： 在大盘爆炸的时候，如果没有及时撤离的话也也是会爆炸的 这个策略在时长波动的时候效果很不错，但是无法避免大盘爆炸。
更需要的东西应该是在大盘爆炸的时候及时止损的东西

网格策略更新：增加atr指标，不过对结果好像是负影响...
"""
import logging

from trader_v2.strategy.base import StrategyBase
from trader_v2.strategy.util import BarManager, ArrayManagerDF

logger = logging.getLogger("strategy.grid")


class StrategyThree(StrategyBase):
    """
    网格交易策略
    因为下的单都是限价单，且挂的是高价卖单，低价买单，所以可以在基准确定的时候提前下单。
    """
    __name__ = "strategy three （grid strategy）"

    def __init__(self, strategy_engine, account, symbol, buy_x, sell_x, per_count, base_price=None):
        """

        :param strategy_engine: 
        :param account: 
        :param symbol: 
        :param buy_x: 下跌buy_x买入
        :param sell_x: 上涨sell_x卖出
        :param per_count: 每浮动1%交易的量
        :param base_price: 
        """
        super(StrategyThree, self).__init__(strategy_engine, account)
        self.symbol = symbol
        # 每次上涨或下跌x触发策略
        self.buy_x = buy_x / 100.0
        self.sell_x = sell_x / 100.0
        # 每次买入/卖出的份额
        self.per_count = per_count
        # 基准价格
        self.base_price = base_price
        # 上一次市场上交易成功的价格
        self.last_trade_price = None
        self.ready = False
        self.base_currency, self.quote_currency = account.split_symbol(symbol)

        self.buy_order_id = None
        self.sell_order_id = None

        self.bar_manager = BarManager(on_bar=self.on_bar)
        self.array_manager = ArrayManagerDF()

    def start(self):
        StrategyBase.start(self)
        self.request_1day_kline(self.symbol)
        self.ready = False

    def on_1day_kline_req(self, klines):
        """
        在收到历史kline的时候，需要做两件事
        1、设置一个策略的base价格
        2、计算atr，通过atr计算幅度
        """
        bar_last = klines[-1]
        if not self.base_price:
            self.base_price = bar_last.close
        self.last_trade_price = bar_last.close
        self.ready = True
        self.subscribe_market_trade(self.symbol)

        for kline in klines:
            self.bar_manager.update_from_bar(kline)
        # self.subscribe_1day_kline(symbol=self.symbol)
        self.subscribe_1day_kline(symbol=self.symbol)

        if not self.buy_order_id or not self.sell_order_id:
            self.on_base_change()

    def on_1day_kline(self, bar_data):
        self.bar_manager.update_from_bar(bar_data)

    def on_bar(self, bar):
        self.array_manager.update_bar(bar)
        if self.array_manager.count > 7:
            atr = self.array_manager.atr(7)
            self.sell_x = self.buy_x = max(3 / 100.0, atr / self.base_price * 2)

    def on_market_trade(self, market_trade_item):
        self.last_trade_price = market_trade_item.price

    def on_base_change(self):
        """
        在基准价格改变时调用这个方法
        会先取消掉之前下的两个单（应该只有一个能成功执行），根据基准价格下两个新单
        :return: 
        """
        logger.debug("on base change , now base is {base}".format(base=self.base_price))
        # 取消之前下的单
        if self.buy_order_id:
            self.strategy_engine.cancel_order(self.buy_order_id)
        if self.sell_order_id:
            self.strategy_engine.cancel_order(self.sell_order_id)
        # 计算新单价格并下单
        low_price = round(min(self.base_price * (1 - self.buy_x), self.last_trade_price),
                          self.account.price_precision(self.symbol))
        high_price = round(max(self.base_price * (1 + self.sell_x), self.last_trade_price),
                           self.account.price_precision(self.symbol))
        buy_low_count = int(
            min(self.per_count * self.buy_x * 100, self.account.position(self.quote_currency) / low_price))
        sell_high_count = int(min(self.per_count * self.sell_x * 100, self.account.position(self.base_currency)))
        logger.info("send limit buy order , {symbol} price: {p} , count:{c}".format(symbol=self.symbol, p=low_price,
                                                                                    c=buy_low_count))
        self.buy_order_id = self.strategy_engine.limit_buy(self.symbol, low_price, buy_low_count,
                                                           complete_callback=self.order_deal)
        logger.info("send limit sell order , {symbol} price: {p} , count:{c}".format(symbol=self.symbol, p=high_price,
                                                                                     c=sell_high_count))
        self.sell_order_id = self.strategy_engine.limit_sell(self.symbol, high_price, sell_high_count,
                                                             complete_callback=self.order_deal)

    def order_deal(self, order_id):
        if order_id == self.buy_order_id:
            logger.info("buy order complete")
            self.base_price = self.base_price * (1 - self.buy_x)
            self.on_base_change()
        elif order_id == self.sell_order_id:
            logger.info("sell order complete")
            self.base_price = self.base_price * (1 + self.sell_x)
            self.on_base_change()
        else:
            logger.error("order not exist")

    def stop(self):
        """
        取消之前这个策略下的单
        :return: 
        """
        logger.info("starting close")
        if self.buy_order_id:
            logger.info("cancel buy order")
            self.strategy_engine.cancel_order(self.buy_order_id)
        if self.sell_order_id:
            logger.info("cancel sell order")
            self.strategy_engine.cancel_order(self.sell_order_id)
        StrategyBase.stop(self)
