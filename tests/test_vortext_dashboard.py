import aiohttp
"""
tests/test_vortext_dashboard.py — Comprehensive Unit & Integration Tests for VORTEXT Live Feed Publisher
"""
from datetime import datetime, timezone
import json
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.multi_account.account_context import AccountContext
from app.multi_account.account_manager import MT5AccountManager
from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.mt5_session import IMT5Session, MT5DirectSession, MT5ProcessSession
from app.vortext_dashboard import (
    build_snapshot,
    make_signature,
    VortextDashboardPublisher,
    _deal_entry,
    _format_deal,
    _format_position,
    _iso,
    _num,
)


class MockSession(IMT5Session):
    """Mock session for testing isolated multi-account snapshots."""

    def __init__(self, config: AccountConfig, balance=1000.0, equity=1050.0, margin=50.0, free_margin=1000.0, positions=None, deals=None):
        self.config = config
        self._connected = True
        self._balance = balance
        self._equity = equity
        self._margin = margin
        self._free_margin = free_margin
        self._positions = positions or []
        self._deals = deals or []

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_account_info(self):
        if not self._connected:
            return None
        return {
            "login": self.config.login,
            "server": self.config.server,
            "balance": self._balance,
            "equity": self._equity,
            "margin": self._margin,
            "free_margin": self._free_margin,
            "margin_level": 2100.0,
            "currency": "USD",
            "leverage": 100,
            "trade_mode": 0,  # DEMO
            "trade_allowed": True,
        }

    def get_positions(self, symbol=None, all_magic=False):
        if not self._connected:
            return []
        if all_magic:
            return self._positions
        return [p for p in self._positions if getattr(p, "magic", p.get("magic") if isinstance(p, dict) else None) == self.config.magic_number]

    def get_history_deals(self, start=None, end=None, all_magic=False, days=7):
        if not self._connected:
            return []
        if all_magic:
            return self._deals
        return [d for d in self._deals if getattr(d, "magic", d.get("magic") if isinstance(d, dict) else None) == self.config.magic_number]

    def get_symbol_spec(self, symbol: str):
        return None

    def get_tick(self, symbol: str):
        return None

    def buy(self, volume: float, sl: float, tp: float, comment: str = "", symbol: str = "XAUUSD"):
        raise NotImplementedError("Publisher must never execute buy orders")

    def sell(self, volume: float, sl: float, tp: float, comment: str = "", symbol: str = "XAUUSD"):
        raise NotImplementedError("Publisher must never execute sell orders")

    def modify(self, ticket: int, sl: float, tp: float, symbol: str = "XAUUSD"):
        raise NotImplementedError("Publisher must never modify orders")

    def close(self, ticket: int, volume=None, reason: str = "manual", symbol=None):
        raise NotImplementedError("Publisher must never close orders")

    def close_all(self, reason: str = "emergency") -> int:
        raise NotImplementedError("Publisher must never close orders")


# ── HMAC & Security Tests ───────────────────────────────────────────────────

def test_hmac_signature_is_deterministic_and_binds_the_body():
    secret = "x" * 64
    timestamp = "1793161000"
    body = b'{"bot_id":"vortext-fleet"}'
    sig = make_signature(secret, timestamp, body)
    assert len(sig) == 64
    assert sig == make_signature(secret, timestamp, body)
    assert sig != make_signature(secret, timestamp, body + b" ")
    assert sig != make_signature(secret, "1793161001", body)


def test_publisher_is_disabled_by_default(monkeypatch):
    for key in ("VORTEXT_DASHBOARD_SYNC_ENABLED", "VORTEXT_DASHBOARD_INGEST_URL", "VORTEXT_BOT_HMAC_SECRET"):
        monkeypatch.delenv(key, raising=False)
    publisher = VortextDashboardPublisher(mt5_client=SimpleNamespace(connected=True, _sim_mode=False))
    assert publisher.enabled is False


def test_publisher_enabled_only_when_fully_configured(monkeypatch):
    monkeypatch.setenv("VORTEXT_DASHBOARD_SYNC_ENABLED", "true")
    monkeypatch.setenv("VORTEXT_DASHBOARD_INGEST_URL", "https://pkgtraders-demo.vercel.app/api/trades")
    monkeypatch.setenv("VORTEXT_BOT_HMAC_SECRET", "a" * 32)
    monkeypatch.setenv("VORTEXT_BOT_ID", "vortext-fleet")
    monkeypatch.setenv("VORTEXT_PUBLISH_INTERVAL_SECONDS", "10")

    publisher = VortextDashboardPublisher(mt5_client=SimpleNamespace(connected=True, _sim_mode=False))
    assert publisher.enabled is True
    assert publisher.interval_seconds == 10.0
    assert publisher.bot_id == "vortext-fleet"


def test_publisher_rejects_insecure_http_endpoint(monkeypatch):
    monkeypatch.setenv("VORTEXT_DASHBOARD_SYNC_ENABLED", "true")
    monkeypatch.setenv("VORTEXT_DASHBOARD_INGEST_URL", "http://insecure-site.com/api/trades")
    monkeypatch.setenv("VORTEXT_BOT_HMAC_SECRET", "a" * 32)
    publisher = VortextDashboardPublisher(mt5_client=SimpleNamespace())
    assert publisher.enabled is False


def test_publisher_rejects_short_hmac_secret(monkeypatch):
    monkeypatch.setenv("VORTEXT_DASHBOARD_SYNC_ENABLED", "true")
    monkeypatch.setenv("VORTEXT_DASHBOARD_INGEST_URL", "https://pkgtraders-demo.vercel.app/api/trades")
    monkeypatch.setenv("VORTEXT_BOT_HMAC_SECRET", "too-short-secret")
    publisher = VortextDashboardPublisher(mt5_client=SimpleNamespace())
    assert publisher.enabled is False


# ── Snapshot Construction & Simulation Rejection Tests ───────────────────────

def test_snapshot_refuses_simulated_or_disconnected_client():
    disconnected = SimpleNamespace(connected=False, _sim_mode=False)
    with pytest.raises(RuntimeError, match="not connected"):
        build_snapshot(disconnected)

    simulated = SimpleNamespace(connected=True, _sim_mode=True)
    with pytest.raises(RuntimeError, match="simulated"):
        build_snapshot(simulated)


def test_snapshot_single_account_legacy_success():
    account_data = {
        "login": 123456,
        "server": "Test-Server",
        "currency": "USD",
        "balance": 5000.0,
        "equity": 5200.0,
        "margin": 100.0,
        "margin_free": 5100.0,
        "leverage": 200,
        "trade_mode": 0,
    }
    positions_data = [
        {
            "ticket": 101,
            "symbol": "XAUUSD",
            "direction": "buy",
            "volume": 0.05,
            "open_price": 2700.0,
            "current_price": 2710.0,
            "sl": 2690.0,
            "tp": 2730.0,
            "profit": 50.0,
            "swap": 0.0,
            "open_time": 1730000000,
            "magic": 20250701,
        }
    ]
    deals_data = [
        {
            "ticket": 201,
            "order": 101,
            "symbol": "XAUUSD",
            "type": 0,  # DEAL_TYPE_BUY
            "entry": 0,  # DEAL_ENTRY_IN
            "volume": 0.05,
            "price": 2700.0,
            "profit": 0.0,
            "commission": -0.5,
            "swap": 0.0,
            "fee": 0.0,
            "time": 1730000000,
            "magic": 20250701,
        }
    ]
    client = SimpleNamespace(
        connected=True,
        _sim_mode=False,
        _cfg=SimpleNamespace(magic=20250701),
        get_account=lambda: account_data,
        get_positions=lambda: positions_data,
        get_history=lambda start, end: deals_data,
    )
    snapshot = build_snapshot(client, bot_id="test-bot")
    assert snapshot["bot_id"] == "test-bot"
    assert snapshot["account"]["balance"] == 5000.0
    assert snapshot["account"]["equity"] == 5200.0
    assert snapshot["account"]["trade_mode"] == "DEMO"
    assert len(snapshot["positions"]) == 1
    assert snapshot["positions"][0]["ticket"] == "101"
    assert snapshot["positions"][0]["side"] == "buy"
    assert len(snapshot["deals"]) == 1
    assert snapshot["deals"][0]["ticket"] == "201"
    assert snapshot["deals"][0]["side"] == "buy"
    assert snapshot["deals"][0]["entry"] == "in"
    assert len(snapshot["accounts"]) == 1
    assert snapshot["fleet_summary"]["total_accounts"] == 1


# ── Multi-Account Fleet Tests ────────────────────────────────────────────────

def test_snapshot_multi_account_fleet_success():
    cfg1 = AccountConfig(
        account_id="account_001",
        enabled=True,
        trading_enabled=False,
        login=111111,
        server="BrokerA-Demo",
        magic_number=1001,
        dry_run=False,
    )
    pos1 = {
        "ticket": 1001,
        "symbol": "EURUSD",
        "direction": "buy",
        "volume": 0.1,
        "open_price": 1.0800,
        "current_price": 1.0850,
        "sl": 1.0750,
        "tp": 1.0900,
        "profit": 50.0,
        "swap": 0.0,
        "open_time": 1730001000,
        "magic": 1001,
    }
    deal1 = {
        "ticket": 5001,
        "order": 1001,
        "symbol": "EURUSD",
        "type": 0,
        "entry": 0,
        "volume": 0.1,
        "price": 1.0800,
        "profit": 0.0,
        "commission": -0.7,
        "swap": 0.0,
        "fee": 0.0,
        "time": 1730001000,
        "magic": 1001,
    }
    session1 = MockSession(cfg1, balance=2000.0, equity=2050.0, margin=20.0, free_margin=2030.0, positions=[pos1], deals=[deal1])
    ctx1 = AccountContext(config=cfg1, mt5_session=session1)

    cfg2 = AccountConfig(
        account_id="account_002",
        enabled=True,
        trading_enabled=True,
        login=222222,
        server="BrokerB-Demo",
        magic_number=1002,
        dry_run=False,
    )
    pos2 = {
        "ticket": 2002,
        "symbol": "XAUUSD",
        "direction": "sell",
        "volume": 0.05,
        "open_price": 2720.0,
        "current_price": 2715.0,
        "sl": 2730.0,
        "tp": 2700.0,
        "profit": 25.0,
        "swap": -1.5,
        "open_time": 1730002000,
        "magic": 1002,
    }
    session2 = MockSession(cfg2, balance=3000.0, equity=3023.5, margin=30.0, free_margin=2993.5, positions=[pos2], deals=[])
    ctx2 = AccountContext(config=cfg2, mt5_session=session2)

    manager = MagicMock()
    manager._contexts = {
        "account_001": ctx1,
        "account_002": ctx2,
    }

    snapshot = build_snapshot(manager, bot_id="vortext-fleet")

    assert snapshot["bot_id"] == "vortext-fleet"
    assert len(snapshot["accounts"]) == 2
    assert snapshot["fleet_summary"]["total_accounts"] == 2
    assert snapshot["fleet_summary"]["total_balance"] == 5000.0
    assert snapshot["fleet_summary"]["total_equity"] == 5073.5
    assert snapshot["fleet_summary"]["total_floating_pnl"] == 73.5  # 50 + (25 - 1.5)
    assert len(snapshot["positions"]) == 2
    assert len(snapshot["deals"]) == 1

    # Check tagging of positions
    p_eur = next(p for p in snapshot["positions"] if p["symbol"] == "EURUSD")
    assert p_eur["account_id"] == "account_001"
    assert p_eur["login"] == 111111
    assert p_eur["side"] == "buy"

    p_gold = next(p for p in snapshot["positions"] if p["symbol"] == "XAUUSD")
    assert p_gold["account_id"] == "account_002"
    assert p_gold["login"] == 222222
    assert p_gold["side"] == "sell"


def test_snapshot_multi_account_refuses_dry_run_only():
    cfg = AccountConfig(
        account_id="sim_account",
        enabled=True,
        trading_enabled=False,
        login=999999,
        server="SimServer",
        magic_number=9999,
        dry_run=True,  # SIMULATED / DRY-RUN
    )
    session = MockSession(cfg)
    ctx = AccountContext(config=cfg, mt5_session=session)
    manager = MagicMock()
    manager._contexts = {"sim_account": ctx}

    with pytest.raises(RuntimeError, match="No active real MT5 accounts"):
        build_snapshot(manager)


def test_deal_magic_filtering_in_multi_account():
    cfg = AccountConfig(account_id="acc", login=1, server="s", magic_number=777, enabled=True, dry_run=False)
    # Deal with matching magic 777 and foreign magic 999
    deals = [
        {"ticket": 1, "symbol": "XAUUSD", "type": 0, "entry": 0, "volume": 0.01, "price": 2000.0, "profit": 10.0, "magic": 777},
        {"ticket": 2, "symbol": "XAUUSD", "type": 0, "entry": 0, "volume": 0.01, "price": 2000.0, "profit": 50.0, "magic": 999},
    ]
    session = MockSession(cfg, deals=deals)
    ctx = AccountContext(config=cfg, mt5_session=session)
    manager = MagicMock()
    manager._contexts = {"acc": ctx}

    snapshot = build_snapshot(manager)
    assert len(snapshot["deals"]) == 1
    assert snapshot["deals"][0]["ticket"] == "1"


# ── JSON Serialization & Safety Tests ────────────────────────────────────────

def test_payload_json_serializable_no_nan():
    cfg = AccountConfig(account_id="acc", login=1, server="s", magic_number=777, enabled=True, dry_run=False)
    session = MockSession(cfg, balance=123.45, equity=123.45)
    ctx = AccountContext(config=cfg, mt5_session=session)
    manager = MagicMock()
    manager._contexts = {"acc": ctx}

    snapshot = build_snapshot(manager)
    # Must serialize strictly with allow_nan=False
    raw_json = json.dumps(snapshot, ensure_ascii=True, allow_nan=False)
    assert "vortext-fleet" in raw_json
    assert "123.45" in raw_json


# ── Network Error Isolation Tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_once_handles_network_error_gracefully():
    publisher = VortextDashboardPublisher(mt5_client=SimpleNamespace())
    publisher.endpoint = "https://pkgtraders-demo.vercel.app/api/trades"
    publisher.secret = "a" * 32

    class FailingContextManager:
        async def __aenter__(self):
            raise aiohttp.ClientError("Simulated connection timeout")
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_session = MagicMock()
    mock_session.post.return_value = FailingContextManager()

    # Must return False and not raise an exception
    success = await publisher.publish_once(mock_session, {"test": "payload"})
    assert success is False


# ── MT5DirectSession & MT5ProcessSession Deal History Interface Tests ───────

def test_direct_session_get_history_deals_dry_run():
    cfg = AccountConfig(account_id="dry", login=1, server="s", dry_run=True)
    session = MT5DirectSession(cfg)
    assert session.get_history_deals() == []


def test_process_session_get_history_deals_disconnected():
    cfg = AccountConfig(account_id="proc", login=1, server="s", dry_run=False)
    session = MT5ProcessSession(cfg)
    assert session.get_history_deals() == []

# ── Simulation symbol fail-closed tests ──────────────────────────────────────

@pytest.mark.parametrize("session_type", [MT5DirectSession, MT5ProcessSession])
def test_dry_run_sessions_do_not_fallback_to_another_symbols_contract(session_type):
    cfg = AccountConfig(
        account_id="sim_symbol_guard",
        login=123456,
        server="Simulation-Server",
        dry_run=True,
    )
    session = session_type(cfg)

    gold_spec = session.get_symbol_spec("XAUUSD")
    assert gold_spec is not None
    assert gold_spec["contract_size"] == 100.0

    # No simulated quote/spec exists for symbols outside the explicit fixture map.
    assert session.get_symbol_spec("XAGUSD") is None
    assert session.get_tick("XAGUSD") is None
