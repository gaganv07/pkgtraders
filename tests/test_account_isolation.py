"""
tests/test_account_isolation.py — Account State Isolation & Decoupling Tests
"""

import pytest
from app.multi_account.account_registry import AccountConfig
from app.multi_account.account_context import (
    AccountContext,
    AccountStatus,
    TradeExecutionReport,
)
from app.multi_account.mt5_session import MT5DirectSession


def test_independent_balance_and_equity():
    cfg_a = AccountConfig(account_id="acc_a", login=1001, password="p1", magic_number=1001)
    cfg_b = AccountConfig(account_id="acc_b", login=1002, password="p2", magic_number=1002)

    ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    ctx_b = AccountContext(config=cfg_b, mt5_session=MT5DirectSession(cfg_b))

    ctx_a.update_snapshot(balance=5000.0, equity=5200.0, margin=200.0, free_margin=5000.0)
    ctx_b.update_snapshot(balance=25000.0, equity=24800.0, margin=1500.0, free_margin=23300.0)

    # Assert completely isolated state
    assert ctx_a.risk_state.current_balance == 5000.0
    assert ctx_a.risk_state.current_equity == 5200.0
    assert ctx_b.risk_state.current_balance == 25000.0
    assert ctx_b.risk_state.current_equity == 24800.0

    assert ctx_a.risk_state.current_balance != ctx_b.risk_state.current_balance
    assert ctx_a.risk_state.current_equity != ctx_b.risk_state.current_equity


def test_isolated_positions():
    cfg_a = AccountConfig(account_id="acc_a", login=1001, password="p1", magic_number=1001)
    cfg_b = AccountConfig(account_id="acc_b", login=1002, password="p2", magic_number=1002)

    ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    ctx_b = AccountContext(config=cfg_b, mt5_session=MT5DirectSession(cfg_b))

    ctx_a.initialize_risk(10000.0)
    ctx_b.initialize_risk(10000.0)

    # Fill on Account A
    rep_a = TradeExecutionReport(
        account_id="acc_a",
        login=1001,
        signal_id="sig_1",
        symbol="XAUUSD",
        direction="LONG",
        status="SUCCESS",
        executed_volume=0.5,
        executed_price=2000.0,
        ticket=111111,
        magic_number=1001,
    )
    ctx_a.record_fill(rep_a)

    # Fill on Account B
    rep_b = TradeExecutionReport(
        account_id="acc_b",
        login=1002,
        signal_id="sig_1",
        symbol="EURUSD",
        direction="SHORT",
        status="SUCCESS",
        executed_volume=1.0,
        executed_price=1.0850,
        ticket=222222,
        magic_number=1002,
    )
    ctx_b.record_fill(rep_b)

    # Verify positions on A do not appear on B
    assert 111111 in ctx_a.exec_state.open_positions
    assert 111111 not in ctx_b.exec_state.open_positions

    assert 222222 in ctx_b.exec_state.open_positions
    assert 222222 not in ctx_a.exec_state.open_positions

    assert ctx_a.exec_state.open_positions[111111]["symbol"] == "XAUUSD"
    assert ctx_b.exec_state.open_positions[222222]["symbol"] == "EURUSD"


def test_isolated_risk_drawdown():
    cfg_a = AccountConfig(
        account_id="acc_a", login=1001, password="p1", magic_number=1001,
        daily_drawdown_limit_pct=3.0
    )
    cfg_b = AccountConfig(
        account_id="acc_b", login=1002, password="p2", magic_number=1002,
        daily_drawdown_limit_pct=3.0
    )

    ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    ctx_b = AccountContext(config=cfg_b, mt5_session=MT5DirectSession(cfg_b))

    ctx_a.initialize_risk(10000.0)
    ctx_b.initialize_risk(10000.0)

    ctx_a.status = AccountStatus.CONNECTED
    ctx_b.status = AccountStatus.CONNECTED

    # Account A suffers 4% drawdown (exceeds 3% limit)
    ctx_a.update_snapshot(balance=10000.0, equity=9600.0)
    # Account B remains healthy
    ctx_b.update_snapshot(balance=10000.0, equity=10100.0)

    assert ctx_a.status == AccountStatus.RISK_LOCKED
    assert ctx_b.status == AccountStatus.CONNECTED

    allowed_a, _ = ctx_a.is_trading_allowed("XAUUSD")
    allowed_b, _ = ctx_b.is_trading_allowed("XAUUSD")

    assert allowed_a is False
    assert allowed_b is True


def test_credential_isolation():
    cfg_a = AccountConfig(account_id="acc_a", login=1001, password="SecretPassA", magic_number=1001)
    cfg_b = AccountConfig(account_id="acc_b", login=1002, password="SecretPassB", magic_number=1002)

    assert cfg_a.resolve_password() == "SecretPassA"
    assert cfg_b.resolve_password() == "SecretPassB"
    assert cfg_a.resolve_password() != cfg_b.resolve_password()


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Explicit 10-Point Runtime Account Isolation Test Suite
# ══════════════════════════════════════════════════════════════════════════════

def test_account_a_cannot_execute_using_session_b():
    """1. Account A cannot execute using Account B's MT5 session."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    sess_b = MT5DirectSession(cfg_b)
    sess_b.connect()

    # Mismatched pairing: Context A attached to Session B
    ctx_mismatched = AccountContext(config=cfg_a, mt5_session=sess_b)
    ctx_mismatched.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_mismatched.status = AccountStatus.CONNECTED

    allowed, reason = ctx_mismatched.is_trading_allowed("XAUUSD")
    assert allowed is False
    assert "MT5 account mismatch" in reason
    assert "login 10001" in reason
    assert "login 10002" in reason


def test_account_b_cannot_execute_using_session_a():
    """2. Account B cannot execute using Account A's MT5 session."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    sess_a = MT5DirectSession(cfg_a)
    sess_a.connect()

    # Mismatched pairing: Context B attached to Session A
    ctx_mismatched = AccountContext(config=cfg_b, mt5_session=sess_a)
    ctx_mismatched.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_mismatched.status = AccountStatus.CONNECTED

    allowed, reason = ctx_mismatched.is_trading_allowed("XAUUSD")
    assert allowed is False
    assert "MT5 account mismatch" in reason
    assert "login 10002" in reason
    assert "login 10001" in reason


def test_account_a_risk_lock_does_not_affect_b():
    """3. Account A's risk lock does not affect Account B."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, daily_drawdown_limit_pct=3.0, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, daily_drawdown_limit_pct=3.0, dry_run=True)

    ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    ctx_b = AccountContext(config=cfg_b, mt5_session=MT5DirectSession(cfg_b))
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_a.status = AccountStatus.CONNECTED
    ctx_b.status = AccountStatus.CONNECTED

    # Lock Account A due to drawdown
    ctx_a.update_snapshot(balance=10000.0, equity=9600.0)
    assert ctx_a.status == AccountStatus.RISK_LOCKED

    allowed_a, reason_a = ctx_a.is_trading_allowed("XAUUSD")
    allowed_b, reason_b = ctx_b.is_trading_allowed("XAUUSD")

    assert allowed_a is False
    assert "risk/drawdown limits" in reason_a
    assert allowed_b is True
    assert reason_b == "ALLOWED"


@pytest.mark.asyncio
async def test_account_a_disconnect_does_not_stop_b():
    """4. Account A's disconnect does not stop Account B."""
    from app.multi_account.account_manager import MT5AccountManager
    from app.multi_account.account_registry import AccountRegistry
    from app.multi_account.account_context import NormalizedSignal
    from datetime import datetime, timezone

    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Disconnect Account A
    ctx_a.status = AccountStatus.DISCONNECTED

    sig = NormalizedSignal(
        signal_id="sig_iso_p2_disc",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )
    reports = await mgr.distribute_signal(sig)
    await mgr.disconnect_all()

    assert reports["acc_A"].is_success is False
    assert "DISCONNECTED" in reports["acc_A"].rejection_reason
    assert reports["acc_B"].is_success is True


@pytest.mark.asyncio
async def test_account_a_worker_crash_does_not_stop_b():
    """5. Account A's worker crash does not stop Account B."""
    from app.multi_account.account_manager import MT5AccountManager
    from app.multi_account.account_registry import AccountRegistry
    from app.multi_account.account_context import NormalizedSignal
    from datetime import datetime, timezone

    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Simulate worker task cancellation/crash on Account A
    worker_a = mgr._workers.get("acc_A")
    if worker_a and worker_a._task:
        worker_a._task.cancel()

    sig = NormalizedSignal(
        signal_id="sig_iso_p2_crash",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )
    reports = await mgr.distribute_signal(sig)
    await mgr.disconnect_all()

    assert reports["acc_B"].is_success is True


@pytest.mark.asyncio
async def test_account_a_broker_rejection_does_not_stop_b():
    """6. Account A's broker rejection does not stop Account B."""
    from app.multi_account.account_manager import MT5AccountManager
    from app.multi_account.account_registry import AccountRegistry
    from app.multi_account.account_context import NormalizedSignal
    from app.multi_account.mt5_session import FillResult
    from datetime import datetime, timezone

    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Inject broker rejection into Account A's session buy
    ctx_a.session.buy = lambda *args, **kwargs: FillResult(success=False, error="Trade Disabled [10017]")

    sig = NormalizedSignal(
        signal_id="sig_iso_p2_rej",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )
    reports = await mgr.distribute_signal(sig)
    await mgr.disconnect_all()

    assert reports["acc_A"].is_success is False
    assert "Trade Disabled" in reports["acc_A"].rejection_reason
    assert reports["acc_B"].is_success is True


def test_duplicate_signals_isolated_per_account():
    """7. Duplicate signals are isolated correctly per account."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    ctx_b = AccountContext(config=cfg_b, mt5_session=MT5DirectSession(cfg_b))
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_a.status = AccountStatus.CONNECTED
    ctx_b.status = AccountStatus.CONNECTED

    # Mark signal as processed only on Account A
    ctx_a.exec_state.processed_signals.add("sig_shared_001")

    allowed_a, reason_a = ctx_a.is_trading_allowed("XAUUSD", signal_id="sig_shared_001")
    allowed_b, reason_b = ctx_b.is_trading_allowed("XAUUSD", signal_id="sig_shared_001")

    # Account A must reject duplicate; Account B must allow it since B hasn't processed it
    assert allowed_a is False
    assert "Duplicate signal" in reason_a
    assert allowed_b is True
    assert reason_b == "ALLOWED"


def test_restarting_account_a_does_not_duplicate_account_b_positions():
    """8. Restarting Account A does not duplicate Account B positions."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    ctx_b = AccountContext(config=cfg_b, mt5_session=MT5DirectSession(cfg_b))

    ctx_b.exec_state.open_positions[555111] = {"ticket": 555111, "symbol": "XAUUSD", "magic": 20250702}

    # Simulate restart of Account A
    restarted_ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    assert len(restarted_ctx_a.exec_state.open_positions) == 0
    assert len(ctx_b.exec_state.open_positions) == 1
    assert 555111 not in restarted_ctx_a.exec_state.open_positions


def test_account_a_positions_cannot_appear_in_account_b():
    """9. Account A's positions cannot appear in Account B."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    ctx_b = AccountContext(config=cfg_b, mt5_session=MT5DirectSession(cfg_b))

    rep_a = TradeExecutionReport(
        account_id="acc_A", login=10001, signal_id="sig_x", symbol="XAUUSD",
        direction="LONG", status="SUCCESS", executed_volume=0.10, executed_price=2000.0,
        ticket=777001, magic_number=20250701,
    )
    ctx_a.record_fill(rep_a)

    assert 777001 in ctx_a.exec_state.open_positions
    assert 777001 not in ctx_b.exec_state.open_positions


def test_magic_number_collision_blocked():
    """10. Account A's magic number cannot be used by Account B."""
    from app.multi_account.account_registry import AccountRegistry

    reg = AccountRegistry()
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701)
    cfg_b_collision = AccountConfig(account_id="acc_B", login=10002, magic_number=20250701)

    reg.register(cfg_a)
    with pytest.raises(ValueError, match="Duplicate magic_number 20250701"):
        reg.register(cfg_b_collision)

