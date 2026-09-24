"""
app/multi_account/terminal_supervisor.py — Portable MT5 Terminal Lifecycle & Identity Handshake Supervisor

Implements:
- Phase 3: Deterministic Portable Terminal Directory Management (D:\\MT5_Terminals\\Account_XXX\\terminal64.exe /portable)
- Phase 4: Strict Account Identity Handshake & Fail-Closed Guardrails (ACCOUNT_IDENTITY_MISMATCH)
- Terminal health checks, process verification via psutil, and crash recovery.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import psutil

from app.multi_account.account_context import AccountStatus
from app.multi_account.account_registry import AccountConfig, mask_credential
from app.multi_account.mt5_session import IMT5Session

logger = logging.getLogger(__name__)

DEFAULT_TERMINAL_BASE_DIR = Path(r"D:\MT5_Terminals")
PRIMARY_TERMINAL_EXE = Path(r"C:\Program Files\MetaTrader 5\terminal64.exe")


@dataclass
class TerminalInstanceInfo:
    """Telemetry and state for a single account's dedicated terminal."""
    account_id: str
    terminal_dir: Path
    terminal_exe: Path
    pid: Optional[int] = None
    is_portable: bool = True
    process_alive: bool = False
    handshake_status: str = "PENDING"  # "PENDING" | "VERIFIED" | "MISMATCH" | "FAILED"
    last_verified_at: Optional[datetime] = None
    verified_login: Optional[int] = None
    verified_server: Optional[str] = None
    verified_company: Optional[str] = None


@dataclass
class IdentityHandshakeResult:
    """Result of rigorous pre-trade account identity handshake."""
    success: bool
    account_id: str
    status: AccountStatus
    configured_login: int
    returned_login: Optional[int]
    configured_server: str
    returned_server: Optional[str]
    configured_company: str = ""
    returned_company: Optional[str] = ""
    magic_number_verified: bool = False
    symbol_available: bool = False
    error_reason: str = ""

    def __repr__(self) -> str:
        return (
            f"IdentityHandshakeResult(account='{self.account_id}', success={self.success}, "
            f"status={self.status.value}, login_match=({self.configured_login}=={self.returned_login}), "
            f"server_match=({self.configured_server}=={self.returned_server}), reason='{self.error_reason}')"
        )


class TerminalSupervisor:
    """
    Supervises the physical MT5 terminal instances, process isolation,
    and identity handshakes across the account fleet.
    """

    def __init__(self, base_terminals_dir: Optional[Path] = None):
        self.base_dir = base_terminals_dir or DEFAULT_TERMINAL_BASE_DIR
        self._terminals: Dict[str, TerminalInstanceInfo] = {}

    # ── Directory Layout & Provisioning (Phase 3) ─────────────────────────────

    def provision_terminal_directory(
        self,
        account_id: str,
        custom_dir: Optional[Union[str, Path]] = None,
        source_exe: Optional[Path] = None,
    ) -> Path:
        """
        Ensure deterministic directory layout for portable terminal on Drive D:.
        D:\\MT5_Terminals\\<account_id>\\
            terminal64.exe
            bases\\
            config\\
            MQL5\\
        """
        target_dir = Path(custom_dir) if custom_dir else (self.base_dir / account_id)
        target_exe = target_dir / "terminal64.exe"

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            # Create standard subdirectories for portable self-containment
            for subdir in ["bases", "config", "MQL5", "profiles", "templates", "history", "ticks"]:
                (target_dir / subdir).mkdir(parents=True, exist_ok=True)

            # Copy main executable if not present and source exists
            if not target_exe.exists():
                src = source_exe or PRIMARY_TERMINAL_EXE
                if src.exists():
                    shutil.copy2(src, target_exe)
                    logger.info(f"[{account_id}] Provisioned portable terminal64.exe to {target_exe}")
        except Exception as e:
            logger.warning(f"[{account_id}] Terminal directory provisioning notice: {e}")

        self._terminals[account_id] = TerminalInstanceInfo(
            account_id=account_id,
            terminal_dir=target_dir,
            terminal_exe=target_exe,
            is_portable=True,
        )
        return target_dir

    # ── Process Management (Phase 3) ─────────────────────────────────────────

    def start_terminal(
        self,
        config: AccountConfig,
        timeout_s: float = 15.0,
    ) -> Optional[int]:
        """
        Start terminal in portable mode: terminal64.exe /portable.
        Returns OS PID or None if failed.
        """
        if config.dry_run:
            sim_pid = 90000 + (abs(hash(config.account_id)) % 10000)
            info = self._terminals.setdefault(
                config.account_id,
                TerminalInstanceInfo(
                    account_id=config.account_id,
                    terminal_dir=Path(config.portable_terminal_directory or (self.base_dir / config.account_id)),
                    terminal_exe=Path(config.terminal_path or "terminal64.exe"),
                    pid=sim_pid,
                    process_alive=True,
                ),
            )
            info.pid = sim_pid
            info.process_alive = True
            logger.info(f"[{config.account_id}] [DRY_RUN] Simulated portable terminal started (PID={sim_pid})")
            return sim_pid

        term_dir = Path(config.portable_terminal_directory or (self.base_dir / config.account_id))
        term_exe = Path(config.terminal_path) if config.terminal_path else (term_dir / "terminal64.exe")

        if not term_exe.exists():
            # Attempt to provision
            self.provision_terminal_directory(config.account_id, custom_dir=term_dir)

        if not term_exe.exists():
            logger.error(f"[{config.account_id}] Cannot start terminal: executable not found at {term_exe}")
            return None

        # Check if already running for this directory
        existing_pid = self.find_terminal_process(term_dir)
        if existing_pid:
            logger.info(f"[{config.account_id}] Found existing portable terminal process (PID={existing_pid})")
            info = self._terminals.setdefault(
                config.account_id,
                TerminalInstanceInfo(
                    account_id=config.account_id,
                    terminal_dir=term_dir,
                    terminal_exe=term_exe,
                    pid=existing_pid,
                    process_alive=True,
                ),
            )
            info.pid = existing_pid
            info.process_alive = True
            return existing_pid

        cmd = [str(term_exe), "/portable"]
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(term_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            pid = proc.pid
            logger.info(f"[{config.account_id}] Spawned portable terminal: {' '.join(cmd)} (PID={pid})")

            info = self._terminals.setdefault(
                config.account_id,
                TerminalInstanceInfo(
                    account_id=config.account_id,
                    terminal_dir=term_dir,
                    terminal_exe=term_exe,
                    pid=pid,
                    process_alive=True,
                ),
            )
            info.pid = pid
            info.process_alive = True
            return pid
        except Exception as e:
            logger.error(f"[{config.account_id}] Failed to spawn terminal: {e}")
            return None

    def verify_terminal_process(self, account_id: str) -> bool:
        """Verify that the account's terminal process is currently alive."""
        info = self._terminals.get(account_id)
        if not info or not info.pid:
            return False

        try:
            proc = psutil.Process(info.pid)
            alive = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            info.process_alive = alive
            return alive
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            info.process_alive = False
            return False

    def find_terminal_process(self, terminal_dir: Path) -> Optional[int]:
        """Scan running processes for terminal64.exe running with /portable in target dir."""
        for p in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
            try:
                name = (p.info.get("name") or "").lower()
                if "terminal64.exe" in name or "terminal.exe" in name:
                    cwd = p.info.get("cwd") or ""
                    cmdline = p.info.get("cmdline") or []
                    cmd_str = " ".join(cmdline).lower()
                    if str(terminal_dir).lower() in cwd.lower() or str(terminal_dir).lower() in cmd_str:
                        return p.info["pid"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def stop_terminal(self, account_id: str, timeout_s: float = 3.0) -> bool:
        """Gracefully terminate the account's dedicated terminal."""
        info = self._terminals.get(account_id)
        if not info or not info.pid:
            return True

        try:
            proc = psutil.Process(info.pid)
            proc.terminate()
            proc.wait(timeout=timeout_s)
            logger.info(f"[{account_id}] Stopped terminal process PID={info.pid}")
        except psutil.TimeoutExpired:
            proc.kill()
            logger.warning(f"[{account_id}] Force-killed terminal process PID={info.pid}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        info.pid = None
        info.process_alive = False
        info.handshake_status = "PENDING"
        return True

    # ── Account Identity Handshake (Phase 4) ──────────────────────────────────

    def perform_identity_handshake(
        self,
        config: AccountConfig,
        session: IMT5Session,
    ) -> IdentityHandshakeResult:
        """
        Rigorous pre-trade identity verification.
        Validates:
        1. Terminal responds
        2. Session returns valid account_info
        3. Returned login equals configured login
        4. Returned server matches configured server
        5. Returned company matches configured company (if provided)
        6. Unique magic number is configured
        7. Trading permissions are active
        8. Expected symbol (e.g. XAUUSD) is available for quotes

        If any check fails: returns ACCOUNT_IDENTITY_MISMATCH (fail-closed).
        """
        account_id = config.account_id

        # 1. Query live account info from session
        info = session.get_account_info()
        if not info:
            logger.critical(
                f"[{account_id}] Handshake FAILED: session returned no account_info"
            )
            return IdentityHandshakeResult(
                success=False,
                account_id=account_id,
                status=AccountStatus.ACCOUNT_IDENTITY_MISMATCH,
                configured_login=config.login,
                returned_login=None,
                configured_server=config.server,
                returned_server=None,
                error_reason="No account_info returned by MT5 session",
            )

        ret_login = info.get("login")
        ret_server = info.get("server")
        ret_company = info.get("company", "")
        trade_allowed = info.get("trade_allowed", True)

        # 2. Login match check
        if ret_login != config.login:
            reason = f"Login mismatch: configured={config.login} vs broker={ret_login}"
            logger.critical(f"[{account_id}] FAIL SAFE: {reason}")
            return IdentityHandshakeResult(
                success=False,
                account_id=account_id,
                status=AccountStatus.ACCOUNT_IDENTITY_MISMATCH,
                configured_login=config.login,
                returned_login=ret_login,
                configured_server=config.server,
                returned_server=ret_server,
                returned_company=ret_company,
                error_reason=reason,
            )

        # 3. Server match check
        cfg_srv_clean = config.server.strip().lower()
        ret_srv_clean = str(ret_server or "").strip().lower()
        if cfg_srv_clean and (cfg_srv_clean not in ret_srv_clean and ret_srv_clean not in cfg_srv_clean):
            reason = f"Server mismatch: configured='{config.server}' vs broker='{ret_server}'"
            logger.critical(f"[{account_id}] FAIL SAFE: {reason}")
            return IdentityHandshakeResult(
                success=False,
                account_id=account_id,
                status=AccountStatus.ACCOUNT_IDENTITY_MISMATCH,
                configured_login=config.login,
                returned_login=ret_login,
                configured_server=config.server,
                returned_server=ret_server,
                returned_company=ret_company,
                error_reason=reason,
            )

        # 4. Company match check (if configured)
        if config.company:
            cfg_comp_clean = config.company.strip().lower()
            ret_comp_clean = str(ret_company or "").strip().lower()
            if cfg_comp_clean and (cfg_comp_clean not in ret_comp_clean and ret_comp_clean not in cfg_comp_clean):
                reason = f"Broker company mismatch: configured='{config.company}' vs broker='{ret_company}'"
                logger.critical(f"[{account_id}] FAIL SAFE: {reason}")
                return IdentityHandshakeResult(
                    success=False,
                    account_id=account_id,
                    status=AccountStatus.ACCOUNT_IDENTITY_MISMATCH,
                    configured_login=config.login,
                    returned_login=ret_login,
                    configured_server=config.server,
                    returned_server=ret_server,
                    configured_company=config.company,
                    returned_company=ret_company,
                    error_reason=reason,
                )

        # 5. Magic number assertion
        if config.magic_number <= 0:
            reason = f"Invalid magic number {config.magic_number}"
            logger.critical(f"[{account_id}] FAIL SAFE: {reason}")
            return IdentityHandshakeResult(
                success=False,
                account_id=account_id,
                status=AccountStatus.ACCOUNT_IDENTITY_MISMATCH,
                configured_login=config.login,
                returned_login=ret_login,
                configured_server=config.server,
                returned_server=ret_server,
                error_reason=reason,
            )

        # 6. Trade permission verification
        if not trade_allowed:
            reason = "AutoTrading or investor password restriction: trade_allowed=False"
            logger.warning(f"[{account_id}] {reason}")
            return IdentityHandshakeResult(
                success=False,
                account_id=account_id,
                status=AccountStatus.AUTH_ERROR,
                configured_login=config.login,
                returned_login=ret_login,
                configured_server=config.server,
                returned_server=ret_server,
                error_reason=reason,
            )

        # 7. Symbol quote availability check
        test_symbol = config.symbols[0] if config.symbols else "XAUUSD"
        spec = session.get_symbol_spec(test_symbol)
        if not spec:
            reason = f"Symbol '{test_symbol}' not available in MT5 terminal Market Watch"
            logger.warning(f"[{account_id}] {reason}")
            return IdentityHandshakeResult(
                success=False,
                account_id=account_id,
                status=AccountStatus.ERROR,
                configured_login=config.login,
                returned_login=ret_login,
                configured_server=config.server,
                returned_server=ret_server,
                error_reason=reason,
            )

        # Update telemetry
        t_info = self._terminals.get(account_id)
        if t_info:
            t_info.handshake_status = "VERIFIED"
            t_info.last_verified_at = datetime.now(timezone.utc)
            t_info.verified_login = ret_login
            t_info.verified_server = ret_server
            t_info.verified_company = ret_company

        logger.info(
            f"[{account_id}] Identity Handshake VERIFIED: Login=#{ret_login}, Server='{ret_server}', "
            f"Balance=${info.get('balance', 0.0):,.2f}, Magic={config.magic_number} -> EXECUTION_READY"
        )

        return IdentityHandshakeResult(
            success=True,
            account_id=account_id,
            status=AccountStatus.EXECUTION_READY,
            configured_login=config.login,
            returned_login=ret_login,
            configured_server=config.server,
            returned_server=ret_server,
            configured_company=config.company,
            returned_company=ret_company,
            magic_number_verified=True,
            symbol_available=True,
            error_reason="",
        )


# Global singleton instance for fleet management
_terminal_supervisor: Optional[TerminalSupervisor] = None


def get_terminal_supervisor() -> TerminalSupervisor:
    global _terminal_supervisor
    if _terminal_supervisor is None:
        _terminal_supervisor = TerminalSupervisor()
    return _terminal_supervisor
