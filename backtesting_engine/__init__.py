"""Event-driven backtesting engine skeleton for ML-based trading strategies.

See README.md in this directory for architecture notes and usage. Public
API is re-exported here for convenience.
"""
from .data_handler import DataHandler, HistoricCSVDataHandler
from .engine import Backtest, MarketDataStallError
from .event import (
    Event,
    EventType,
    FillEvent,
    LiquidateEvent,
    MarketEvent,
    OrderDirection,
    OrderEvent,
    OrderType,
    SignalDirection,
    SignalEvent,
)
from .execution_handler import CommissionModel, ExecutionHandler, SimulatedExecutionHandler, SlippageModel
from .forex_cost_models import ForexCommissionModel, ForexPositionSizer, ForexSlippageModel
from .ict_strategy import DEFAULT_KILLZONES, ICTKillzoneStrategy, Killzone
from .ml_model import DummyXGBoostSignalModel
from .portfolio import Portfolio, PositionSizer
from .risk_manager import RiskManager
from .strategy import MLMomentumStrategy, Strategy

__all__ = [
    "Backtest",
    "MarketDataStallError",
    "Event",
    "EventType",
    "FillEvent",
    "LiquidateEvent",
    "MarketEvent",
    "OrderDirection",
    "OrderEvent",
    "OrderType",
    "SignalDirection",
    "SignalEvent",
    "DataHandler",
    "HistoricCSVDataHandler",
    "MLMomentumStrategy",
    "Strategy",
    "ICTKillzoneStrategy",
    "Killzone",
    "DEFAULT_KILLZONES",
    "DummyXGBoostSignalModel",
    "Portfolio",
    "PositionSizer",
    "RiskManager",
    "CommissionModel",
    "ExecutionHandler",
    "SimulatedExecutionHandler",
    "SlippageModel",
    "ForexCommissionModel",
    "ForexSlippageModel",
    "ForexPositionSizer",
]
