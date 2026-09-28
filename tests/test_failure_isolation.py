"""
tests/test_failure_isolation.py — Failure Isolation & Resilience Tests
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_context import NormalizedSignal, AccountStatus
from app.multi_account.account_manager import MT5AccountManager
from app.mt5_client import FillResult


@pytest.mark.asyncio
async def test_one_account_reject_does_not_block_another():
    """
    Simulate Account A order succeeds while Account B order is rejected by broker.
    Account A MUST succeed, and Account B's failure must not affect Account A.
    """
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg_a = AccountConfig(account_id="acc_success", login=1001, password="p", magic_number=1001, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_rejected", login=1002, password="p", magic_number=1002, dry_run=True)

    ctx_a = manager.add_account(cfg_a)
    ctx_b = manager.add_account(cfg_b)

    await manager.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Mock Account B's session to simulate broker rejection (e.g. Invalid Stops)
    ctx_b.session.buy = MagicMock(return_value=FillResult(
        success=False, retcode=10016, error="Invalid stops"
    ))

    signal = NormalizedSignal(
        signal_id="sig_iso_001",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )

    reports = await manager.distribute_signal(signal)

    assert "acc_success" in reports
    assert "acc_rejected" in reports

    rep_a = reports["acc_success"]
    rep_b = reports["acc_rejected"]

    assert rep_a.is_success is True
    assert rep_a.status == "SUCCESS"

    assert rep_b.is_success is False
    assert rep_b.status == "REJECTED"
    assert "Invalid stops" in rep_b.rejection_reason

    # Verify Account A has open trade recorded and Account B does not
    assert len(ctx_a.exec_state.open_positions) == 1
    assert len(ctx_b.exec_state.open_positions) == 0


@pytest.mark.asyncio
async def test_disconnected_account_does_not_stop_connected_account():
    """
    Simulate Account A is disconnected while Account B is connected.
    Account B MUST execute successfully, while Account A reports non-connection.
    """
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg_a = AccountConfig(account_id="acc_disconnected", login=1001, password="p", magic_number=1001, dry_run=True)
    cfg_b = AccountConfig(account_id="acc_connected", login=1002, password="p", magic_number=1002, dry_run=True)

    ctx_a = manager.add_account(cfg_a)
    ctx_b = manager.add_account(cfg_b)

    await manager.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)

    # Disconnect Account A
    ctx_a.status = AccountStatus.DISCONNECTED

    signal = NormalizedSignal(
        signal_id="sig_iso_002",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )

    reports = await manager.distribute_signal(signal)

    assert "acc_connected" in reports
    assert "acc_disconnected" in reports

    rep_b = reports["acc_connected"]
    rep_a = reports["acc_disconnected"]

    assert rep_b.is_success is True
    assert rep_b.status == "SUCCESS"

    assert rep_a.is_success is False
    assert rep_a.status == "REJECTED"
    assert any(w in rep_a.rejection_reason for w in ("not connected", "DISCONNECTED", "not ready"))


@pytest.mark.asyncio
async def test_clean_shutdown_all_sessions():
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg1 = AccountConfig(account_id="acc_shut_1", login=1001, password="p", magic_number=1001, dry_run=True)
    cfg2 = AccountConfig(account_id="acc_shut_2", login=1002, password="p", magic_number=1002, dry_run=True)

    ctx1 = manager.add_account(cfg1)
    ctx2 = manager.add_account(cfg2)

    await manager.connect_all()
    assert ctx1.status in (AccountStatus.CONNECTED, AccountStatus.EXECUTION_READY)
    assert ctx2.status in (AccountStatus.CONNECTED, AccountStatus.EXECUTION_READY)

    await manager.disconnect_all()
    assert ctx1.status == AccountStatus.DISCONNECTED
    assert ctx2.status == AccountStatus.DISCONNECTED
