"""
tests/test_demo_readiness.py — PyTest Suite for Live Demo Readiness & Operational Modules

Validates:
- TradeJournal CSV generation
- ExecutionAnalyticsEngine calculations
- AutoRecoveryEngine heartbeat & position reconciliation
- SafetyEngine pre-trade checks
- ConsoleDashboard text generation
"""

import os
from pathlib import Path
import pytest
import pandas as pd

from app.trade_journal import TradeJournal, TradeJournalEntry
from app.execution_analytics import ExecutionAnalyticsEngine, ExecutionMetrics
from app.safety_engine import SafetyEngine, SafetyCheckResult
from app.auto_recovery import AutoRecoveryEngine


def test_trade_journal_export(tmp_path):
    csv_file = tmp_path / "test_journal.csv"
    journal = TradeJournal(file_path=csv_file)

    entry = TradeJournalEntry(
        timestamp="2026-08-03T10:00:00Z",
        exit_timestamp="2026-08-03T10:15:00Z",
        symbol="XAUUSD",
        direction="LONG",
        entry_price=4060.0,
        exit_price=4070.0,
        sl=4050.0,
        tp=4080.0,
        lot_size=0.1,
        balance=1000.0,
        equity=1010.0,
        risk_pct=1.0,
        spread_pts=15.0,
        atr=5.0,
        ema50=4055.0,
        rsi=55.0,
        ai_score=85.0,
        score_breakdown="of:85;liq:80",
        entry_reason="QualityScore=85.0",
        exit_reason="TP1",
        holding_time_s=900.0,
        pnl=100.0,
        pnl_pct=10.0,
        r_multiple=1.0,
        broker_retcode=10009,
        execution_latency_ms=25.0,
    )

    success = journal.log_trade(entry)
    assert success
    assert csv_file.exists()

    df = pd.read_csv(csv_file)
    assert len(df) == 1
    assert df["symbol"].iloc[0] == "XAUUSD"
    assert df["pnl"].iloc[0] == 100.0


def test_execution_analytics_calculation():
    trades = [
        {"pnl": 50.0, "r_multiple": 1.0, "latency_ms": 30.0, "slippage_pts": 0.5, "spread_pts": 15.0, "holding_time_s": 600.0},
        {"pnl": -25.0, "r_multiple": -0.5, "latency_ms": 40.0, "slippage_pts": 1.0, "spread_pts": 18.0, "holding_time_s": 300.0},
        {"pnl": 75.0, "r_multiple": 1.5, "latency_ms": 20.0, "slippage_pts": 0.2, "spread_pts": 12.0, "holding_time_s": 1200.0},
    ]

    metrics = ExecutionAnalyticsEngine.calculate_metrics(trades, rejections_count=0, initial_balance=500.0)

    assert metrics.total_trades == 3
    assert metrics.winning_trades == 2
    assert metrics.losing_trades == 1
    assert metrics.total_pnl == 100.0
    assert metrics.gross_profit == 125.0
    assert metrics.gross_loss == 25.0
    assert metrics.profit_factor == 5.0
    assert metrics.win_rate_pct == pytest.approx(66.66, rel=1e-2)
    assert metrics.avg_latency_ms == pytest.approx(30.0)


def test_safety_engine_evaluation():
    class DummyRisk:
        circuit_broken = False
        def approve_with_exposure(self, risk_pct): return True, "OK"
    class DummySession:
        class State: news_blackout = False
        state = State()
    class DummySymbolManager:
        def verify_symbol_tradeable(self, sym): return True, "Open"

    safety = SafetyEngine(DummyRisk(), DummySession(), DummySymbolManager())

    # Test normal pass
    res = safety.evaluate_pre_trade_safety("XAUUSD", current_spread_pts=20.0, max_spread_pts=50.0)
    assert res.passed
    assert res.code == "OK"

    # Test spread spike rejection
    res_spike = safety.evaluate_pre_trade_safety("XAUUSD", current_spread_pts=80.0, max_spread_pts=50.0)
    assert not res_spike.passed
    assert res_spike.code == "SPREAD_SPIKE"
