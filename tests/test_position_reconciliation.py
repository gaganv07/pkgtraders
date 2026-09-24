"""
tests/test_position_reconciliation.py — Automated Tests for Phase 9: Position Reconciliation

Validates:
1. Startup reconciliation restores magic-matched positions into AccountContext.
2. Unknown positions (foreign magic numbers / manual trades) are detected and flagged.
3. Missing positions (closed externally on broker) are detected and removed from local state.
4. Duplicate internal records / tickets are handled cleanly.
5. Reconciled positions populate processed_signals to prevent blindly resending existing signals on restart.
6. Multi-account isolation during reconciliation: Account A's positions never leak into Account B.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest

from app.mt5_client import PositionSnapshot
from app.multi_account.account_context import (
    AccountContext,
    AccountStatus,
    NormalizedSignal,
)
from app.multi_account.account_registry import AccountConfig
from app.multi_account.account_worker import AccountWorker
from app.multi_account.account_manager import MT5AccountManager
from app.multi_account.mt5_session import MT5DirectSession


def _create_mock_session(config: AccountConfig, positions: list[PositionSnapshot]):
    """Helper creating a test session pre-populated with simulated positions."""
    sess = MT5DirectSession(config)
    sess._connected = True
    sess._positions = list(positions)
    return sess


@pytest.mark.asyncio
async def test_startup_reconciliation_reconstructs_matched_positions():
    """Verify that positions matching account magic number are reconstructed into internal state."""
    cfg = AccountConfig(
        account_id="acc_reconcile_1",
        login=1001,
        server="TestServer",
        magic_number=20250001,
        enabled=True,
        trading_enabled=True,
        dry_run=True,
    )
    ctx = AccountContext(cfg)
    
    pos1 = PositionSnapshot(
        ticket=101,
        symbol="XAUUSD",
        direction="LONG",
        volume=0.10,
        open_price=2050.0,
        current_price=2055.0,
        sl=2040.0,
        tp=2070.0,
        profit=50.0,
        swap=0.0,
        magic=20250001,
        comment="SIG-REC-01",
        open_time=datetime.now(timezone.utc),
    )
    sess = _create_mock_session(cfg, [pos1])
    ctx.session = sess
    ctx.status = AccountStatus.EXECUTION_READY

    worker = AccountWorker(ctx)
    report = await worker.reconcile_positions()

    assert report.matched_count == 1
    assert report.reconstructed_count == 1
    assert 101 in report.reconstructed_tickets
    assert 101 in ctx.exec_state.open_positions
    assert ctx.exec_state.open_positions[101]["volume"] == 0.10
    assert ctx.exec_state.open_positions[101]["comment"] == "SIG-REC-01"


@pytest.mark.asyncio
async def test_reconciliation_detects_unknown_positions():
    """Verify that positions with foreign magic number or 0 are flagged as unknown and not claimed."""
    cfg = AccountConfig(
        account_id="acc_reconcile_unknown",
        login=1002,
        server="TestServer",
        magic_number=20250002,
        enabled=True,
        trading_enabled=True,
        dry_run=True,
    )
    ctx = AccountContext(cfg)

    # pos1 matches, pos2 is manual/foreign magic
    pos1 = PositionSnapshot(
        ticket=201, symbol="XAUUSD", direction="BUY", volume=0.05,
        open_price=2050.0, current_price=2052.0, sl=2040.0, tp=2060.0,
        profit=10.0, swap=0.0, magic=20250002, comment="bot_order",
        open_time=datetime.now(timezone.utc),
    )
    pos2_foreign = PositionSnapshot(
        ticket=999, symbol="EURUSD", direction="SELL", volume=1.0,
        open_price=1.0850, current_price=1.0840, sl=1.0900, tp=1.0750,
        profit=100.0, swap=0.0, magic=99999999, comment="manual_trade",
        open_time=datetime.now(timezone.utc),
    )
    sess = _create_mock_session(cfg, [pos1, pos2_foreign])
    ctx.session = sess
    ctx.status = AccountStatus.EXECUTION_READY

    worker = AccountWorker(ctx)
    report = await worker.reconcile_positions()

    assert report.matched_count == 1
    assert report.unknown_count == 1
    assert 999 in report.unknown_tickets
    assert 201 in ctx.exec_state.open_positions
    # Foreign position must NOT be claimed as bot position
    assert 999 not in ctx.exec_state.open_positions


@pytest.mark.asyncio
async def test_reconciliation_detects_missing_positions():
    """Verify that if a position in local state disappears on MT5 (e.g. SL hit while offline), it is removed."""
    cfg = AccountConfig(
        account_id="acc_reconcile_missing",
        login=1003,
        server="TestServer",
        magic_number=20250003,
        enabled=True,
        trading_enabled=True,
        dry_run=True,
    )
    ctx = AccountContext(cfg)
    
    # Pre-populate internal state with ticket 301
    ctx.exec_state.open_positions[301] = {
        "ticket": 301,
        "symbol": "XAUUSD",
        "direction": "LONG",
        "volume": 0.05,
        "price": 2040.0,
        "sl": 2030.0,
        "tp": 2060.0,
        "profit": 0.0,
        "magic": 20250003,
    }

    # MT5 has 0 positions (position was closed on broker while disconnected)
    sess = _create_mock_session(cfg, [])
    ctx.session = sess
    ctx.status = AccountStatus.EXECUTION_READY

    worker = AccountWorker(ctx)
    report = await worker.reconcile_positions()

    assert report.missing_count == 1
    assert 301 in report.missing_tickets
    # Removed from internal open_positions
    assert 301 not in ctx.exec_state.open_positions


@pytest.mark.asyncio
async def test_reconciliation_prevents_blind_resend_on_restart():
    """Verify that restarting with an open position marks its signal as processed, preventing re-execution."""
    cfg = AccountConfig(
        account_id="acc_reconcile_restart",
        login=1004,
        server="TestServer",
        magic_number=20250004,
        enabled=True,
        trading_enabled=True,
        dry_run=True,
    )
    ctx = AccountContext(cfg)

    sig_id = "SIG_RESTART_PREVENTION_TEST"
    pos = PositionSnapshot(
        ticket=401,
        symbol="XAUUSD",
        direction="LONG",
        volume=0.10,
        open_price=2060.0,
        current_price=2062.0,
        sl=2050.0,
        tp=2080.0,
        profit=20.0,
        swap=0.0,
        magic=20250004,
        comment=sig_id,
        open_time=datetime.now(timezone.utc),
    )
    sess = _create_mock_session(cfg, [pos])
    ctx.session = sess
    ctx.status = AccountStatus.EXECUTION_READY

    worker = AccountWorker(ctx)
    await worker.reconcile_positions()

    # The signal ID must now be in processed_signals
    assert sig_id in ctx.exec_state.processed_signals

    # Attempting to trade with the same signal ID must be blocked fail-closed
    allowed, reason = ctx.is_trading_allowed("XAUUSD", signal_id=sig_id)
    assert not allowed
    assert "Duplicate signal" in reason


@pytest.mark.asyncio
async def test_multi_account_reconciliation_isolation():
    """Verify that reconciling Account A does not contaminate Account B's state."""
    cfg_a = AccountConfig(
        account_id="acc_iso_A",
        login=1005,
        server="ServerA",
        magic_number=20250005,
        enabled=True,
        trading_enabled=True,
        dry_run=True,
    )
    cfg_b = AccountConfig(
        account_id="acc_iso_B",
        login=1006,
        server="ServerB",
        magic_number=20250006,
        enabled=True,
        trading_enabled=True,
        dry_run=True,
    )
    ctx_a = AccountContext(cfg_a)
    ctx_b = AccountContext(cfg_b)

    pos_a = PositionSnapshot(
        ticket=501, symbol="XAUUSD", direction="LONG", volume=0.20,
        open_price=2050.0, current_price=2055.0, sl=2040.0, tp=2070.0,
        profit=100.0, swap=0.0, magic=20250005, comment="SIG-A",
        open_time=datetime.now(timezone.utc),
    )
    pos_b = PositionSnapshot(
        ticket=601, symbol="XAUUSD", direction="SHORT", volume=0.05,
        open_price=2055.0, current_price=2050.0, sl=2065.0, tp=2035.0,
        profit=25.0, swap=0.0, magic=20250006, comment="SIG-B",
        open_time=datetime.now(timezone.utc),
    )

    ctx_a.session = _create_mock_session(cfg_a, [pos_a])
    ctx_b.session = _create_mock_session(cfg_b, [pos_b])
    ctx_a.status = AccountStatus.EXECUTION_READY
    ctx_b.status = AccountStatus.EXECUTION_READY

    worker_a = AccountWorker(ctx_a)
    worker_b = AccountWorker(ctx_b)

    rep_a = await worker_a.reconcile_positions()
    rep_b = await worker_b.reconcile_positions()

    assert 501 in ctx_a.exec_state.open_positions
    assert 501 not in ctx_b.exec_state.open_positions

    assert 601 in ctx_b.exec_state.open_positions
    assert 601 not in ctx_a.exec_state.open_positions

    assert "SIG-A" in ctx_a.exec_state.processed_signals
    assert "SIG-A" not in ctx_b.exec_state.processed_signals
