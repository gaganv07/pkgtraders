"""
tests/test_multi_account_execution.py — Signal Fan-Out & Execution Coordinator Tests
"""

import pytest
from datetime import datetime, timezone

from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_context import NormalizedSignal, AccountStatus, AccountContext
from app.multi_account.account_manager import MT5AccountManager


@pytest.mark.asyncio
async def test_signal_fanout_execution():
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    # Register two dry-run accounts
    cfg_a = AccountConfig(
        account_id="acc_alpha", login=1001, password="pwd", magic_number=20250701,
        risk_per_trade_pct=1.0, dry_run=True
    )
    cfg_b = AccountConfig(
        account_id="acc_beta", login=1002, password="pwd", magic_number=20250702,
        risk_per_trade_pct=0.5, dry_run=True
    )

    ctx_a = manager.add_account(cfg_a)
    ctx_b = manager.add_account(cfg_b)

    await manager.connect_all()
    ctx_a.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_b.update_snapshot(balance=20000.0, equity=20000.0)

    signal = NormalizedSignal(
        signal_id="sig_exec_001",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
        quality_score=85.0,
    )

    reports = await manager.distribute_signal(signal)

    assert len(reports) == 2
    assert "acc_alpha" in reports
    assert "acc_beta" in reports

    rep_a = reports["acc_alpha"]
    rep_b = reports["acc_beta"]

    # Both succeeded in dry run
    assert rep_a.is_success is True
    assert rep_b.is_success is True

    # Check magic numbers are preserved and unique
    assert rep_a.magic_number == 20250701
    assert rep_b.magic_number == 20250702
    assert rep_a.magic_number != rep_b.magic_number

    # Check order attribution
    assert rep_a.account_id == "acc_alpha"
    assert rep_b.account_id == "acc_beta"
    assert rep_a.signal_id == "sig_exec_001"
    assert rep_b.signal_id == "sig_exec_001"

    # Check position sizes reflect individual account risk settings
    assert rep_a.executed_volume > 0
    assert rep_b.executed_volume > 0


@pytest.mark.asyncio
async def test_global_emergency_stop_blocks_execution():
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg = AccountConfig(account_id="acc_stop", login=1001, password="pwd", magic_number=1001, dry_run=True)
    ctx = manager.add_account(cfg)
    await manager.connect_all()
    ctx.update_snapshot(balance=10000.0, equity=10000.0)

    # Activate global emergency stop
    manager.global_emergency_stop = True

    signal = NormalizedSignal(
        signal_id="sig_blocked",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )

    reports = await manager.distribute_signal(signal)
    assert reports == {}


@pytest.mark.asyncio
async def test_disabled_account_skipped_during_fanout():
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg_enabled = AccountConfig(account_id="acc_enabled", login=1001, password="pwd", magic_number=1001, enabled=True, dry_run=True)
    cfg_disabled = AccountConfig(account_id="acc_disabled", login=1002, password="pwd", magic_number=1002, enabled=False, dry_run=True)

    ctx_en = manager.add_account(cfg_enabled)
    ctx_dis = manager.add_account(cfg_disabled)

    await manager.connect_all()
    ctx_en.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_dis.update_snapshot(balance=10000.0, equity=10000.0)

    signal = NormalizedSignal(
        signal_id="sig_test_skip",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )

    reports = await manager.distribute_signal(signal)

    assert "acc_enabled" in reports
    assert "acc_disabled" not in reports
    assert reports["acc_enabled"].is_success is True


@pytest.mark.asyncio
async def test_dry_run_deterministic_3_accounts():
    """
    Dry-run simulation with 3 accounts:
    Account A: Balance = $1,000, Risk = 1.0%
    Account B: Balance = $5,000, Risk = 1.0%
    Account C: Balance = $10,000, Risk = 0.5%
    One BUY XAUUSD signal.
    Verify:
    - Orders generated for A, B, C independently
    - Independent volumes reflecting balance/risk
    - Zero real MT5 orders placed
    """
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg_a = AccountConfig(
        account_id="account_A", login=10001, password="pwd", magic_number=100001,
        risk_per_trade_pct=1.0, initial_balance=1000.0, dry_run=True
    )
    cfg_b = AccountConfig(
        account_id="account_B", login=10002, password="pwd", magic_number=100002,
        risk_per_trade_pct=1.0, initial_balance=5000.0, dry_run=True
    )
    cfg_c = AccountConfig(
        account_id="account_C", login=10003, password="pwd", magic_number=100003,
        risk_per_trade_pct=0.5, initial_balance=10000.0, dry_run=True
    )

    ctx_a = manager.add_account(cfg_a)
    ctx_b = manager.add_account(cfg_b)
    ctx_c = manager.add_account(cfg_c)

    await manager.connect_all()

    ctx_a.update_snapshot(balance=1000.0, equity=1000.0)
    ctx_b.update_snapshot(balance=5000.0, equity=5000.0)
    ctx_c.update_snapshot(balance=10000.0, equity=10000.0)

    signal = NormalizedSignal(
        signal_id="sig_deterministic_buy",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,  # 5 pt SL
        take_profit_1=2010.0,
        quality_score=90.0,
    )

    reports = await manager.distribute_signal(signal)

    assert len(reports) == 3
    assert all(rep.is_success for rep in reports.values())
    assert all(rep.executed_price > 0 for rep in reports.values())

    rep_a = reports["account_A"]
    rep_b = reports["account_B"]
    rep_c = reports["account_C"]

    # Verify independent order identity
    assert rep_a.account_id == "account_A"
    assert rep_b.account_id == "account_B"
    assert rep_c.account_id == "account_C"

    # Verify magic numbers
    assert rep_a.magic_number == 100001
    assert rep_b.magic_number == 100002
    assert rep_c.magic_number == 100003

    # Verify volumes calculated independently
    # Account A: $1000 * 1% = $10 risk
    # Account B: $5000 * 1% = $50 risk -> 5x volume of A
    # Account C: $10000 * 0.5% = $50 risk -> ~same volume as B, 5x volume of A
    assert rep_b.executed_volume > rep_a.executed_volume
    assert rep_c.executed_volume > rep_a.executed_volume
    assert rep_b.executed_volume == pytest.approx(rep_c.executed_volume, rel=0.1)


@pytest.mark.asyncio
async def test_duplicate_signal_protection():
    """Verify the same signal cannot create duplicate trades on the same account."""
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg = AccountConfig(account_id="acc_dup", login=2001, password="pwd", magic_number=2001, dry_run=True)
    ctx = manager.add_account(cfg)
    await manager.connect_all()
    ctx.update_snapshot(balance=10000.0, equity=10000.0)

    signal = NormalizedSignal(
        signal_id="sig_unique_999",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
    )

    # First dispatch -> Success
    rep1 = await manager.distribute_signal(signal)
    assert rep1["acc_dup"].is_success is True

    # Second dispatch with identical signal_id -> Rejected duplicate
    rep2 = await manager.distribute_signal(signal)
    assert rep2["acc_dup"].is_success is False
    assert rep2["acc_dup"].status == "REJECTED"
    assert "Duplicate signal" in rep2["acc_dup"].rejection_reason


@pytest.mark.asyncio
async def test_mt5_account_mismatch_protection():
    """Verify execution is refused if context account doesn't match session account."""
    from app.multi_account.mt5_session import MT5DirectSession

    cfg_ctx = AccountConfig(account_id="acc_expected", login=5555, password="pwd", magic_number=5555, dry_run=True)
    cfg_sess = AccountConfig(account_id="acc_mismatched", login=9999, password="pwd", magic_number=9999, dry_run=True)

    # Session has login 9999, but Context expects login 5555
    mismatched_session = MT5DirectSession(config=cfg_sess)
    ctx = AccountContext(config=cfg_ctx, mt5_session=mismatched_session)

    allowed, reason = ctx.is_trading_allowed("XAUUSD", signal_id="sig_test_mismatch")
    assert allowed is False
    assert "MT5 account mismatch" in reason


@pytest.mark.asyncio
async def test_restart_position_recovery():
    """Verify that restarting the bot recovers existing open positions from MT5 session."""
    from app.multi_account.mt5_session import MT5DirectSession
    from app.multi_account.account_worker import AccountWorker
    from app.mt5_client import PositionSnapshot

    cfg = AccountConfig(account_id="acc_restart", login=7777, password="pwd", magic_number=7777, dry_run=True)
    session = MT5DirectSession(config=cfg)

    now = datetime.now(timezone.utc)
    # Pre-populate simulated open positions in session
    session._positions = [
        PositionSnapshot(
            ticket=5001,
            symbol="XAUUSD",
            direction="LONG",
            volume=0.10,
            open_price=2000.0,
            current_price=2005.0,
            sl=1995.0,
            tp=2010.0,
            profit=50.0,
            swap=0.0,
            magic=7777,
            comment="pkg",
            open_time=now,
        ),
        PositionSnapshot(
            ticket=5002,
            symbol="EURUSD",
            direction="SHORT",
            volume=0.20,
            open_price=1.0850,
            current_price=1.0860,
            sl=1.0900,
            tp=1.0750,
            profit=-20.0,
            swap=0.0,
            magic=7777,
            comment="pkg",
            open_time=now,
        ),
    ]

    ctx = AccountContext(config=cfg, mt5_session=session)
    worker = AccountWorker(context=ctx)

    assert len(ctx.exec_state.open_positions) == 0

    # Simulate restart connection and reconciliation
    await worker.connect()

    # Verify positions recovered
    assert len(ctx.exec_state.open_positions) == 2
    assert 5001 in ctx.exec_state.open_positions
    assert 5002 in ctx.exec_state.open_positions
    assert ctx.exec_state.open_positions[5001]["volume"] == 0.10
    assert ctx.exec_state.open_positions[5002]["direction"] == "SHORT"


@pytest.mark.asyncio
async def test_signal_fanout_exact_phase8_tiers():
    """
    Phase 8 validation:
    One strategy signal distributed across 3 distinct tiers:
    Account A: $1,000
    Account B: $10,000
    Account C: $50,000
    Each must independently calculate: lot size, risk, SL, TP, execution parameters.
    Never calculate one account's lot size and reuse it for another account.
    """
    registry = AccountRegistry()
    manager = MT5AccountManager(registry=registry)

    cfg_a = AccountConfig(
        account_id="tier_1k", login=101, password="pwd", magic_number=20251001,
        risk_per_trade_pct=1.0, initial_balance=1000.0, dry_run=True
    )
    cfg_b = AccountConfig(
        account_id="tier_10k", login=102, password="pwd", magic_number=20251002,
        risk_per_trade_pct=1.0, initial_balance=10000.0, dry_run=True
    )
    cfg_c = AccountConfig(
        account_id="tier_50k", login=103, password="pwd", magic_number=20251003,
        risk_per_trade_pct=1.0, initial_balance=50000.0, dry_run=True
    )

    ctx_a = manager.add_account(cfg_a)
    ctx_b = manager.add_account(cfg_b)
    ctx_c = manager.add_account(cfg_c)

    await manager.connect_all()

    ctx_a.update_snapshot(balance=1000.0, equity=1000.0)
    ctx_b.update_snapshot(balance=10000.0, equity=10000.0)
    ctx_c.update_snapshot(balance=50000.0, equity=50000.0)

    signal = NormalizedSignal(
        signal_id="sig_phase8_fanout",
        timestamp=datetime.now(timezone.utc),
        symbol="XAUUSD",
        direction="LONG",
        entry_reference=2000.0,
        stop_loss=1995.0,  # 5 pt SL
        take_profit_1=2010.0,
        quality_score=95.0,
    )

    reports = await manager.distribute_signal(signal)

    assert len(reports) == 3
    rep_a = reports["tier_1k"]
    rep_b = reports["tier_10k"]
    rep_c = reports["tier_50k"]

    assert rep_a.is_success and rep_b.is_success and rep_c.is_success

    # Strict volume inequality reflecting independent calculation:
    # $1,000 (1%) -> $10 risk
    # $10,000 (1%) -> $100 risk (10x of A)
    # $50,000 (1%) -> $500 risk (50x of A, 5x of B)
    assert rep_a.executed_volume < rep_b.executed_volume < rep_c.executed_volume
    assert rep_b.executed_volume >= 5 * rep_a.executed_volume
    assert rep_c.executed_volume >= 4 * rep_b.executed_volume

    # Each execution report has unique magic number and account ID
    assert rep_a.magic_number == 20251001
    assert rep_b.magic_number == 20251002
    assert rep_c.magic_number == 20251003


