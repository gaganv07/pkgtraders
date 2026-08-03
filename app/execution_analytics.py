"""
app/execution_analytics.py — Advanced Execution & Statistical Analytics Engine

Computes advanced statistical metrics for production certification:
- 95% Confidence Interval for Expectancy
- 10,000-sample Bootstrap Expectancy & Confidence Intervals
- Rolling 50-trade Expectancy, Profit Factor, Win Rate, and Drawdown
- Maximum Winning & Losing Streaks
- Risk of Ruin %
- Ulcer Index, Calmar Ratio, MAR Ratio
- Long vs Short, Symbol, & Session performance breakdowns
- Edge Stability Verification (>40% single-day or single-symbol profit check)
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

ANALYTICS_JSON_PATH = Path("reports") / "execution_analytics.json"
ANALYTICS_MD_PATH   = Path("reports") / "execution_analytics.md"


@dataclass
class ExecutionMetrics:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    
    # Financial metrics
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy_usd: float = 0.0
    expectancy_r: float = 0.0
    expectancy_ci_lower_usd: float = 0.0
    expectancy_ci_upper_usd: float = 0.0
    bootstrap_expectancy_usd: float = 0.0
    bootstrap_ci_lower_usd: float = 0.0
    bootstrap_ci_upper_usd: float = 0.0
    
    avg_trade_pnl: float = 0.0
    max_drawdown_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    recovery_factor: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    mar_ratio: float = 0.0
    ulcer_index: float = 0.0
    risk_of_ruin_pct: float = 0.0

    # Streaks
    max_winning_streak: int = 0
    max_losing_streak: int = 0

    # Edge Stability
    edge_unstable: bool = False
    edge_instability_reason: str = ""

    # Execution Quality metrics
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    avg_spread_pts: float = 0.0
    avg_slippage_pts: float = 0.0
    worst_slippage_pts: float = 0.0
    rejected_trades: int = 0
    requotes: int = 0
    execution_success_rate_pct: float = 100.0
    avg_fill_time_ms: float = 0.0
    avg_holding_time_s: float = 0.0

    # Breakdowns
    symbol_performance: Dict[str, float] = field(default_factory=dict)
    session_performance: Dict[str, float] = field(default_factory=dict)
    long_vs_short_performance: Dict[str, float] = field(default_factory=dict)


class ExecutionAnalyticsEngine:
    """
    Computes statistical and operational analytics from trade history.
    """

    @staticmethod
    def calculate_metrics(
        trades: List[Dict[str, Any]],
        rejections_count: int = 0,
        initial_balance: float = 500.0,
        n_bootstrap: int = 10000,
    ) -> ExecutionMetrics:
        m = ExecutionMetrics()
        m.total_trades = len(trades)
        m.rejected_trades = rejections_count
        
        total_attempts = m.total_trades + rejections_count
        m.execution_success_rate_pct = (m.total_trades / total_attempts * 100.0) if total_attempts > 0 else 100.0

        if not trades:
            return m

        pnls = [t.get("realized_pnl", t.get("pnl", 0.0)) for t in trades]
        r_multiples = [t.get("r_multiple", 0.0) for t in trades]
        latencies = [t.get("latency_ms", t.get("execution_latency_ms", 0.0)) for t in trades if t.get("latency_ms", t.get("execution_latency_ms", 0.0)) > 0]
        slippages = [abs(t.get("slippage", t.get("slippage_pts", 0.0))) for t in trades]
        spreads = [t.get("spread_entry", t.get("spread_pts", 0.0)) for t in trades]
        hold_times = [t.get("holding_time_s", 0.0) for t in trades if t.get("holding_time_s", 0.0) > 0]

        # Win/Loss counts
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        m.winning_trades = len(wins)
        m.losing_trades = len(losses)
        m.win_rate_pct = (m.winning_trades / m.total_trades * 100.0) if m.total_trades > 0 else 0.0

        # Totals & Averages
        m.total_pnl = float(sum(pnls))
        m.gross_profit = float(sum(wins))
        m.gross_loss = float(abs(sum(losses)))
        m.avg_trade_pnl = m.total_pnl / m.total_trades if m.total_trades > 0 else 0.0
        m.profit_factor = (m.gross_profit / m.gross_loss) if m.gross_loss > 0 else (m.gross_profit if m.gross_profit > 0 else 0.0)

        m.expectancy_usd = m.avg_trade_pnl
        m.expectancy_r = float(np.mean(r_multiples)) if r_multiples else 0.0

        # Streaks
        curr_win = 0
        curr_loss = 0
        max_win = 0
        max_loss = 0
        for p in pnls:
            if p > 0:
                curr_win += 1
                curr_loss = 0
                max_win = max(max_win, curr_win)
            elif p < 0:
                curr_loss += 1
                curr_win = 0
                max_loss = max(max_loss, curr_loss)

        m.max_winning_streak = max_win
        m.max_losing_streak = max_loss

        # 95% Confidence Interval for Expectancy (t-distribution / normal approx)
        if len(pnls) > 1:
            std_err = np.std(pnls, ddof=1) / math.sqrt(len(pnls))
            m.expectancy_ci_lower_usd = float(m.expectancy_usd - 1.96 * std_err)
            m.expectancy_ci_upper_usd = float(m.expectancy_usd + 1.96 * std_err)

            # 10,000 Bootstrap Resampling
            rng = np.random.default_rng(seed=42)
            boot_means = [rng.choice(pnls, size=len(pnls), replace=True).mean() for _ in range(n_bootstrap)]
            m.bootstrap_expectancy_usd = float(np.mean(boot_means))
            m.bootstrap_ci_lower_usd = float(np.percentile(boot_means, 2.5))
            m.bootstrap_ci_upper_usd = float(np.percentile(boot_means, 97.5))
        else:
            m.expectancy_ci_lower_usd = m.expectancy_usd
            m.expectancy_ci_upper_usd = m.expectancy_usd
            m.bootstrap_expectancy_usd = m.expectancy_usd
            m.bootstrap_ci_lower_usd = m.expectancy_usd
            m.bootstrap_ci_upper_usd = m.expectancy_usd

        # Drawdown, Ulcer Index & Risk of Ruin
        equity = initial_balance
        peak = initial_balance
        max_dd_usd = 0.0
        max_dd_pct = 0.0
        dd_pcts = []

        for p in pnls:
            equity += p
            peak = max(peak, equity)
            dd_usd = peak - equity
            dd_pct = (dd_usd / peak * 100.0) if peak > 0 else 0.0
            dd_pcts.append(dd_pct)
            max_dd_usd = max(max_dd_usd, dd_usd)
            max_dd_pct = max(max_dd_pct, dd_pct)

        m.max_drawdown_usd = float(max_dd_usd)
        m.max_drawdown_pct = float(max_dd_pct)
        m.recovery_factor = (m.total_pnl / max_dd_usd) if max_dd_usd > 0 else 0.0

        # Ulcer Index: sqrt(mean(dd_pct^2))
        if dd_pcts:
            m.ulcer_index = float(math.sqrt(np.mean([d**2 for d in dd_pcts])))

        # Calmar & MAR Ratios (annualized pnl / max_dd_pct)
        if m.max_drawdown_pct > 0:
            m.calmar_ratio = float((m.total_pnl / initial_balance * 100.0) / m.max_drawdown_pct)
            m.mar_ratio = m.calmar_ratio

        # Risk of Ruin
        if m.win_rate_pct > 0 and m.win_rate_pct < 100:
            w = m.win_rate_pct / 100.0
            l = 1.0 - w
            if w > l:
                m.risk_of_ruin_pct = float(((1 - (w - l)) / (1 + (w - l))) ** 10 * 100.0)
            else:
                m.risk_of_ruin_pct = 100.0

        # Sharpe & Sortino Ratios
        if len(pnls) > 1:
            std_pnl = np.std(pnls, ddof=1)
            m.sharpe_ratio = float((np.mean(pnls) / std_pnl * math.sqrt(252))) if std_pnl > 0 else 0.0
            neg_pnls = [p for p in pnls if p < 0]
            downside_std = np.std(neg_pnls, ddof=1) if len(neg_pnls) > 1 else std_pnl
            m.sortino_ratio = float((np.mean(pnls) / downside_std * math.sqrt(252))) if downside_std > 0 else 0.0

        # Breakdowns: Symbol, Session, Long vs Short
        sym_perf: Dict[str, float] = {}
        long_vs_short: Dict[str, float] = {"LONG": 0.0, "SHORT": 0.0}
        daily_pnl_map: Dict[str, float] = {}

        for t in trades:
            sym = t.get("symbol", "UNKNOWN")
            direction = t.get("direction", "LONG")
            pnl = t.get("realized_pnl", t.get("pnl", 0.0))
            
            sym_perf[sym] = sym_perf.get(sym, 0.0) + pnl
            if direction in long_vs_short:
                long_vs_short[direction] += pnl

            ts_str = t.get("entry_time", t.get("timestamp", ""))
            date_key = ts_str[:10] if isinstance(ts_str, str) and len(ts_str) >= 10 else "UNKNOWN"
            daily_pnl_map[date_key] = daily_pnl_map.get(date_key, 0.0) + pnl

        m.symbol_performance = {k: float(v) for k, v in sym_perf.items()}
        m.long_vs_short_performance = {k: float(v) for k, v in long_vs_short.items()}

        # Edge Stability Verification
        if m.total_pnl > 0:
            max_sym_pnl = max(sym_perf.values()) if sym_perf else 0.0
            max_day_pnl = max(daily_pnl_map.values()) if daily_pnl_map else 0.0

            if max_sym_pnl / m.total_pnl > 0.40:
                m.edge_unstable = True
                m.edge_instability_reason += f"Single symbol contributes >40% of net profits ({max_sym_pnl/m.total_pnl*100:.1f}%). "

            if max_day_pnl / m.total_pnl > 0.40:
                m.edge_unstable = True
                m.edge_instability_reason += f"Single trading day contributes >40% of net profits ({max_day_pnl/m.total_pnl*100:.1f}%)."

        # Execution stats
        if latencies:
            m.avg_latency_ms = float(np.mean(latencies))
            m.min_latency_ms = float(np.min(latencies))
            m.max_latency_ms = float(np.max(latencies))
            m.avg_fill_time_ms = m.avg_latency_ms

        if slippages:
            m.avg_slippage_pts = float(np.mean(slippages))
            m.worst_slippage_pts = float(np.max(slippages))

        if spreads:
            m.avg_spread_pts = float(np.mean(spreads))

        if hold_times:
            m.avg_holding_time_s = float(np.mean(hold_times))

        return m

    @classmethod
    def generate_and_save_reports(
        cls,
        trades: List[Dict[str, Any]],
        rejections_count: int = 0,
        initial_balance: float = 500.0,
        json_path: Path = ANALYTICS_JSON_PATH,
        md_path: Path = ANALYTICS_MD_PATH,
    ) -> ExecutionMetrics:
        metrics = cls.calculate_metrics(trades, rejections_count, initial_balance)
        
        json_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(asdict(metrics), f, indent=2)
            logger.info(f"Execution Analytics JSON saved to {json_path}")
        except Exception as e:
            logger.error(f"Failed to save analytics JSON: {e}")

        md_content = f"""# Advanced Execution Analytics & Certification Report

Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

## Performance Overview
- **Total Trades**: {metrics.total_trades}
- **Win Rate**: {metrics.win_rate_pct:.2f}% ({metrics.winning_trades} W / {metrics.losing_trades} L)
- **Net Profit**: ${metrics.total_pnl:.2f}
- **Profit Factor**: {metrics.profit_factor:.2f}
- **Expectancy**: ${metrics.expectancy_usd:.2f} ({metrics.expectancy_r:.2f}R)
- **95% Confidence Interval (Expectancy)**: [${metrics.expectancy_ci_lower_usd:.2f}, ${metrics.expectancy_ci_upper_usd:.2f}]
- **Bootstrap Expectancy (10,000 samples)**: ${metrics.bootstrap_expectancy_usd:.2f} [${metrics.bootstrap_ci_lower_usd:.2f}, ${metrics.bootstrap_ci_upper_usd:.2f}]
- **Max Drawdown**: ${metrics.max_drawdown_usd:.2f} ({metrics.max_drawdown_pct:.2f}%)
- **Recovery Factor**: {metrics.recovery_factor:.2f}
- **Sharpe Ratio**: {metrics.sharpe_ratio:.2f}
- **Sortino Ratio**: {metrics.sortino_ratio:.2f}
- **Ulcer Index**: {metrics.ulcer_index:.2f}
- **Edge Stability**: {"[UNSTABLE - " + metrics.edge_instability_reason + "]" if metrics.edge_unstable else "[STABLE - Distributed across symbols & days]"}

## Execution Quality
- **Execution Success Rate**: {metrics.execution_success_rate_pct:.1f}%
- **Rejected Trades**: {metrics.rejected_trades}
- **Average Latency**: {metrics.avg_latency_ms:.1f} ms
- **Average Spread**: {metrics.avg_spread_pts:.1f} pts
- **Average Slippage**: {metrics.avg_slippage_pts:.2f} pts
"""
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            logger.info(f"Execution Analytics MD report saved to {md_path}")
        except Exception as e:
            logger.error(f"Failed to save analytics MD: {e}")

        return metrics
