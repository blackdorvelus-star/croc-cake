"""Is the ICT sweep/MSS/(FVG) entry signal distinguishable from chance?

This runs a lightweight Monte Carlo permutation test: for each ICT
strategy, take its actual closed-trade performance on the real EUR/USD H1
data and compare it against many runs of RandomKillzoneEntryStrategy on
the *same* data, *same* killzones, *same* cost models, and *same*
fixed-fractional risk sizing -- entry timing replaced by a coin flip,
everything else held constant, and the random baseline's entry rate
calibrated so its average trade count matches the ICT strategy's.

If the ICT strategy's result sits comfortably inside the random
distribution, its "edge" is not distinguishable from noise on this data --
which, given the data's severe limitations (see README.md: ~4 months of
H1 bars during the March 2020 COVID crash), is the expected, honest
outcome here. This script exists to run that check properly, not to
manufacture a positive result.

Run with:
    python -m backtesting_engine.examples.run_thesis_validation
"""
from __future__ import annotations

import logging
import queue
import statistics
from typing import Callable, List, Tuple

from backtesting_engine import (
    Backtest,
    ForexCommissionModel,
    ForexPositionSizer,
    ForexSlippageModel,
    HistoricCSVDataHandler,
    ICT2022Strategy,
    ICTKillzoneStrategy,
    PerformanceReport,
    Portfolio,
    RandomKillzoneEntryStrategy,
    RiskManager,
    SimulatedExecutionHandler,
    Strategy,
    compute_performance_report,
)
from backtesting_engine.examples.run_real_eurusd_backtest import KILLZONE_REFERENCE_TIMEZONE, load_real_eurusd_h1

PIP_VALUE = 0.0001
RISK_PER_TRADE_PCT = 0.01
INITIAL_CAPITAL = 100_000.0
SYMBOL = "EURUSD"

logger = logging.getLogger(__name__)


def run_pipeline(strategy_factory: Callable[["queue.Queue"], Strategy], symbol_data) -> Tuple[Portfolio, RiskManager]:
    """Wires one strategy into the full engine (same cost/sizing/risk
    stack every time) and runs it to completion."""
    event_queue: "queue.Queue" = queue.Queue()
    data_handler = HistoricCSVDataHandler(event_queue, {SYMBOL: symbol_data})
    strategy = strategy_factory(event_queue)

    position_sizer = ForexPositionSizer(risk_per_trade_pct=RISK_PER_TRADE_PCT, pip_value_per_standard_lot=10.0)
    portfolio = Portfolio(
        symbol_list=[SYMBOL], initial_capital=INITIAL_CAPITAL, position_sizer=position_sizer, fixed_order_quantity=1_000
    )
    # Rate limit set very high on purpose: it is wall-clock based (real
    # elapsed seconds during replay), so how many orders it lets through
    # would otherwise depend on incidental CPU speed differences between
    # runs rather than on anything about the strategies being compared.
    # The drawdown kill switch stays at its normal setting since hitting
    # it *is* a meaningful, comparable outcome.
    risk_manager = RiskManager(portfolio=portfolio, max_orders_per_minute=1_000, max_drawdown_pct=0.02)
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
        heartbeat_timeout_seconds=30.0,
    )
    backtest.run()
    return portfolio, risk_manager


def _average_trade_count(symbol_data, entry_probability: float, seeds: range) -> float:
    counts = []
    for seed in seeds:
        portfolio, _ = run_pipeline(
            lambda q, p=entry_probability, s=seed: RandomKillzoneEntryStrategy(
                symbol_list=[SYMBOL],
                event_queue=q,
                entry_probability_per_bar=p,
                stop_loss_pips=20.0,
                reference_timezone=KILLZONE_REFERENCE_TIMEZONE,
                random_seed=s,
            ),
            symbol_data,
        )
        counts.append(len(portfolio.closed_trades))
    return statistics.mean(counts)


def calibrate_entry_probability(symbol_data, target_trades: int, calibration_seeds: int = 20) -> float:
    """Binary-searches entry_probability_per_bar so the random baseline's
    average trade count over `calibration_seeds` runs matches the target."""
    if target_trades <= 0:
        return 0.01  # arbitrary low-activity default; nothing to match against
    lo, hi = 1e-4, 1.0
    seeds = range(calibration_seeds)
    for _ in range(12):
        mid = (lo + hi) / 2
        avg_trades = _average_trade_count(symbol_data, mid, seeds)
        if avg_trades < target_trades:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def run_monte_carlo_baseline(
    symbol_data, entry_probability: float, num_runs: int = 200
) -> List[PerformanceReport]:
    reports = []
    for seed in range(num_runs):
        portfolio, _ = run_pipeline(
            lambda q, p=entry_probability, s=seed: RandomKillzoneEntryStrategy(
                symbol_list=[SYMBOL],
                event_queue=q,
                entry_probability_per_bar=p,
                stop_loss_pips=20.0,
                reference_timezone=KILLZONE_REFERENCE_TIMEZONE,
                random_seed=s,
            ),
            symbol_data,
        )
        reports.append(compute_performance_report(portfolio, risk_per_trade_pct=RISK_PER_TRADE_PCT))
    return reports


def evaluate_strategy(name: str, strategy_factory: Callable[["queue.Queue"], Strategy], symbol_data) -> None:
    print(f"\n=== {name} ===")
    portfolio, risk_manager = run_pipeline(strategy_factory, symbol_data)
    report = compute_performance_report(portfolio, risk_per_trade_pct=RISK_PER_TRADE_PCT)
    print(f"Actual result: {report}")
    if risk_manager.trading_halted:
        print(f"(RiskManager halted trading: {risk_manager.halt_reason})")

    if report.num_trades == 0:
        print("No closed trades -- nothing to compare against a random baseline.")
        return

    calibrated_p = calibrate_entry_probability(symbol_data, target_trades=report.num_trades)
    baseline_reports = run_monte_carlo_baseline(symbol_data, calibrated_p, num_runs=200)
    baseline_pnls = [r.total_pnl for r in baseline_reports]
    avg_baseline_trades = statistics.mean(r.num_trades for r in baseline_reports)

    beat_or_tied = sum(1 for pnl in baseline_pnls if pnl >= report.total_pnl)
    empirical_p_value = beat_or_tied / len(baseline_pnls)

    print(
        f"Random baseline (n=200 seeds, calibrated to ~{avg_baseline_trades:.1f} trades/run, "
        f"p_entry={calibrated_p:.4f}):"
    )
    print(
        f"  mean total_pnl={statistics.mean(baseline_pnls):+.2f}  "
        f"median={statistics.median(baseline_pnls):+.2f}  "
        f"stdev={statistics.pstdev(baseline_pnls):.2f}"
    )
    print(
        f"  P(random total_pnl >= actual {report.total_pnl:+.2f}) = {empirical_p_value:.3f}  "
        f"({beat_or_tied}/200 random runs matched or beat the real strategy)"
    )
    if empirical_p_value > 0.10:
        print(
            "  -> Not distinguishable from chance at this sample size: the strategy's "
            "result is well within what random entries produce on this data."
        )
    else:
        print(
            "  -> The real strategy beat random entries more often than a 10% threshold "
            "would predict by chance -- suggestive, but still not proof with this few trades."
        )


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    symbol_data = load_real_eurusd_h1()
    print(f"Loaded {len(symbol_data)} real EUR/USD H1 bars: {symbol_data.index[0]} -> {symbol_data.index[-1]}")

    evaluate_strategy(
        "ICTKillzoneStrategy",
        lambda q: ICTKillzoneStrategy(
            symbol_list=[SYMBOL], event_queue=q, swing_lookback=10, mss_confirmation_bars=5,
            pip_value=PIP_VALUE, reference_timezone=KILLZONE_REFERENCE_TIMEZONE,
        ),
        symbol_data,
    )
    evaluate_strategy(
        "ICT2022Strategy",
        lambda q: ICT2022Strategy(
            symbol_list=[SYMBOL], event_queue=q, max_bars_awaiting_mss=15, max_bars_awaiting_fvg=10,
            pip_value=PIP_VALUE, reference_timezone=KILLZONE_REFERENCE_TIMEZONE,
        ),
        symbol_data,
    )


if __name__ == "__main__":
    main()
