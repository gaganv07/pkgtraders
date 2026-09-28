"""
tests/test_multi_account_api.py — Test Suite for Multi-Account REST API Endpoints

Validates:
- GET /api/accounts (masked credentials, status, metrics)
- GET /api/accounts/summary (fleet aggregates)
- GET /api/accounts/{id} (detailed context & positions)
- POST /api/accounts/{id}/toggle (admin & trading enable toggles)
- POST /api/accounts/{id}/close-all (account position liquidation)
- POST /api/accounts/emergency-stop & /reset (fleet kill-switch)
- POST /api/accounts/toggle-bot (bot enable/pause)
- Verification that router is mounted and accessible via dashboard apps
"""

import pytest
from fastapi.testclient import TestClient

from app.multi_account.account_registry import AccountConfig, AccountRegistry
from app.multi_account.account_manager import MT5AccountManager
from app.multi_account.multi_account_api import set_api_account_manager
from dashboard.control_center import app as control_center_app
from dashboard.app import app as dash_app


@pytest.fixture
def mock_account_manager():
    """Build a multi-account manager with 3 test accounts and inject into API."""
    registry = AccountRegistry()
    cfg1 = AccountConfig(
        account_id="acc_fleet_1",
        login=10101,
        server="BrokerA-Server",
        password="super_secret_password_1",
        magic_number=10101,
        risk_per_trade_pct=1.0,
        initial_balance=10000.0,
        dry_run=True,
    )
    cfg2 = AccountConfig(
        account_id="acc_fleet_2",
        login=10102,
        server="BrokerB-Server",
        password="super_secret_password_2",
        magic_number=10102,
        risk_per_trade_pct=0.5,
        initial_balance=25000.0,
        dry_run=True,
    )
    cfg3 = AccountConfig(
        account_id="acc_fleet_3",
        login=10103,
        server="BrokerC-Server",
        password="super_secret_password_3",
        magic_number=10103,
        enabled=False,
        dry_run=True,
    )

    manager = MT5AccountManager(registry=registry)
    ctx1 = manager.add_account(cfg1)
    ctx2 = manager.add_account(cfg2)
    ctx3 = manager.add_account(cfg3)

    ctx1.update_snapshot(balance=10000.0, equity=10250.0, margin=100.0, free_margin=10150.0)
    ctx2.update_snapshot(balance=25000.0, equity=24800.0, margin=200.0, free_margin=24600.0)

    set_api_account_manager(manager)
    return manager


@pytest.fixture
def cc_client(mock_account_manager):
    return TestClient(control_center_app)


@pytest.fixture
def dash_client(mock_account_manager):
    return TestClient(dash_app)


def test_list_accounts_masks_credentials(cc_client):
    """Verify GET /api/accounts returns list and hides all passwords."""
    resp = cc_client.get("/api/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3

    for acct in data:
        # Passwords must NEVER be present or exposed
        assert "password" not in acct or acct.get("password") == "********"
        assert "super_secret_password" not in str(acct)
        assert acct["account_id"] in ["acc_fleet_1", "acc_fleet_2", "acc_fleet_3"]
        assert "balance" in acct
        assert "equity" in acct
        assert "status" in acct


def test_fleet_summary_metrics(cc_client):
    """Verify GET /api/accounts/summary computes fleet aggregates."""
    resp = cc_client.get("/api/accounts/summary")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_accounts"] == 3
    assert data["total_equity"] == pytest.approx(35050.0, rel=1e-2)
    assert data["emergency_stop"] is False
    assert data["bot_enabled"] is True
    assert "per_account" in data


def test_get_account_details_and_not_found(cc_client):
    """Verify GET /api/accounts/{id} returns details and 404 for unknown accounts."""
    resp = cc_client.get("/api/accounts/acc_fleet_1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["account_id"] == "acc_fleet_1"
    assert data["login"] == 10101
    assert data["balance"] == 10000.0
    assert "positions" in data
    assert "processed_signals_count" in data

    # Unknown account
    resp_404 = cc_client.get("/api/accounts/non_existent_account")
    assert resp_404.status_code == 404


def test_toggle_account_administrative_and_trading(cc_client, mock_account_manager):
    """Verify POST /api/accounts/{id}/toggle toggles enabled & trading_enabled."""
    ctx1 = mock_account_manager.get_account("acc_fleet_1")
    assert ctx1.config.enabled is True
    assert ctx1.config.trading_enabled is True

    # Toggle trading only to False
    resp1 = cc_client.post("/api/accounts/acc_fleet_1/toggle", json={"trading_only": True, "enabled": False})
    assert resp1.status_code == 200
    assert resp1.json()["new_value"] is False
    assert ctx1.config.trading_enabled is False
    assert ctx1.config.enabled is True

    # Toggle overall enabled to False
    resp2 = cc_client.post("/api/accounts/acc_fleet_1/toggle", json={"trading_only": False, "enabled": False})
    assert resp2.status_code == 200
    assert resp2.json()["new_value"] is False
    assert ctx1.config.enabled is False
    assert ctx1.status.value == "DISABLED"


def test_emergency_stop_lifecycle(cc_client, mock_account_manager):
    """Verify POST /api/accounts/emergency-stop activates and resets kill-switch."""
    assert mock_account_manager.global_emergency_stop is False

    # Activate emergency stop
    resp_stop = cc_client.post(
        "/api/accounts/emergency-stop",
        json={"close_positions": False, "reason": "Operator Drill"}
    )
    assert resp_stop.status_code == 200
    assert resp_stop.json()["global_emergency_stop"] is True
    assert mock_account_manager.global_emergency_stop is True

    # Reset emergency stop
    resp_reset = cc_client.post("/api/accounts/emergency-stop/reset")
    assert resp_reset.status_code == 200
    assert resp_reset.json()["global_emergency_stop"] is False
    assert mock_account_manager.global_emergency_stop is False


def test_toggle_bot_trading(cc_client, mock_account_manager):
    """Verify POST /api/accounts/toggle-bot toggles bot_enabled."""
    assert mock_account_manager.bot_enabled is True

    resp_pause = cc_client.post("/api/accounts/toggle-bot", params={"enabled": False})
    assert resp_pause.status_code == 200
    assert resp_pause.json()["bot_enabled"] is False
    assert mock_account_manager.bot_enabled is False

    resp_resume = cc_client.post("/api/accounts/toggle-bot", params={"enabled": True})
    assert resp_resume.status_code == 200
    assert resp_resume.json()["bot_enabled"] is True
    assert mock_account_manager.bot_enabled is True


def test_close_all_positions_for_single_account(cc_client, mock_account_manager):
    """Verify POST /api/accounts/{id}/close-all invokes close_all on account session."""
    ctx1 = mock_account_manager.get_account("acc_fleet_1")
    ctx1.session._connected = True
    # Place a simulated dry-run buy order
    fill = ctx1.session.buy(0.1, sl=1990.0, tp=2010.0, symbol="XAUUSD")
    assert fill.success is True
    assert len(ctx1.session._positions) == 1

    resp = cc_client.post("/api/accounts/acc_fleet_1/close-all", params={"reason": "Test Close"})
    assert resp.status_code == 200
    assert resp.json()["closed_positions_count"] == 1
    assert len(ctx1.session._positions) == 0


def test_dash_app_mounted_router(dash_client):
    """Verify that multi-account router is also mounted and operational on dash_app."""
    resp = dash_client.get("/api/accounts")
    assert resp.status_code == 200
    assert len(resp.json()) == 3
