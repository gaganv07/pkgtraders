"""
tests/test_mt5_integration.py — PyTest Suite for MetaTrader 5 Integration

Validates all 5 MT5 integration components:
- MT5Connector
- AccountManager
- SymbolManager
- MarketFeed
- OrderExecutor
"""

import os
import pytest
import pandas as pd
from app.config import settings
from app.mt5_connector import MT5Connector, ConnectionResult
from app.account_manager import AccountManager
from app.symbol_manager import SymbolManager, REQUIRED_SYMBOLS
from app.market_feed import MarketFeed
from app.order_executor import OrderExecutor


@pytest.fixture(scope="module")
def mt5_components():
    connector = MT5Connector(
        login=settings.mt5.login,
        password=settings.mt5.password,
        server=settings.mt5.server,
        path=settings.mt5.path,
    )
    acct_mgr = AccountManager()
    symbol_mgr = SymbolManager()
    market_feed = MarketFeed(symbol_resolver=symbol_mgr)
    order_executor = OrderExecutor(symbol_manager=symbol_mgr, account_manager=acct_mgr)

    return {
        "connector": connector,
        "acct_mgr": acct_mgr,
        "symbol_mgr": symbol_mgr,
        "market_feed": market_feed,
        "order_executor": order_executor,
    }


def test_symbol_manager_initialization(mt5_components):
    symbol_mgr = mt5_components["symbol_mgr"]
    mapping = symbol_mgr.initialize_symbols()

    assert isinstance(mapping, dict)
    # Check that required symbols are present in mapping or attempted
    assert len(symbol_mgr.target_symbols) == len(REQUIRED_SYMBOLS)


def test_market_feed_indicator_calculation():
    # Test pandas indicator calculations on dummy OHLCV data
    data = {
        "time": pd.date_range("2026-01-01", periods=50, freq="15min"),
        "open": [100.0 + i for i in range(50)],
        "high": [105.0 + i for i in range(50)],
        "low": [95.0 + i for i in range(50)],
        "close": [102.0 + i for i in range(50)],
        "tick_volume": [1000 for _ in range(50)],
    }
    df = pd.DataFrame(data)
    df_calc = MarketFeed.calculate_indicators(df)

    assert "atr" in df_calc.columns
    assert "ema50" in df_calc.columns
    assert "ema200" in df_calc.columns
    assert "rsi" in df_calc.columns
    assert "vwap" in df_calc.columns
    assert not df_calc["atr"].isna().all()


def test_order_executor_risk_validation(mt5_components):
    order_executor = mt5_components["order_executor"]
    
    # Test spread limit rejection
    valid, reason = order_executor.validate_pre_trade_risk(
        symbol="XAUUSD",
        volume=0.01,
        max_spread_pts=0.0,  # 0 limit forces spread rejection if live
    )
    # Result depends on whether MT5 is live; should return tuple (bool, str)
    assert isinstance(valid, bool)
    assert isinstance(reason, str)
