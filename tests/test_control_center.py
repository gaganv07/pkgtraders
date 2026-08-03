"""
tests/test_control_center.py — PyTest Suite for Legacy Asset Partners Control Center

Validates:
- Read-only REST API endpoints (/api/v2/overview, /api/v2/live_trades, /api/v2/trade_history, /api/v2/symbol_analytics, /api/v2/health)
- Excel & PDF Exporters (/api/v2/export/excel, /api/v2/export/pdf)
"""

import pytest
from fastapi.testclient import TestClient
from dashboard.control_center import app, _read_trade_journal


@pytest.fixture
def client():
    return TestClient(app)


def test_overview_endpoint(client):
    response = client.get("/api/v2/overview")
    assert response.status_code == 200
    data = response.json()
    assert "account" in data
    assert "connection" in data
    assert "risk" in data
    assert "system" in data


def test_live_trades_endpoint(client):
    response = client.get("/api/v2/live_trades")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_trade_history_endpoint(client):
    response = client.get("/api/v2/trade_history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_symbol_analytics_endpoint(client):
    response = client.get("/api/v2/symbol_analytics")
    assert response.status_code == 200
    data = response.json()
    assert "BTCUSD" in data
    assert "XAUUSD" in data
    assert "EURUSD" in data


def test_health_endpoint(client):
    response = client.get("/api/v2/health")
    assert response.status_code == 200
    data = response.json()
    assert "system" in data


def test_excel_export_endpoint(client):
    response = client.get("/api/v2/export/excel")
    assert response.status_code == 200
    assert "sheet" in response.headers["content-type"] or "csv" in response.headers["content-type"] or "application" in response.headers["content-type"]


def test_pdf_export_endpoint(client):
    response = client.get("/api/v2/export/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
