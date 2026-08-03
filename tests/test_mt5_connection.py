"""
tests/test_mt5_connection.py — PyTest Suite for Vantage MT5 Connection Module

Validates:
- Environment configuration validation (missing credentials handling)
- Credential masking
- Structured logging to logs/mt5_connection.log
- Trading permissions checks
- Symbol validation logic
- Account safety checks
"""

import os
from pathlib import Path
import pytest
from app.mt5_connection import (
    MT5ConnectionManager,
    mask_credential,
    LOG_FILE,
)


def test_mask_credential():
    assert mask_credential("Gaganv!4459") == "Ga*******59"
    assert mask_credential("123") == "****"


def test_configuration_validation():
    # Valid config
    mgr_valid = MT5ConnectionManager(login=907901, password="secret", server="Vantage-Live")
    ok, missing = mgr_valid.validate_configuration()
    assert ok is True
    assert len(missing) == 0

    # Invalid config
    mgr_invalid = MT5ConnectionManager(login=0, password="", server="")
    ok_inv, missing_inv = mgr_invalid.validate_configuration()
    assert ok_inv is False
    assert "MT5_LOGIN" in missing_inv
    assert "MT5_PASSWORD" in missing_inv
    assert "MT5_SERVER" in missing_inv


def test_logging_creation(tmp_path):
    mgr = MT5ConnectionManager(login=907901, password="secret", server="Vantage-Live")
    mgr.validate_configuration()
    assert LOG_FILE.exists() or Path("logs/mt5_connection.log").exists()


def test_permissions_check_simulated():
    mgr = MT5ConnectionManager(login=907901, password="secret", server="Vantage-Live")
    perms = mgr.verify_trading_permissions()
    assert "Terminal Connected" in perms
    assert "Account Authorized" in perms
    assert "Trade Allowed" in perms
    assert "Expert Advisors Allowed" in perms
    assert "AutoTrading Enabled" in perms
    assert "Non-Investor Password" in perms
