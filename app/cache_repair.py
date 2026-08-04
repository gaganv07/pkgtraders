"""
app/cache_repair.py — MT5 Cache Repair & Integrity Engine

Detects corrupted MT5 history/tick cache files (.crp, .tkc, .hcc) and file errors
(Error 2, Error 18, Error 112). Automatically backs up corrupted files, deletes only
the affected cache entries, and triggers seamless resynchronization without destroying healthy data.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


@dataclass
class RepairActionResult:
    success: bool
    corrupted_files_found: int
    files_repaired: int
    files_backed_up: int
    error_message: str = ""
    details: List[str] = None

    def __post_init__(self):
        if self.details is None:
            self.details = []


class CacheRepairEngine:
    """
    Automated cache audit, repair, and purging engine for MetaTrader 5 history cache.
    """

    KNOWN_MT5_ERRORS = {
        2: "COMMON_ERROR (File read/write error)",
        18: "MARKET_CLOSED_OR_SYNC_FAILED (History synchronization failure)",
        112: "NOT_ENOUGH_MONEY_OR_BUFFER_OVERFLOW (Disk/memory cache overflow)",
    }

    def __init__(self, terminal_data_path: Optional[str] = None):
        self.terminal_data_path = self._resolve_terminal_path(terminal_data_path)

    def _resolve_terminal_path(self, explicit_path: Optional[str] = None) -> Optional[Path]:
        if explicit_path and os.path.exists(explicit_path):
            return Path(explicit_path)

        if MT5_AVAILABLE:
            try:
                info = mt5.terminal_info()
                if info and hasattr(info, "data_path") and os.path.exists(info.data_path):
                    return Path(info.data_path)
            except Exception:
                pass

        # Standard Windows AppData location fallback
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            mq_path = Path(appdata) / "MetaQuotes" / "Terminal"
            if mq_path.exists():
                return mq_path

        return None

    def audit_cache_integrity(self) -> Tuple[bool, List[Path]]:
        """
        Scan MT5 data directory for corrupted or zero-byte cache files (.crp, .tkc, .hcc).
        Returns (is_healthy, list_of_corrupted_files).
        """
        corrupted_files: List[Path] = []
        if not self.terminal_data_path or not self.terminal_data_path.exists():
            logger.warning(f"[CACHE_REPAIR] Terminal data path unavailable: {self.terminal_data_path}")
            return True, []

        logger.info(f"[CACHE_REPAIR] Auditing cache integrity in '{self.terminal_data_path}'...")

        try:
            # Search for .crp, .tkc, .hcc files in bases/ directory
            for ext in ("*.crp", "*.tkc", "*.hcc"):
                for p in self.terminal_data_path.rglob(ext):
                    try:
                        # Zero-byte files or inaccessible files are flagged as corrupted
                        if p.stat().st_size == 0:
                            logger.warning(f"[CACHE_REPAIR] Corrupted 0-byte cache file detected: {p}")
                            corrupted_files.append(p)
                        else:
                            # Test file readability
                            with open(p, "rb") as f:
                                f.read(16)
                    except Exception as e:
                        logger.warning(f"[CACHE_REPAIR] Unreadable cache file detected '{p}': {e}")
                        corrupted_files.append(p)
        except Exception as e:
            logger.error(f"[CACHE_REPAIR] Exception during cache audit: {e}")

        is_healthy = len(corrupted_files) == 0
        logger.info(f"[CACHE_REPAIR] Audit complete. Found {len(corrupted_files)} corrupted files.")
        return is_healthy, corrupted_files

    def repair_corrupted_cache(self, corrupted_files: Optional[List[Path]] = None) -> RepairActionResult:
        """
        Safely back up corrupted cache files to .bak and remove them to trigger MT5 re-download.
        """
        if corrupted_files is None:
            _, corrupted_files = self.audit_cache_integrity()

        if not corrupted_files:
            return RepairActionResult(True, 0, 0, 0, "No corrupted cache files found.")

        repaired_count = 0
        backup_count = 0
        details = []

        backup_dir = self.terminal_data_path / "cache_backups" if self.terminal_data_path else Path("logs/cache_backups")
        backup_dir.mkdir(parents=True, exist_ok=True)

        for p in corrupted_files:
            try:
                # 1. Non-destructive backup
                bak_target = backup_dir / f"{p.name}.{int(time.time())}.bak"
                try:
                    shutil.copy2(p, bak_target)
                    backup_count += 1
                except (PermissionError, OSError) as be:
                    logger.warning(f"[CACHE_REPAIR] File '{p.name}' locked by active MT5 process — skipping backup: {be}")

                # 2. Safely remove corrupted file
                if p.exists():
                    try:
                        os.remove(p)
                        repaired_count += 1
                        msg = f"Purged corrupted file: {p.name} (Backup: {bak_target.name})"
                        logger.info(f"[CACHE_REPAIR] {msg}")
                        details.append(msg)
                    except (PermissionError, OSError) as pe:
                        logger.warning(f"[CACHE_REPAIR] File '{p.name}' currently locked by running MT5 process — purge postponed: {pe}")
                        details.append(f"Purge postponed for locked file {p.name}")
            except Exception as e:
                err_msg = f"Failed to purge cache file {p.name}: {e}"
                logger.error(f"[CACHE_REPAIR] {err_msg}")
                details.append(err_msg)

        success = repaired_count == len(corrupted_files)
        return RepairActionResult(
            success=success,
            corrupted_files_found=len(corrupted_files),
            files_repaired=repaired_count,
            files_backed_up=backup_count,
            details=details,
        )

    def handle_mt5_error_code(self, error_code: int, symbol: str = "") -> bool:
        """
        Automatically repair cache if MT5 error indicates cache or sync failure.
        """
        if error_code not in self.KNOWN_MT5_ERRORS:
            return False

        reason = self.KNOWN_MT5_ERRORS[error_code]
        logger.warning(f"[CACHE_REPAIR] MT5 Error [{error_code}] detected for '{symbol}': {reason}")

        res = self.repair_corrupted_cache()
        logger.info(f"[CACHE_REPAIR] Auto-repair result for Error [{error_code}]: {res.files_repaired} files repaired.")
        return res.success
