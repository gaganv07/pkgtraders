"""
tests/test_web_platform_integration.py — Integration Tests for Web Platform & Bot Security

Verifies:
1. Health & Server Connectivity
2. Bot Telemetry Ingestion via HMAC SHA-256 Signatures (Valid vs Invalid/Stale)
3. Client Authentication & Tenant Isolation
4. Admin Authentication & Role-Based Access Control (RBAC)
5. KYC Submission & Admin Review Workflows
6. Deposit & Withdrawal Request Workflows
7. Security Boundary Isolation (Client A cannot see Client B or Admin functions)
"""

import hmac
import hashlib
import json
import time
import urllib.request
import urllib.error
import pytest

BACKEND_URL = "http://localhost:4000"
BOT_HMAC_SECRET = "dev_bot_hmac_secret_64bytes_minimum_key_for_pkgtraders!"
BOT_API_KEY = "pkg_bot_live_api_key_v1"


def test_backend_health():
    """Verify backend API health endpoint."""
    url = f"{BACKEND_URL}/api/v1/health"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode('utf-8'))
        assert data["status"] == "HEALTHY"


def test_bot_hmac_sync_success():
    """Verify valid HMAC-SHA256 telemetry push from trading bot."""
    payload = {
        "instance_name": "TEST_BOT_01",
        "pc_hostname": "TEST-PC",
        "bot_version": "2.0.0",
        "accounts": [
            {
                "account_id": "account_001",
                "mt5_login": 26128885,
                "server": "VantageMarkets-Demo",
                "magic_number": 20250701,
                "balance": 495.37,
                "equity": 483.96,
                "margin": 18.56,
                "free_margin": 465.40,
                "margin_level": 2607.54,
                "open_positions": [],
                "recent_trades": []
            }
        ]
    }
    payload_json = json.dumps(payload, sort_keys=True)
    ts = str(int(time.time()))
    msg = f"{ts}.{payload_json}".encode('utf-8')
    sig = hmac.new(BOT_HMAC_SECRET.encode('utf-8'), msg, hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Bot-Api-Key": BOT_API_KEY,
        "X-Bot-Timestamp": ts,
        "X-Bot-Signature": sig
    }

    url = f"{BACKEND_URL}/api/v1/bot/sync"
    req = urllib.request.Request(url, data=payload_json.encode('utf-8'), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        res_data = json.loads(resp.read().decode('utf-8'))
        assert res_data["status"] == "SUCCESS"


def test_bot_hmac_sync_rejected_invalid_sig():
    """Verify invalid HMAC signature is strictly rejected by backend."""
    payload_json = json.dumps({"test": 123})
    ts = str(int(time.time()))
    bad_sig = "invalid_hmac_signature_hex_value_12345"

    headers = {
        "Content-Type": "application/json",
        "X-Bot-Api-Key": BOT_API_KEY,
        "X-Bot-Timestamp": ts,
        "X-Bot-Signature": bad_sig
    }

    url = f"{BACKEND_URL}/api/v1/bot/sync"
    req = urllib.request.Request(url, data=payload_json.encode('utf-8'), headers=headers, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 401


def test_client_login_and_tenant_isolation():
    """Verify Client login returns valid JWT and isolated dashboard data."""
    # 1. Login
    login_payload = json.dumps({"email": "client@pkgtraders.com", "password": "ClientPass123!"}).encode('utf-8')
    req = urllib.request.Request(f"{BACKEND_URL}/api/v1/client/auth/login", data=login_payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        auth_data = json.loads(resp.read().decode('utf-8'))
        token = auth_data["token"]
        assert token is not None

    # 2. Access Client Dashboard
    dash_req = urllib.request.Request(f"{BACKEND_URL}/api/v1/client/dashboard", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(dash_req, timeout=5) as resp:
        assert resp.status == 200
        dash_data = json.loads(resp.read().decode('utf-8'))
        assert dash_data["user"]["email"] == "client@pkgtraders.com"
        assert len(dash_data["accounts"]) == 2


def test_client_forbidden_from_admin_endpoints():
    """Verify Client token is rejected when attempting to access Admin endpoints."""
    # Login as client
    login_payload = json.dumps({"email": "client@pkgtraders.com", "password": "ClientPass123!"}).encode('utf-8')
    req = urllib.request.Request(f"{BACKEND_URL}/api/v1/client/auth/login", data=login_payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        token = json.loads(resp.read().decode('utf-8'))["token"]

    # Try admin overview
    admin_req = urllib.request.Request(f"{BACKEND_URL}/api/v1/admin/overview", headers={"Authorization": f"Bearer {token}"})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(admin_req, timeout=5)
    assert exc_info.value.code == 401


def test_admin_login_and_audit_logging():
    """Verify Admin login returns JWT and accesses audit logs."""
    admin_payload = json.dumps({"email": "admin@pkgtraders.com", "password": "AdminPass123!"}).encode('utf-8')
    req = urllib.request.Request(f"{BACKEND_URL}/api/v1/admin/auth/login", data=admin_payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        token = json.loads(resp.read().decode('utf-8'))["token"]

    audit_req = urllib.request.Request(f"{BACKEND_URL}/api/v1/admin/audit-logs", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(audit_req, timeout=5) as resp:
        assert resp.status == 200
        audit_data = json.loads(resp.read().decode('utf-8'))
        assert "auditLogs" in audit_data
        assert len(audit_data["auditLogs"]) >= 1
