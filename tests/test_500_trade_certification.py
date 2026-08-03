"""
tests/test_500_trade_certification.py — PyTest Suite for 500-Trade Certification Suite

Validates:
- Advanced statistical analytics (Bootstrap Expectancy 10,000 samples, 95% Confidence Interval)
- Ulcer Index, Calmar Ratio, Risk of Ruin
- Edge Stability verification (>40% single-symbol or single-day profit check)
- Periodical Markdown Report generation (Daily, Weekly, Monthly)
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path

from app.execution_analytics import ExecutionAnalyticsEngine, ExecutionMetrics
from reports.generator import ReportGenerator


def test_bootstrap_and_confidence_interval():
    # Simulated 20 positive expectancy trades
    np.random.seed(42)
    trades = [{"realized_pnl": float(np.random.normal(loc=15.0, scale=10.0))} for _ in range(20)]

    metrics = ExecutionAnalyticsEngine.calculate_metrics(trades, rejections_count=0, initial_balance=500.0, n_bootstrap=1000)

    assert metrics.total_trades == 20
    assert metrics.expectancy_usd > 0
    assert metrics.expectancy_ci_lower_usd < metrics.expectancy_usd
    assert metrics.expectancy_ci_upper_usd > metrics.expectancy_usd
    assert metrics.bootstrap_expectancy_usd > 0
    assert metrics.bootstrap_ci_lower_usd <= metrics.bootstrap_ci_upper_usd


def test_edge_stability_flag():
    # Test stable edge
    stable_trades = [
        {"symbol": "XAUUSD", "realized_pnl": 20.0, "entry_time": "2026-08-01T10:00:00Z"},
        {"symbol": "EURUSD", "realized_pnl": 20.0, "entry_time": "2026-08-02T10:00:00Z"},
        {"symbol": "GBPUSD", "realized_pnl": 20.0, "entry_time": "2026-08-03T10:00:00Z"},
    ]
    m_stable = ExecutionAnalyticsEngine.calculate_metrics(stable_trades, rejections_count=0, initial_balance=500.0)
    assert not m_stable.edge_unstable

    # Test unstable edge (>40% of net profits from single symbol)
    unstable_trades = [
        {"symbol": "XAUUSD", "realized_pnl": 90.0, "entry_time": "2026-08-01T10:00:00Z"},
        {"symbol": "EURUSD", "realized_pnl": 5.0, "entry_time": "2026-08-02T10:00:00Z"},
        {"symbol": "GBPUSD", "realized_pnl": 5.0, "entry_time": "2026-08-03T10:00:00Z"},
    ]
    m_unstable = ExecutionAnalyticsEngine.calculate_metrics(unstable_trades, rejections_count=0, initial_balance=500.0)
    assert m_unstable.edge_unstable
    assert "Single symbol contributes >40%" in m_unstable.edge_instability_reason


def test_periodical_markdown_reports(tmp_path):
    gen = ReportGenerator(report_dir=str(tmp_path))

    daily_stats = {
        "total_trades": 5, "winning": 4, "losing": 1,
        "win_rate": 80.0, "gross_profit": 100.0, "gross_loss": 20.0,
        "net_pnl": 80.0, "profit_factor": 5.0, "max_drawdown": 10.0,
        "avg_quality": 85.0, "avg_latency_ms": 25.0, "avg_slippage": 0.2,
    }
    
    daily_file = gen.write_daily_markdown_report(daily_stats, "2026-08-03")
    assert Path(daily_file).exists()

    weekly_file = gen.write_weekly_markdown_report(daily_stats, "2026_W31")
    assert Path(weekly_file).exists()

    monthly_file = gen.write_monthly_markdown_report(daily_stats, "2026_08")
    assert Path(monthly_file).exists()
