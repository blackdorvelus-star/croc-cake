"""Event-driven backtesting engine skeleton for ML-based trading strategies.

See README.md in this directory for architecture notes and usage. Public
API is re-exported here for convenience.
"""
from .analytics import PerformanceReport, compute_performance_report
from .data_handler import DataHandler, HistoricCSVDataHandler
from .engine import Backtest, MarketDataStallError
from .entry_filters import passes_entry_filters
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
from .htf_bias import Bias, DailyBiasFilter
from .ict_2022_strategy import FractalSwingDetector, ICT2022Strategy
from .ict_strategy import DEFAULT_KILLZONES, ICTKillzoneStrategy, Killzone, KillzoneFilter
from .indicators import ADXIndicator
from .ml_model import DummyXGBoostSignalModel
from .portfolio import Portfolio, PositionSizer, TradeRecord
from .random_baseline_strategy import RandomKillzoneEntryStrategy
from .risk_manager import RiskManager
from .strategy import MLMomentumStrategy, Strategy
from .trade_management import TakeProfitManager

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
    "ICT2022Strategy",
    "FractalSwingDetector",
    "Killzone",
    "KillzoneFilter",
    "DEFAULT_KILLZONES",
    "DummyXGBoostSignalModel",
    "Portfolio",
    "PositionSizer",
    "TradeRecord",
    "PerformanceReport",
    "compute_performance_report",
    "RandomKillzoneEntryStrategy",
    "RiskManager",
    "CommissionModel",
    "ExecutionHandler",
    "SimulatedExecutionHandler",
    "SlippageModel",
    "ForexCommissionModel",
    "ForexSlippageModel",
    "ForexPositionSizer",
    "Bias",
    "DailyBiasFilter",
    "ADXIndicator",
    "TakeProfitManager",
    "passes_entry_filters",
]
