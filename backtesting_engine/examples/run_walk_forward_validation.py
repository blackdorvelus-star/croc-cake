"""Walk-forward validation of evidence-based ICT strategy filters.

Tests the concrete improvements from README's "Validation de la these"
research (higher-timeframe bias, R:R take-profit, ADX regime filter)
without curve-fitting: for each rolling fold, a small grid of filter
configurations is evaluated on the fold's TRAIN window only, the single
best-scoring configuration is picked, and that exact configuration --
untouched -- is then run once on the fold's TEST window, which the
selection step never saw. A fully unfiltered baseline is run on the same
test window for direct comparison.

This is not an exhaustive search and there is no guarantee any of it
holds up out-of-sample -- that is the question being asked, not a
foregone conclusion. Whatever the test windows show is reported as-is.

Run with:
    python -m backtesting_engine.examples.run_walk_forward_validation
"""
from __future__ import annotations

import itertools
import logging
import queue
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd

from backtesting_engine import (
    ADXIndicator,
    Backtest,
    DailyBiasFilter,
    ForexCommissionModel,
    ForexPositionSizer,
    ForexSlippageModel,
    HistoricCSVDataHandler,
    ICT2022Strategy,
    ICTKillzoneStrategy,
    PerformanceReport,
    Portfolio,
    RiskManager,
    SimulatedExecutionHandler,
    Strategy,
    compute_performance_report,
)
from backtesting_engine.examples.real_data import load_eurusd_h1_2004_2024

SYMBOL = "EURUSD"
PIP_VALUE = 0.0001
RISK_PER_TRADE_PCT = 0.01
INITIAL_CAPITAL = 100_000.0
KILLZONE_REFERENCE_TIMEZONE = "America/New_York"

# Small, literature-motivated grid (see README) -- not an exhaustive
# search. Each axis includes "off" (None) so the unfiltered baseline is
# always itself a candidate; a filter only wins a fold if it actually
# beat doing without it, on that fold's TRAIN window alone.
HTF_EMA_PERIODS = [None, 50]
REWARD_RISK_RATIOS = [None, 2.0]
ADX_THRESHOLDS = [None, 25.0]

MIN_TRADES_TO_TRUST = 10  # a config selected on fewer trades is not trusted, however lucky


@dataclass
class Fold:
    name: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str


FOLDS = [
    Fold("fold_1", "2004-01-01", "2012-12-31", "2013-01-01", "2018-12-31"),
    Fold("fold_2", "2009-01-01", "2017-12-31", "2018-01-01", "2024-03-29"),
]

Config = Tuple[Optional[int], Optional[float], Optional[float]]  # (htf_ema, reward_risk, adx_threshold)


def build_strategy(strategy_name: str, event_queue: "queue.Queue", config: Config) -> Strategy:
    htf_ema, reward_risk, adx_threshold = config
    htf_bias_filter = DailyBiasFilter(ema_period=htf_ema) if htf_ema else None
    adx_filter = ADXIndicator(period=14) if adx_threshold else None
    kwargs = dict(
        symbol_list=[SYMBOL],
        event_queue=event_queue,
        pip_value=PIP_VALUE,
        reference_timezone=KILLZONE_REFERENCE_TIMEZONE,
        htf_bias_filter=htf_bias_filter,
        adx_filter=adx_filter,
        max_adx_for_entry=adx_threshold,
        reward_risk_ratio=reward_risk,
    )
    if strategy_name == "killzone":
        return ICTKillzoneStrategy(swing_lookback=10, mss_confirmation_bars=5, **kwargs)
    return ICT2022Strategy(max_bars_awaiting_mss=15, max_bars_awaiting_fvg=10, **kwargs)


def run_pipeline(strategy_name: str, symbol_data: pd.DataFrame, config: Config) -> Portfolio:
    event_queue: "queue.Queue" = queue.Queue()
    data_handler = HistoricCSVDataHandler(event_queue, {SYMBOL: symbol_data})
    strategy = build_strategy(strategy_name, event_queue, config)

    position_sizer = ForexPositionSizer(risk_per_trade_pct=RISK_PER_TRADE_PCT, pip_value_per_standard_lot=10.0)
    portfolio = Portfolio(
        symbol_list=[SYMBOL], initial_capital=INITIAL_CAPITAL, position_sizer=position_sizer, fixed_order_quantity=1_000
    )
    risk_manager = RiskManager(portfolio=portfolio, max_orders_per_minute=1_000_000, max_drawdown_pct=0.02)
    execution_handler = SimulatedExecutionHandler(
        event_queue,
        commission_model=ForexCommissionModel(commission_per_standard_lot=3.0),
        slippage_model=ForexSlippageModel(slippage_pips=0.5, is_jpy_pair=False),
    )
    backtest = Backtest(
        data_handler=data_handler,
        strategy=strategy,
        portfolio=portfolio,
        risk_manager=risk_manager,
        execution_handler=execution_handler,
        heartbeat_timeout_seconds=120.0,
    )
    backtest.run()
    return portfolio


def _score(report: PerformanceReport) -> float:
    """Selection metric for TRAIN data only: total P&L, but a config that
    traded too few times to trust its result never wins regardless of how
    lucky it got."""
    if report.num_trades < MIN_TRADES_TO_TRUST:
        return float("-inf")
    return report.total_pnl


def run_fold(strategy_name: str, symbol_data: pd.DataFrame, fold: Fold) -> dict:
    train_data = symbol_data.loc[fold.train_start : fold.train_end]
    test_data = symbol_data.loc[fold.test_start : fold.test_end]

    best_config: Config = (None, None, None)
    best_score = float("-inf")
    best_train_report: Optional[PerformanceReport] = None

    for config in itertools.product(HTF_EMA_PERIODS, REWARD_RISK_RATIOS, ADX_THRESHOLDS):
        portfolio = run_pipeline(strategy_name, train_data, config)
        report = compute_performance_report(portfolio, risk_per_trade_pct=RISK_PER_TRADE_PCT)
        score = _score(report)
        if score > best_score:
            best_score = score
            best_config = config
            best_train_report = report

    test_portfolio = run_pipeline(strategy_name, test_data, best_config)
    test_report = compute_performance_report(test_portfolio, risk_per_trade_pct=RISK_PER_TRADE_PCT)

    baseline_portfolio = run_pipeline(strategy_name, test_data, (None, None, None))
    baseline_report = compute_performance_report(baseline_portfolio, risk_per_trade_pct=RISK_PER_TRADE_PCT)

    return {
        "fold": fold.name,
        "train_range": (fold.train_start, fold.train_end),
        "test_range": (fold.test_start, fold.test_end),
        "selected_config": best_config,
        "train_report": best_train_report,
        "test_report": test_report,
        "baseline_test_report": baseline_report,
    }


def _format_config(config: Config) -> str:
    htf_ema, reward_risk, adx_threshold = config
    return (
        f"htf_ema={htf_ema or 'off'} reward_risk={reward_risk or 'off'} "
        f"adx_threshold={adx_threshold or 'off'}"
    )


def main() -> None:
    logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
    symbol_data = load_eurusd_h1_2004_2024()
    print(f"Loaded {len(symbol_data)} bars: {symbol_data.index[0]} -> {symbol_data.index[-1]}")

    for strategy_name in ["killzone", "2022"]:
        print(f"\n{'=' * 78}\nStrategy: {strategy_name}\n{'=' * 78}")
        for fold in FOLDS:
            result = run_fold(strategy_name, symbol_data, fold)
            print(
                f"\n--- {result['fold']} "
                f"(train {result['train_range'][0]}..{result['train_range'][1]}, "
                f"test {result['test_range'][0]}..{result['test_range'][1]}) ---"
            )
            print(f"Selected on TRAIN: {_format_config(result['selected_config'])}")
            print(f"  train performance: {result['train_report']}")
            print("TEST (out-of-sample, config fixed from train, never re-tuned):")
            print(f"  {result['test_report']}")
            print("TEST baseline (all filters off, same test window):")
            print(f"  {result['baseline_test_report']}")


if __name__ == "__main__":
    main()
