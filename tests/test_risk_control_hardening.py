"""
tests/test_risk_control_hardening.py — Regression Tests for Risk Controls & Sizing Hardening
"""

import math
import pytest
from app.position_sizer import BrokerSpec, PositionSizer
from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_context import NormalizedSignal
from app.multi_account.account_manager import MT5AccountManager
from app.config import _i, _f


# ── PositionSizer Hardening Tests ─────────────────────────────────────────────

def test_sizer_rejects_zero_and_negative_risk_pct():
    spec = BrokerSpec(symbol="XAUUSD", vol_min=0.01, vol_max=50.0, vol_step=0.01, tick_size=0.01, tick_value=1.0)

    # 0.0 risk
    r0 = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec, risk_pct=0.0, write_csv=False)
    assert r0.final_lot == 0.0
    assert r0.is_valid is False
    assert "positive and finite" in r0.rejection_reason

    # Negative risk
    r_neg = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec, risk_pct=-1.5, write_csv=False)
    assert r_neg.final_lot == 0.0
    assert r_neg.is_valid is False
    assert "positive and finite" in r_neg.rejection_reason


def test_sizer_rejects_non_finite_risk_pct():
    spec = BrokerSpec(symbol="XAUUSD", vol_min=0.01, vol_max=50.0, vol_step=0.01, tick_size=0.01, tick_value=1.0)

    # NaN
    r_nan = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec, risk_pct=float("nan"), write_csv=False)
    assert r_nan.final_lot == 0.0
    assert r_nan.is_valid is False

    # Infinity
    r_inf = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec, risk_pct=float("inf"), write_csv=False)
    assert r_inf.final_lot == 0.0
    assert r_inf.is_valid is False

    # -Infinity
    r_ninf = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec, risk_pct=float("-inf"), write_csv=False)
    assert r_ninf.final_lot == 0.0
    assert r_ninf.is_valid is False


def test_sizer_rejects_invalid_balances():
    spec = BrokerSpec(symbol="XAUUSD", vol_min=0.01, vol_max=50.0, vol_step=0.01, tick_size=0.01, tick_value=1.0)

    for bad_balance in [0.0, -100.0, float("nan"), float("inf"), float("-inf")]:
        r = PositionSizer.size(balance=bad_balance, entry=2000.0, stop_loss=1990.0, spec=spec, risk_pct=1.0, write_csv=False)
        assert r.final_lot == 0.0
        assert r.is_valid is False
        assert "positive and finite" in r.rejection_reason


def test_sizer_rejects_invalid_prices_and_distances():
    spec = BrokerSpec(symbol="XAUUSD", vol_min=0.01, vol_max=50.0, vol_step=0.01, tick_size=0.01, tick_value=1.0)

    # Entry <= 0 or non-finite
    assert PositionSizer.size(balance=1000.0, entry=0.0, stop_loss=1990.0, spec=spec, write_csv=False).final_lot == 0.0
    assert PositionSizer.size(balance=1000.0, entry=-2000.0, stop_loss=1990.0, spec=spec, write_csv=False).final_lot == 0.0
    assert PositionSizer.size(balance=1000.0, entry=float("nan"), stop_loss=1990.0, spec=spec, write_csv=False).final_lot == 0.0

    # Stop loss <= 0 or non-finite
    assert PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=0.0, spec=spec, write_csv=False).final_lot == 0.0
    assert PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=-10.0, spec=spec, write_csv=False).final_lot == 0.0
    assert PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=float("inf"), spec=spec, write_csv=False).final_lot == 0.0

    # Entry == Stop loss
    assert PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=2000.0, spec=spec, write_csv=False).final_lot == 0.0


def test_sizer_valid_positive_risk_functional():
    spec = BrokerSpec(symbol="XAUUSD", vol_min=0.01, vol_max=50.0, vol_step=0.01, tick_size=0.01, tick_value=1.0)
    r = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec, risk_pct=1.0, write_csv=False)
    assert r.final_lot > 0.0
    assert r.is_valid is True
    assert r.risk_amount == 10.0  # 1% of 1000


def test_sizer_never_rounds_invalid_risk_up_to_vol_min():
    spec = BrokerSpec(symbol="XAUUSD", vol_min=0.01, vol_max=50.0, vol_step=0.01, tick_size=0.01, tick_value=1.0)
    for bad_risk in [0.0, -0.01, -5.0, float("nan")]:
        r = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec, risk_pct=bad_risk, write_csv=False)
        assert r.final_lot == 0.0
        assert r.final_lot != spec.vol_min


# ── AccountManager Balance Hardening Tests ────────────────────────────────────

def test_account_manager_rejects_non_positive_balance():
    registry = AccountRegistry()
    cfg = AccountConfig(account_id="acc_test", login=1001, magic_number=20250701, dry_run=True)
    manager = MT5AccountManager(registry=registry)
    ctx = manager.add_account(cfg)

    sig = NormalizedSignal(
        signal_id="sig_test_1",
        timestamp=None,
        symbol="XAUUSD",
        direction="BUY",
        entry_reference=2000.0,
        stop_loss=1990.0,
        take_profit_1=2010.0,
        quality_score=90.0,
    )

    # 1. Zero balance -> must return (0.0, 0.0) without fallback to 1000.0
    ctx.update_snapshot(balance=0.0, equity=0.0)
    vol, exp_loss = manager.calculate_position_size("acc_test", sig)
    assert vol == 0.0
    assert exp_loss == 0.0

    # 2. Negative balance -> must return (0.0, 0.0)
    ctx.risk_state.current_balance = -50.0
    vol_neg, exp_loss_neg = manager.calculate_position_size("acc_test", sig)
    assert vol_neg == 0.0
    assert exp_loss_neg == 0.0

    # 3. Non-finite balance -> must return (0.0, 0.0)
    ctx.risk_state.current_balance = float("nan")
    vol_nan, exp_loss_nan = manager.calculate_position_size("acc_test", sig)
    assert vol_nan == 0.0
    assert exp_loss_nan == 0.0


# ── Config Parser & Conservative Defaults Tests ───────────────────────────────

def test_config_parsers_missing_falls_back_to_defaults(monkeypatch):
    monkeypatch.delenv("MAX_OPEN_TRADES", raising=False)
    monkeypatch.delenv("MAX_RISK_EXPOSURE_PCT", raising=False)
    monkeypatch.delenv("MAX_SAME_CORR_GROUP_TRADES", raising=False)

    assert _i("MAX_OPEN_TRADES", 3) == 3
    assert _f("MAX_RISK_EXPOSURE_PCT", 3.0) == 3.0
    assert _i("MAX_SAME_CORR_GROUP_TRADES", 2) == 2


def test_config_parsers_malformed_falls_back_to_defaults(monkeypatch):
    for bad_int in ["abc", "-5", "NaN", "invalid_number"]:
        monkeypatch.setenv("MAX_OPEN_TRADES", bad_int)
        assert _i("MAX_OPEN_TRADES", 3) == 3

        monkeypatch.setenv("MAX_SAME_CORR_GROUP_TRADES", bad_int)
        assert _i("MAX_SAME_CORR_GROUP_TRADES", 2) == 2

    for bad_float in ["abc", "-2.5", "nan", "not_a_float"]:
        monkeypatch.setenv("MAX_RISK_EXPOSURE_PCT", bad_float)
        assert _f("MAX_RISK_EXPOSURE_PCT", 3.0) == 3.0


def test_config_parsers_explicit_unlimited_overrides(monkeypatch):
    # MAX_OPEN_TRADES
    monkeypatch.setenv("MAX_OPEN_TRADES", "0")
    assert _i("MAX_OPEN_TRADES", 3) == 0

    monkeypatch.setenv("MAX_OPEN_TRADES", "unlimited")
    assert _i("MAX_OPEN_TRADES", 3) == 0

    # MAX_RISK_EXPOSURE_PCT
    monkeypatch.setenv("MAX_RISK_EXPOSURE_PCT", "100.0")
    assert _f("MAX_RISK_EXPOSURE_PCT", 3.0) == 100.0

    monkeypatch.setenv("MAX_RISK_EXPOSURE_PCT", "unlimited")
    assert _f("MAX_RISK_EXPOSURE_PCT", 3.0) == 100.0

    # MAX_SAME_CORR_GROUP_TRADES
    monkeypatch.setenv("MAX_SAME_CORR_GROUP_TRADES", "0")
    assert _i("MAX_SAME_CORR_GROUP_TRADES", 2) == 0


def test_config_parsers_valid_numeric_overrides(monkeypatch):
    monkeypatch.setenv("MAX_OPEN_TRADES", "5")
    assert _i("MAX_OPEN_TRADES", 3) == 5

    monkeypatch.setenv("MAX_RISK_EXPOSURE_PCT", "4.5")
    assert _f("MAX_RISK_EXPOSURE_PCT", 3.0) == 4.5

    monkeypatch.setenv("MAX_SAME_CORR_GROUP_TRADES", "1")
    assert _i("MAX_SAME_CORR_GROUP_TRADES", 2) == 1


def test_broker_spec_non_finite_and_nan_rejected():
    # 1. PositionSizer rejects NaN and Inf broker spec fields
    for bad_val in [float("nan"), float("inf"), float("-inf")]:
        spec_bad_tick = BrokerSpec(symbol="XAUUSD", vol_min=0.01, vol_max=50.0, vol_step=0.01, tick_size=bad_val, tick_value=1.0)
        res = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec_bad_tick, risk_pct=1.0, write_csv=False)
        assert res.final_lot == 0.0
        assert not res.is_valid

        spec_bad_vol = BrokerSpec(symbol="XAUUSD", vol_min=bad_val, vol_max=50.0, vol_step=0.01, tick_size=0.01, tick_value=1.0)
        res2 = PositionSizer.size(balance=1000.0, entry=2000.0, stop_loss=1990.0, spec=spec_bad_vol, risk_pct=1.0, write_csv=False)
        assert res2.final_lot == 0.0
        assert not res2.is_valid

    # 2. AccountManager calculate_position_size rejects NaN and Inf in spec_dict
    registry = AccountRegistry()
    cfg = AccountConfig(account_id="acc_spec_test", login=1002, magic_number=20250702, dry_run=True)
    manager = MT5AccountManager(registry=registry)
    ctx = manager.add_account(cfg)
    ctx.update_snapshot(balance=1000.0, equity=1000.0)
    sig = NormalizedSignal(
        signal_id="sig_spec_1", timestamp=None, symbol="XAUUSD", direction="BUY",
        entry_reference=2000.0, stop_loss=1990.0, take_profit_1=2010.0, quality_score=90.0
    )

    base_spec = {
        "digits": 2, "point": 0.01, "spread": 15, "contract_size": 100.0,
        "vol_min": 0.01, "vol_max": 50.0, "vol_step": 0.01,
        "tick_size": 0.01, "tick_value": 0.01,
    }

    for bad_field in ["point", "contract_size", "tick_size", "tick_value", "vol_min", "vol_max", "vol_step", "digits"]:
        for bad_val in [float("nan"), float("inf"), float("-inf")]:
            corrupted_spec = dict(base_spec)
            corrupted_spec[bad_field] = bad_val
            ctx.session.get_symbol_spec = lambda sym, cs=corrupted_spec: cs
            vol, risk_usd = manager.calculate_position_size("acc_spec_test", sig)
            assert vol == 0.0, f"Field {bad_field} with {bad_val} should yield 0 volume"
            assert risk_usd == 0.0
