import logging

from config.cst import CONFIG_ENABLED_OPTION, CONFIG_TRADER, CONFIG_TRADER_RISK, CONFIG_TRADER_RISK_MIN, \
    CONFIG_TRADER_RISK_MAX, OrderStatus
from tools.pretty_printer import PrettyPrinter
from trading.trader.order import OrderConstants
from trading.trader.order_notifier import OrderNotifier
from trading.trader.orders_manager import OrdersManager
from trading.trader.portfolio import Portfolio
from trading.trader.trade import Trade
from trading.trader.trades_manager import TradesManager


class Trader:
    def __init__(self, config, exchange):
        self.exchange = exchange
        self.config = config
        self.risk = None
        self.set_risk(self.config[CONFIG_TRADER][CONFIG_TRADER_RISK])
        self.logger = logging.getLogger(self.__class__.__name__)

        if not hasattr(self, 'simulate'):
            self.simulate = False

        self.portfolio = Portfolio(self.config, self)

        self.trades_manager = TradesManager(config, self)

        self.order_manager = OrdersManager(config, self)

        if self.enabled():
            self.order_manager.start()
            self.logger.debug("Enabled on " + self.exchange.get_name())
        else:
            self.logger.debug("Disabled on " + self.exchange.get_name())

    def enabled(self):
        if self.config[CONFIG_TRADER][CONFIG_ENABLED_OPTION]:
            return True
        else:
            return False

    def get_risk(self):
        return self.risk

    def set_risk(self, risk):
        if risk < CONFIG_TRADER_RISK_MIN:
            self.risk = CONFIG_TRADER_RISK_MIN
        elif risk > CONFIG_TRADER_RISK_MAX:
            self.risk = CONFIG_TRADER_RISK_MAX
        else:
            self.risk = risk

    def get_exchange(self):
        return self.exchange

    def get_portfolio(self):
        return self.portfolio

    def create_order(self, order_type, symbol, current_price, quantity, price=None, stop_price=None, linked_to=None):
        self.logger.info("Order creation : {0} | {1} | Price : {2} | Quantity : {3}".format(symbol,
                                                                                            order_type,
                                                                                            price,
                                                                                            quantity))

        # create new order instance
        order_class = OrderConstants.TraderOrderTypeClasses[order_type]
        order = order_class(self)

        # manage order notifier
        if linked_to is None:
            order_notifier = OrderNotifier(self.config, order)
        else:
            order_notifier = linked_to.get_order_notifier()

        order.new(order_type, symbol, current_price, quantity, price, stop_price, order_notifier)

        # update the availability of the currency in the portfolio
        with self.portfolio as pf:
            pf.update_portfolio_available(order, is_new_order=True)

        # notify order manager of a new open order
        self.order_manager.add_order_to_list(order)

        # if this order is linked to another (ex : a sell limit order with a stop loss order)
        if linked_to is not None:
            linked_to.add_linked_order(order)
            order.add_linked_order(linked_to)

        return order

    def cancel_order(self, order):
        with order as odr:
            odr.cancel_order()
        self.order_manager.remove_order_from_list(order)

    # Should be called only if we want to cancel all symbol open orders (no filled)
    def cancel_open_orders(self, symbol):
        # use a copy of the list (not the reference)
        for order in list(self.get_open_orders()):
            if order.get_order_symbol() == symbol and order.get_status() is not OrderStatus.CANCELED:
                self.notify_order_close(order, True)

    def notify_order_cancel(self, order):
        # update portfolio with ended order
        with self.portfolio as pf:
            pf.update_portfolio_available(order, is_new_order=False)

    def notify_order_close(self, order, cancel=False):
        # Cancel linked orders
        for linked_order in order.get_linked_orders():
            self.cancel_order(linked_order)

        # If need to cancel the order call the method and no need to update the portfolio (only availability)
        if cancel:
            order_closed = None
            orders_canceled = order.get_linked_orders() + [order]

            self.cancel_order(order)
            _, profitability_percent, profitability_diff = self.get_trades_manager().get_profitability_without_update()

            with self.portfolio as pf:
                # ensure availability reset
                pf.reset_portfolio_available()

        else:
            order_closed = order
            orders_canceled = order.get_linked_orders()

            # update portfolio with ended order
            with self.portfolio as pf:
                pf.update_portfolio(order)

            # debug purpose
            profitability, profitability_percent, profitability_diff = self.get_trades_manager().get_profitability()

            self.logger.info("Current portfolio profitability : {0}".format(
                PrettyPrinter.portfolio_profitability_pretty_print(profitability,
                                                                   profitability_percent,
                                                                   self.get_trades_manager().get_reference())))

            # add to trade history
            self.trades_manager.add_new_trade_in_history(Trade(self.exchange, order))

            # remove order to open_orders
            self.order_manager.remove_order_from_list(order)

        if order_closed is not None:
            profitability_activated = True
        else:
            profitability_activated = False

        # notification
        order.get_order_notifier().end(order_closed,
                                       orders_canceled,
                                       order.get_profitability(),
                                       profitability_percent,
                                       profitability_diff,
                                       profitability_activated)

    def get_open_orders(self):
        return self.order_manager.get_open_orders()

    def close_open_orders(self):
        pass

    def update_open_orders(self):
        # see exchange
        # -> update order manager
        pass

    def get_order_manager(self):
        return self.order_manager

    def get_trades_manager(self):
        return self.trades_manager

    def stop_order_manager(self):
        self.order_manager.stop()

    def join_order_manager(self):
        if self.order_manager.isAlive():
            self.order_manager.join()

    def get_simulate(self):
        return self.simulate
