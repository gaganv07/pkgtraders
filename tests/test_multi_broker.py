"""
tests/test_multi_broker.py — PyTest Suite for Universal MT5 Broker Infrastructure
"""

from __future__ import annotations

import pytest
from app.broker_adapter import BrokerAdapter
from app.symbol_manager import SymbolManager
from app.history_sync import HistorySynchronizationManager
from app.cache_repair import CacheRepairEngine
from app.data_validator import DataValidator
from app.order_execution_validator import PreTradeExecutionValidator
from app.health_api import InfrastructureHealthAPI


def test_broker_adapter_profile():
    adapter = BrokerAdapter()
    profile = adapter.profile
    assert profile is not None
    assert isinstance(profile.company, str)
    assert isinstance(profile.balance, float)


def test_symbol_manager_discovery():
    mgr = SymbolManager()
    symbols = mgr.initialize_symbols()
    assert isinstance(symbols, dict)
    for canonical, broker_sym in symbols.items():
        assert len(canonical) > 0
        assert len(broker_sym) > 0


def test_cache_repair_engine():
    engine = CacheRepairEngine()
    is_healthy, corrupted = engine.audit_cache_integrity()
    assert isinstance(is_healthy, bool)
    assert isinstance(corrupted, list)


def test_data_validator():
    import pandas as pd
    validator = DataValidator()
    df = pd.DataFrame({
        "open": [100.0 + i for i in range(12)],
        "high": [102.0 + i for i in range(12)],
        "low": [99.0 + i for i in range(12)],
        "close": [101.0 + i for i in range(12)],
    })
    report = validator.validate_dataframe(df, "EURUSD", "M15")
    assert report.is_valid is True


def test_health_api():
    api = InfrastructureHealthAPI()
    health = api.get_overall_health()
    assert "status" in health
    assert "timestamp" in health
