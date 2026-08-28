"""Forex-specific transaction-cost and position-sizing models.

`ForexCommissionModel` and `ForexSlippageModel` implement the same call
signatures as the generic `CommissionModel` / `SlippageModel` in
`execution_handler.py` (Liskov Substitution: pass either pair to
`SimulatedExecutionHandler` interchangeably), but price things the way FX
ECN brokers actually do -- commission per standard lot of volume traded
(independent of price), and slippage in pips rather than a percentage of
notional.

`ForexPositionSizer` is a different concern (position sizing, not
execution cost): it turns a percentage-of-equity risk budget and a
stop-loss distance in pips into a lot size -- the standard "fixed
fractional risk" formula. It satisfies the `PositionSizer` protocol
`Portfolio` depends on (see `portfolio.py`), so it plugs in without
`Portfolio` ever importing this module.
"""
from __future__ import annotations

from typing import Optional

from .event import OrderDirection


class ForexCommissionModel:
    """Per-standard-lot commission, as charged by ECN/raw-spread brokers.

    Unlike a percentage-of-notional model, FX ECN commission is charged on
    *volume traded* (lots), independent of the instrument's price.
    """

    def __init__(self, commission_per_standard_lot: float = 3.0, standard_lot_size: float = 100_000.0) -> None:
        if commission_per_standard_lot < 0:
            raise ValueError("commission_per_standard_lot must be non-negative")
        if standard_lot_size <= 0:
            raise ValueError("standard_lot_size must be positive")
        self.commission_per_standard_lot = commission_per_standard_lot
        self.standard_lot_size = standard_lot_size

    def calculate(self, quantity: int, fill_price: float) -> float:
        lots_traded = abs(quantity) / self.standard_lot_size
        return lots_traded * self.commission_per_standard_lot


class ForexSlippageModel:
    """Fixed-pip slippage model for FX pairs.

    Note this models slippage as a constant number of pips, *not* as a
    function of order size the way `execution_handler.SlippageModel` does
    -- a reasonable simplification for retail/small-institutional lot
    sizes on a deep market like EUR/USD, but it means large orders will
    not show increasing impact here. Combine with a size-scaling model
    instead if you intend to size up significantly.
    """

    def __init__(self, slippage_pips: float = 0.5, is_jpy_pair: bool = False) -> None:
        if slippage_pips < 0:
            raise ValueError("slippage_pips must be non-negative")
        self.slippage_pips = slippage_pips
        self.pip_value = 0.01 if is_jpy_pair else 0.0001

    def slipped_price(
        self,
        direction: OrderDirection,
        quantity: int,
        reference_price: float,
        bar_volume: Optional[float] = None,
    ) -> float:
        slippage_amount = self.slippage_pips * self.pip_value
        sign = 1 if direction == OrderDirection.BUY else -1
        return max(reference_price + sign * slippage_amount, 0.0)


class ForexPositionSizer:
    """Fixed-fractional risk sizing: turns a % of equity risk budget and a
    stop-loss distance (in pips) into a standard-lot size.

    `account_equity` is taken per call rather than stored once at
    construction: risking a fixed *percentage* of equity only behaves
    correctly if that equity is the account's *current* mark-to-market
    value, not whatever it was when the sizer was built -- otherwise
    position size never adapts as the account grows or draws down.
    """

    def __init__(self, risk_per_trade_pct: float = 0.01, pip_value_per_standard_lot: float = 10.0) -> None:
        if not (0.0 < risk_per_trade_pct < 1.0):
            raise ValueError("risk_per_trade_pct must be within (0, 1)")
        if pip_value_per_standard_lot <= 0:
            raise ValueError("pip_value_per_standard_lot must be positive")
        self.risk_per_trade_pct = risk_per_trade_pct
        self.pip_value_per_standard_lot = pip_value_per_standard_lot

    def calculate_lot_size(self, account_equity: float, stop_loss_pips: float) -> float:
        if account_equity <= 0:
            raise ValueError("account_equity must be positive")
        if stop_loss_pips <= 0:
            raise ValueError("stop_loss_pips must be positive")

        capital_at_risk = account_equity * self.risk_per_trade_pct
        risk_per_pip = capital_at_risk / stop_loss_pips
        lots = risk_per_pip / self.pip_value_per_standard_lot
        return round(lots, 2)  # nearest micro-lot (0.01)
