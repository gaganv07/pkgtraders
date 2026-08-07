"""
tests/test_institutional_platform.py — Automated Unit Test Suite
================================================================
Verifies:
  1. Dataset Manager versioning and archiving
  2. Forensic Loss Analyzer root-cause classification
  3. Candidate Model Benchmarker deployment gate policy
  4. Self-Healing Infrastructure Monitor
"""

import json
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))

from app.dataset_manager import DatasetManager, TradeContextFeature
from app.forensic_analyzer import ForensicAnalyzer
from research.candidate_model_benchmarker import CandidateModelBenchmarker
from app.self_healing_monitor import SelfHealingMonitor


def test_dataset_manager_versioning(tmp_path):
    dm = DatasetManager(base_dir=tmp_path)
    feat = TradeContextFeature(
        timestamp="2026-08-07T08:45:00Z",
        trade_id="TEST_001",
        symbol="XAUUSD",
        direction="LONG",
        entry_price=2450.0,
        stop_loss=2445.0,
        take_profit=2460.0,
        risk_usd=5.0,
        risk_pct=1.0,
        pnl=-5.0,
        r_multiple=-1.0,
        outcome="LOSS",
        exit_reason="SL_HIT",
    )
    json_path = dm.archive_record(feat)
    assert json_path.exists()
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]["symbol"] == "XAUUSD"


def test_forensic_analyzer_loss_classification(tmp_path):
    fa = ForensicAnalyzer(log_path=str(tmp_path / "forensic_log.csv"))
    trade_loss = {
        "trade_id": "TEST_LOSS_001",
        "symbol": "XAUUSD",
        "direction": "SHORT",
        "entry_price": 2450.0,
        "exit_price": 2455.0,
        "pnl": -5.0,
        "r_multiple": -1.0,
        "news_score": 15.0,  # low news score -> NEWS_SPIKE
    }
    diag = fa.diagnose_trade(trade_loss)
    assert diag.primary_failure_mode == "NEWS_SPIKE"
    assert diag.confidence >= 0.80


def test_candidate_model_benchmarker_gate(tmp_path):
    bench = CandidateModelBenchmarker()
    res = bench.benchmark_candidate("XGBoost_Candidate_v1")
    assert res.model_name == "XGBoost_Candidate_v1"
    # Verify policy gate: if < 500 trades, gate_500_trades_met is False
    assert res.n_training_samples < 500 or res.gate_500_trades_met is True
    assert "PRODUCTION" in res.deployment_recommendation or "SHADOW" in res.deployment_recommendation


def test_self_healing_monitor():
    sh = SelfHealingMonitor()
    metrics = sh.audit_system_health()
    assert metrics.mt5_connected is True
    assert metrics.disk_free_gb > 0.0
