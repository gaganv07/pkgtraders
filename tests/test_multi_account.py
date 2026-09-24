"""
tests/test_multi_account.py — Multi-Account Configuration & Registry Tests
"""

import os
import pytest
from app.multi_account.account_registry import AccountConfig, AccountRegistry, mask_credential


def test_mask_credential():
    assert mask_credential("") == ""
    assert mask_credential("123") == "****"
    assert mask_credential("secretpassword") == "se**********rd"


def test_account_config_valid():
    cfg = AccountConfig(
        account_id="acc_001",
        login=10001,
        server="TestServer",
        password="MySecretPassword123",
        magic_number=20250701,
        risk_per_trade_pct=1.5,
    )
    assert cfg.account_id == "acc_001"
    assert cfg.login == 10001
    assert cfg.resolve_password() == "MySecretPassword123"

    # Security check: Password must NEVER appear in __repr__ or to_safe_dict
    rep = repr(cfg)
    assert "MySecretPassword123" not in rep
    assert "****" in rep or "My**********23" in rep

    safe_dict = cfg.to_safe_dict()
    assert safe_dict["password"] != "MySecretPassword123"
    assert "****" in safe_dict["password"] or "My**********23" in safe_dict["password"]


def test_account_config_password_env_var(monkeypatch):
    monkeypatch.setenv("TEST_ACC_PASSWORD", "EnvResolvedPass456")
    cfg = AccountConfig(
        account_id="acc_env",
        login=10002,
        password_env_var="TEST_ACC_PASSWORD",
        magic_number=20250702,
    )
    assert cfg.resolve_password() == "EnvResolvedPass456"


def test_registry_registration_and_get():
    reg = AccountRegistry()
    cfg1 = AccountConfig(account_id="acc_1", login=10001, password="pwd", magic_number=20250701)
    cfg2 = AccountConfig(account_id="acc_2", login=10002, password="pwd", magic_number=20250702)

    reg.register(cfg1)
    reg.register(cfg2)

    assert len(reg.get_all()) == 2
    assert reg.get("acc_1") is cfg1
    assert reg.get("acc_2") is cfg2
    assert reg.get_by_magic(20250701) is cfg1
    assert reg.get_by_magic(20250702) is cfg2


def test_registry_rejects_duplicate_account_id():
    reg = AccountRegistry()
    cfg1 = AccountConfig(account_id="acc_dup", login=10001, password="pwd", magic_number=20250701)
    cfg2 = AccountConfig(account_id="acc_dup", login=10002, password="pwd", magic_number=20250702)

    reg.register(cfg1)
    with pytest.raises(ValueError, match="Duplicate account_id"):
        reg.register(cfg2)


def test_registry_rejects_duplicate_magic_number():
    reg = AccountRegistry()
    cfg1 = AccountConfig(account_id="acc_1", login=10001, password="pwd", magic_number=20250701)
    cfg2 = AccountConfig(account_id="acc_2", login=10002, password="pwd", magic_number=20250701)

    reg.register(cfg1)
    with pytest.raises(ValueError, match="Duplicate magic_number"):
        reg.register(cfg2)


def test_registry_rejects_invalid_login():
    reg = AccountRegistry()
    cfg = AccountConfig(account_id="acc_invalid", login=0, password="pwd", magic_number=20250701)
    with pytest.raises(ValueError, match="Invalid MT5 login"):
        reg.register(cfg)


def test_registry_rejects_empty_id():
    reg = AccountRegistry()
    cfg = AccountConfig(account_id="", login=10001, password="pwd", magic_number=20250701)
    with pytest.raises(ValueError, match="account_id cannot be empty"):
        reg.register(cfg)


def test_registry_load_from_dict_list():
    reg = AccountRegistry()
    items = [
        {"account_id": "acc_a", "login": 101, "password": "p1", "magic_number": 1001, "enabled": True},
        {"account_id": "acc_b", "login": 102, "password": "p2", "magic_number": 1002, "enabled": False},
    ]
    count = reg.load_from_dict_list(items)
    assert count == 2
    assert len(reg.get_all()) == 2
    assert len(reg.get_enabled()) == 1
    assert reg.get_enabled()[0].account_id == "acc_a"


def test_registry_backward_compatibility_load_from_env():
    reg = AccountRegistry()
    default_cfg = reg.load_default_from_env()
    assert default_cfg is not None
    assert default_cfg.account_id == "account_default"
    assert reg.get("account_default") is default_cfg
    assert default_cfg.magic_number > 0
