"""
tests/test_terminal_supervisor.py — Terminal Supervisor & Account Identity Handshake Test Suite

Validates Phase 3 & Phase 4:
- Deterministic portable directory provisioning
- Process lifecycle management
- Strict pre-trade identity handshake
- Fail-closed guardrails for login, server, company, and magic number mismatches
"""

import pytest
from pathlib import Path
from app.multi_account.account_registry import AccountConfig
from app.multi_account.account_context import AccountStatus
from app.multi_account.mt5_session import IMT5Session, MT5DirectSession
from app.multi_account.terminal_supervisor import (
    TerminalSupervisor,
    IdentityHandshakeResult,
    get_terminal_supervisor,
)


class MockSessionWithAccountInfo(IMT5Session):
    """Configurable mock session to simulate various broker handshake responses."""

    def __init__(self, account_info_dict=None, symbol_spec_dict="DEFAULT"):
        self._info = account_info_dict
        if symbol_spec_dict == "DEFAULT":
            self._spec = {"digits": 2, "point": 0.01}
        else:
            self._spec = symbol_spec_dict
        self._connected = True

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_account_info(self):
        return self._info

    def get_positions(self, symbol=None):
        return []

    def get_symbol_spec(self, symbol: str):
        return self._spec

    def get_tick(self, symbol: str):
        return {"bid": 2000.0, "ask": 2000.20}

    def buy(self, volume, sl, tp, comment="", symbol="XAUUSD"):
        raise NotImplementedError

    def sell(self, volume, sl, tp, comment="", symbol="XAUUSD"):
        raise NotImplementedError

    def modify(self, ticket, sl, tp, symbol="XAUUSD"):
        raise NotImplementedError

    def close(self, ticket, volume=None, reason="manual", symbol=None):
        raise NotImplementedError

    def close_all(self, reason="emergency"):
        return 0


def test_terminal_provisioning(tmp_path):
    """Verify deterministic portable terminal directory layout creation."""
    supervisor = TerminalSupervisor(base_terminals_dir=tmp_path)
    term_dir = supervisor.provision_terminal_directory(account_id="test_acc_001")

    assert term_dir.exists()
    assert (term_dir / "bases").exists()
    assert (term_dir / "config").exists()
    assert (term_dir / "MQL5").exists()
    assert (term_dir / "history").exists()
    assert (term_dir / "ticks").exists()


def test_handshake_success():
    """Verify successful identity handshake transitions to EXECUTION_READY."""
    supervisor = TerminalSupervisor()
    cfg = AccountConfig(
        account_id="acc_valid",
        login=919205,
        server="BlackBullMarkets-Demo",
        company="Black Bull Group Limited",
        magic_number=20250701,
        dry_run=True,
    )
    mock_session = MockSessionWithAccountInfo(
        account_info_dict={
            "login": 919205,
            "server": "BlackBullMarkets-Demo",
            "company": "Black Bull Group Limited",
            "balance": 10000.0,
            "trade_allowed": True,
        }
    )

    result = supervisor.perform_identity_handshake(cfg, mock_session)
    assert result.success is True
    assert result.status == AccountStatus.EXECUTION_READY
    assert result.magic_number_verified is True
    assert result.error_reason == ""


def test_handshake_login_mismatch_fails_closed():
    """Verify login mismatch immediately blocks execution with ACCOUNT_IDENTITY_MISMATCH."""
    supervisor = TerminalSupervisor()
    cfg = AccountConfig(
        account_id="acc_mismatch_login",
        login=919205,
        server="BlackBullMarkets-Demo",
        magic_number=20250701,
    )
    # Broker returns login 888888 instead of 919205
    mock_session = MockSessionWithAccountInfo(
        account_info_dict={
            "login": 888888,
            "server": "BlackBullMarkets-Demo",
            "company": "Black Bull Group Limited",
            "balance": 10000.0,
            "trade_allowed": True,
        }
    )

    result = supervisor.perform_identity_handshake(cfg, mock_session)
    assert result.success is False
    assert result.status == AccountStatus.ACCOUNT_IDENTITY_MISMATCH
    assert "Login mismatch" in result.error_reason
    assert "919205" in result.error_reason
    assert "888888" in result.error_reason


def test_handshake_server_mismatch_fails_closed():
    """Verify server mismatch blocks execution with ACCOUNT_IDENTITY_MISMATCH."""
    supervisor = TerminalSupervisor()
    cfg = AccountConfig(
        account_id="acc_mismatch_server",
        login=919205,
        server="BlackBullMarkets-Demo",
        magic_number=20250701,
    )
    # Broker returns different server
    mock_session = MockSessionWithAccountInfo(
        account_info_dict={
            "login": 919205,
            "server": "Vantage-Demo",
            "company": "Vantage International",
            "balance": 10000.0,
            "trade_allowed": True,
        }
    )

    result = supervisor.perform_identity_handshake(cfg, mock_session)
    assert result.success is False
    assert result.status == AccountStatus.ACCOUNT_IDENTITY_MISMATCH
    assert "Server mismatch" in result.error_reason


def test_handshake_company_mismatch_fails_closed():
    """Verify broker company mismatch blocks execution."""
    supervisor = TerminalSupervisor()
    cfg = AccountConfig(
        account_id="acc_mismatch_company",
        login=919205,
        server="Demo-Server",
        company="Black Bull Group Limited",
        magic_number=20250701,
    )
    mock_session = MockSessionWithAccountInfo(
        account_info_dict={
            "login": 919205,
            "server": "Demo-Server",
            "company": "Malicious Broker Ltd",
            "balance": 10000.0,
            "trade_allowed": True,
        }
    )

    result = supervisor.perform_identity_handshake(cfg, mock_session)
    assert result.success is False
    assert result.status == AccountStatus.ACCOUNT_IDENTITY_MISMATCH
    assert "Broker company mismatch" in result.error_reason


def test_handshake_read_only_investor_password_blocks_trading():
    """Verify non-trading/investor password triggers AUTH_ERROR."""
    supervisor = TerminalSupervisor()
    cfg = AccountConfig(
        account_id="acc_investor_read_only",
        login=919205,
        server="Demo-Server",
        magic_number=20250701,
    )
    mock_session = MockSessionWithAccountInfo(
        account_info_dict={
            "login": 919205,
            "server": "Demo-Server",
            "company": "",
            "balance": 10000.0,
            "trade_allowed": False,  # Investor password
        }
    )

    result = supervisor.perform_identity_handshake(cfg, mock_session)
    assert result.success is False
    assert result.status == AccountStatus.AUTH_ERROR
    assert "trade_allowed=False" in result.error_reason


def test_handshake_missing_symbol_quotes_fails():
    """Verify missing quotes for target symbol fails handshake."""
    supervisor = TerminalSupervisor()
    cfg = AccountConfig(
        account_id="acc_no_symbol",
        login=919205,
        server="Demo-Server",
        magic_number=20250701,
        symbols=["BTCUSD"],
    )
    mock_session = MockSessionWithAccountInfo(
        account_info_dict={
            "login": 919205,
            "server": "Demo-Server",
            "trade_allowed": True,
        },
        symbol_spec_dict=None,  # Symbol not found in Market Watch
    )

    result = supervisor.perform_identity_handshake(cfg, mock_session)
    assert result.success is False
    assert result.status == AccountStatus.ERROR
    assert "not available in MT5 terminal" in result.error_reason
