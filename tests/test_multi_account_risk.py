"""
tests/test_multi_account_risk.py — Multi-Account Risk Management & Position Sizing Tests
"""

import pytest
from datetime import datetime, timezone

from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_context import NormalizedSignal, AccountStatus
from app.multi_account.account_manager import MT5AccountManager


def test_independent_position_sizing_across_balances():
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    # Account A: $1,000 balance, 1% risk
    cfg_a = AccountConfig(account_id="acc_a", login=1001, password="p", magic_number=1001, risk_per_trade_pct=1.0)
    ctx_a = manager.add_account(cfg_a)
    ctx_a.update_snapshot(balance=1000.0, equity=1000.0)

    # Account B: $10,000 balance, 1% risk
    cfg_b = AccountConfig(account_id="acc_b", login=1002, password="p", magic_number=1002, risk_per_trade_pct=1.0)
    ctx_b = manager.add_account(cfg_b)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Account C: $50,000 balance, 0.5% risk
    cfg_c = AccountConfig(account_id="acc_c", login=1003, password="p", magic_number=1003, risk_per_trade_pct=0.5)
    ctx_c = manager.add_account(cfg_c)
    ctx_c.update_snapshot(balance=50000.0, equity=50000.0)

    signal = NormalizedSignal(
        signal_id="sig_test_risk",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1990.0,   # 10 point stop ($10 per oz = $1000 per standard lot)
        take_profit_1=2020.0,
    )

    vol_a, risk_a = manager.calculate_position_size("acc_a", signal)
    vol_b, risk_b = manager.calculate_position_size("acc_b", signal)
    vol_c, risk_c = manager.calculate_position_size("acc_c", signal)

    # Verify all volumes are calculated independently
    assert vol_a > 0
    assert vol_b > vol_a
    assert vol_c > vol_b

    # Verify risk dollar amounts approximate configured percentage:
    # A: 1% of $1,000 = $10.00
    # B: 1% of $10,000 = $100.00
    # C: 0.5% of $50,000 = $250.00
    assert risk_a <= 10.0 + 0.05
    assert risk_b <= 100.0 + 0.5
    assert risk_c <= 250.0 + 1.0


def test_account_symbol_restrictions():
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    # Account A: Only XAUUSD permitted
    cfg_a = AccountConfig(
        account_id="acc_gold_only", login=1001, password="p", magic_number=1001,
        symbols=["XAUUSD"]
    )
    ctx_a = manager.add_account(cfg_a)
    ctx_a.status = AccountStatus.CONNECTED
    ctx_a.initialize_risk(10000.0)

    # Account B: Only EURUSD permitted
    cfg_b = AccountConfig(
        account_id="acc_fx_only", login=1002, password="p", magic_number=1002,
        symbols=["EURUSD"]
    )
    ctx_b = manager.add_account(cfg_b)
    ctx_b.status = AccountStatus.CONNECTED
    ctx_b.initialize_risk(10000.0)

    # Test XAUUSD signal
    ok_a_gold, _ = ctx_a.is_trading_allowed("XAUUSD")
    ok_b_gold, reason_b = ctx_b.is_trading_allowed("XAUUSD")

    assert ok_a_gold is True
    assert ok_b_gold is False
    assert "not in permitted list" in reason_b

    # Test EURUSD signal
    ok_a_eur, reason_a = ctx_a.is_trading_allowed("EURUSD")
    ok_b_eur, _ = ctx_b.is_trading_allowed("EURUSD")

    assert ok_a_eur is False
    assert "not in permitted list" in reason_a
    assert ok_b_eur is True


def test_account_max_open_trades_limit():
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg = AccountConfig(
        account_id="acc_max_trades", login=1001, password="p", magic_number=1001,
        max_open_trades=2
    )
    ctx = manager.add_account(cfg)
    ctx.status = AccountStatus.CONNECTED
    ctx.initialize_risk(10000.0)

    # 0 trades: allowed
    ok, _ = ctx.is_trading_allowed("XAUUSD")
    assert ok is True

    # 1 trade: allowed
    ctx.exec_state.open_positions[1001] = {"ticket": 1001, "symbol": "XAUUSD"}
    ok, _ = ctx.is_trading_allowed("XAUUSD")
    assert ok is True

    # 2 trades: at limit -> rejected
    ctx.exec_state.open_positions[1002] = {"ticket": 1002, "symbol": "XAUUSD"}
    ok, reason = ctx.is_trading_allowed("XAUUSD")
    assert ok is False
    assert "Max open trades" in reason
