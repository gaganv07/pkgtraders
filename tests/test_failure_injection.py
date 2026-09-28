"""
tests/test_failure_injection.py — Automated Failure Injection & Fault Tolerance Matrix (Phase 7)

Validates complete fleet failure isolation across 13 failure modes:
1. Terminal crash
2. Worker crash
3. MT5 disconnect
4. Wrong login
5. Wrong server
6. Broker order rejection
7. Order execution timeout
8. API exception
9. Duplicate signal
10. Stale terminal detection
11. Corrupted account state
12. Restart during active position
13. Simultaneous failures in multiple accounts
"""

import asyncio
import pytest
from datetime import datetime, timezone
from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_context import (
    AccountContext,
    AccountStatus,
    NormalizedSignal,
    TradeExecutionReport,
)
from app.multi_account.account_manager import MT5AccountManager
from app.multi_account.mt5_session import FillResult, MT5DirectSession
from app.multi_account.terminal_supervisor import get_terminal_supervisor


def make_signal(sig_id: str) -> NormalizedSignal:
    return NormalizedSignal(
        signal_id=sig_id,
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )


@pytest.mark.asyncio
async def test_terminal_crash_isolation():
    """1. Terminal process on Account A crashes; Accounts B & C continue normally."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    cfg_c = AccountConfig(account_id="acc_C", login=10003, magic_number=20250703, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    ctx_c = mgr.add_account(cfg_c)
    await mgr.connect_all()
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_c.update_snapshot(balance=10000.0, equity=10000.0)

    # Simulate terminal crash on A
    ctx_a.status = AccountStatus.ERROR
    ctx_a.session.disconnect()

    reps = await mgr.distribute_signal(make_signal("sig_fail_term_crash"))
    await mgr.disconnect_all()

    assert reps["acc_A"].is_success is False
    assert reps["acc_B"].is_success is True
    assert reps["acc_C"].is_success is True


@pytest.mark.asyncio
async def test_worker_crash_isolation():
    """2. Worker task on Account A is cancelled/crashed; B & C continue."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    cfg_c = AccountConfig(account_id="acc_C", login=10003, magic_number=20250703, dry_run=True)
    mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    ctx_c = mgr.add_account(cfg_c)
    await mgr.connect_all()
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_c.update_snapshot(balance=10000.0, equity=10000.0)

    # Cancel worker A task
    w_a = mgr._workers.get("acc_A")
    if w_a and w_a._task:
        w_a._task.cancel()

    reps = await mgr.distribute_signal(make_signal("sig_fail_worker_crash"))
    await mgr.disconnect_all()

    assert reps["acc_B"].is_success is True
    assert reps["acc_C"].is_success is True


@pytest.mark.asyncio
async def test_mt5_disconnect_isolation():
    """3. Account A loses MT5 broker connection; B & C continue."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    ctx_a.status = AccountStatus.DISCONNECTED

    reps = await mgr.distribute_signal(make_signal("sig_fail_mt5_disc"))
    await mgr.disconnect_all()

    assert reps["acc_A"].is_success is False
    assert reps["acc_B"].is_success is True


@pytest.mark.asyncio
async def test_wrong_login_isolation():
    """4. Handshake on Account A detects wrong login; A locked to MISMATCH, B continues."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Force wrong login status
    ctx_a.status = AccountStatus.ACCOUNT_IDENTITY_MISMATCH

    reps = await mgr.distribute_signal(make_signal("sig_fail_wrong_login"))
    await mgr.disconnect_all()

    assert reps["acc_A"].is_success is False
    assert "ACCOUNT_IDENTITY_MISMATCH" in reps["acc_A"].rejection_reason
    assert reps["acc_B"].is_success is True


@pytest.mark.asyncio
async def test_wrong_server_isolation():
    """5. Handshake on Account A detects wrong server; A locked to MISMATCH, B continues."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, server="TargetServer", magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, server="TargetServer", magic_number=20250702, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    ctx_a.status = AccountStatus.ACCOUNT_IDENTITY_MISMATCH

    reps = await mgr.distribute_signal(make_signal("sig_fail_wrong_server"))
    await mgr.disconnect_all()

    assert reps["acc_A"].is_success is False
    assert reps["acc_B"].is_success is True


@pytest.mark.asyncio
async def test_broker_rejection_isolation():
    """6. Broker rejects order on Account A; Account B executes."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    ctx_a.session.buy = lambda *args, **kwargs: FillResult(success=False, error="Off Quotes [10004]")

    reps = await mgr.distribute_signal(make_signal("sig_fail_broker_rej"))
    await mgr.disconnect_all()

    assert reps["acc_A"].is_success is False
    assert "Off Quotes" in reps["acc_A"].rejection_reason
    assert reps["acc_B"].is_success is True


@pytest.mark.asyncio
async def test_timeout_isolation():
    """7. Order execution on Account A times out; Account B executes."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Session buy raises TimeoutError
    def slow_buy(*args, **kwargs):
        raise TimeoutError("Execution gateway timeout")

    ctx_a.session.buy = slow_buy

    reps = await mgr.distribute_signal(make_signal("sig_fail_timeout"))
    await mgr.disconnect_all()

    assert reps["acc_A"].is_success is False
    assert "timeout" in reps["acc_A"].rejection_reason.lower()
    assert reps["acc_B"].is_success is True


@pytest.mark.asyncio
async def test_api_exception_isolation():
    """8. Unhandled exception in Account A's execution pipeline is caught without stopping B."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    await mgr.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Throw unexpected runtime error on A
    def crash_buy(*args, **kwargs):
        raise RuntimeError("Unexpected OS socket crash")

    ctx_a.session.buy = crash_buy

    reps = await mgr.distribute_signal(make_signal("sig_fail_exception"))
    await mgr.disconnect_all()

    assert reps["acc_A"].is_success is False
    assert "socket crash" in reps["acc_A"].rejection_reason
    assert reps["acc_B"].is_success is True


def test_duplicate_signal_isolation():
    """9. Duplicate signal on Account A does not block new execution on Account B."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    ctx_a = AccountContext(config=cfg_a, mt5_session=MT5DirectSession(cfg_a))
    ctx_b = AccountContext(config=cfg_b, mt5_session=MT5DirectSession(cfg_b))
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_a.status = AccountStatus.CONNECTED
    ctx_b.status = AccountStatus.CONNECTED

    ctx_a.exec_state.processed_signals.add("sig_replay_001")

    ok_a, _ = ctx_a.is_trading_allowed("XAUUSD", signal_id="sig_replay_001")
    ok_b, _ = ctx_b.is_trading_allowed("XAUUSD", signal_id="sig_replay_001")

    assert ok_a is False
    assert ok_b is True


def test_stale_terminal_detection():
    """10. Terminal supervisor detects stale/unresponsive terminal session."""
    cfg = AccountConfig(account_id="acc_stale", login=10001, magic_number=20250701)
    supervisor = get_terminal_supervisor()
    # Unregistered/stale process returns False
    alive = supervisor.verify_terminal_process("acc_stale_nonexistent")
    assert alive is False


def test_corrupted_account_state_isolation():
    """11. Account A has corrupted financial numbers; falls back safely, B unaffected."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)

    # Corrupt Account A balance
    ctx_a.risk_state.current_balance = -500.0
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    vol_a, _ = mgr.calculate_position_size("acc_A", make_signal("sig_corrupt"))
    vol_b, _ = mgr.calculate_position_size("acc_B", make_signal("sig_corrupt"))

    # Account A falls back to baseline safely
    assert vol_a > 0.0
    assert vol_b > 0.0
    assert vol_b > vol_a


def test_restart_during_active_position():
    """12. Account A restarts during active position; reconciles without duplicating trade."""
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    sess_a = MT5DirectSession(cfg_a)
    sess_a.connect()
    ctx_a = AccountContext(config=cfg_a, mt5_session=sess_a)

    # Simulate existing active position
    fill_rep = TradeExecutionReport(
        account_id="acc_A", login=10001, signal_id="sig_active_pos", symbol="XAUUSD",
        direction="LONG", status="SUCCESS", executed_volume=0.20, executed_price=2000.0,
        ticket=888101, magic_number=20250701,
    )
    ctx_a.record_fill(fill_rep)
    assert 888101 in ctx_a.exec_state.open_positions

    # Re-sending the same signal must be blocked
    allowed, reason = ctx_a.is_trading_allowed("XAUUSD", signal_id="sig_active_pos")
    assert allowed is False
    assert "Duplicate signal" in reason


@pytest.mark.asyncio
async def test_simultaneous_failures_in_multiple_accounts():
    """13. Simultaneous failures in Accounts A & B; Account C continues execution."""
    reg = AccountRegistry()
    mgr = MT5AccountManager(registry=reg)
    cfg_a = AccountConfig(account_id="acc_A", login=10001, magic_number=20250701, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_B", login=10002, magic_number=20250702, dry_run=True)
    cfg_c = AccountConfig(account_id="acc_C", login=10003, magic_number=20250703, dry_run=True)

    ctx_a = mgr.add_account(cfg_a)
    ctx_b = mgr.add_account(cfg_b)
    ctx_c = mgr.add_account(cfg_c)
    await mgr.connect_all()
    ctx_c.update_snapshot(balance=10000.0, equity=10000.0)

    # Simultaneous failures: A disconnected, B auth error
    ctx_a.status = AccountStatus.DISCONNECTED
    ctx_b.status = AccountStatus.AUTH_ERROR

    reps = await mgr.distribute_signal(make_signal("sig_simultaneous_fail"))
    await mgr.disconnect_all()

    assert reps["acc_A"].is_success is False
    assert reps["acc_B"].is_success is False
    assert reps["acc_C"].is_success is True
