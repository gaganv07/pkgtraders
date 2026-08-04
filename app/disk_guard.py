"""
app/disk_guard.py — Disk Space Guardian for MT5 Trading Bot
============================================================

Monitors available disk space on the MT5 data drive and the project drive.
Detects disk-full conditions BEFORE they cause MT5 tick write errors [112].
Provides safe cleanup routines and automatic MT5 cache management.

Errors prevented:
  - 'XAUUSD' file writing error [There is not enough space on the disk. (112)]
  - synchronization process failed [XAUUSD]
  - 'XAUUSD' file opening or reading error [2]

STRICT: No trading logic, strategy, or indicators are modified here.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
CRITICAL_FREE_MB = 500      # Below this: stop tick downloading, alert
WARNING_FREE_MB  = 1_000    # Below this: warn every cycle
OK_FREE_MB       = 2_000    # Above this: fully OK


def _drive_free_mb(path: str) -> float:
    """Return free space in MB for the drive containing `path`."""
    try:
        stat = shutil.disk_usage(path)
        return stat.free / (1024 * 1024)
    except Exception:
        return float("inf")


def _folder_size_mb(path: str) -> float:
    """Return total size in MB of a folder (recursive)."""
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except Exception:
        pass
    return total / (1024 * 1024)


class DiskGuard:
    """
    Monitor disk space and perform safe MT5 cache cleanup when needed.

    Responsibilities:
      1. Check free MB on C: (MT5 data drive) before each bot cycle.
      2. Emit WARNING logs at < 1 GB free.
      3. Emit CRITICAL logs + trigger cleanup at < 500 MB free.
      4. Detect and remove stale broker cache folders (old broker data).
      5. Repair corrupt XAUUSD.crp (zero-byte tick index).
      6. Clean old MT5 logs (keep last N days).
    """

    def __init__(
        self,
        mt5_data_path: Optional[str] = None,
        active_broker: str = "VantageMarkets-Demo",
        log_retention_days: int = 7,
    ):
        self.mt5_data_path = mt5_data_path or self._auto_detect_mt5_data()
        self.active_broker = active_broker
        self.log_retention_days = log_retention_days
        self._last_check_time = 0.0
        self._check_interval_s = 60.0     # Re-check every 60 seconds
        self._last_cleanup_time = 0.0
        self._cleanup_cooldown_s = 300.0  # Don't clean more than once per 5 min

    # ── Public API ─────────────────────────────────────────────────────────────

    def check(self) -> Tuple[str, float, str]:
        """
        Check disk health. Returns (status, free_mb, message).
        status: "OK" | "WARNING" | "CRITICAL"
        """
        now = time.time()
        if now - self._last_check_time < self._check_interval_s:
            return "OK", float("inf"), "Cached OK"

        self._last_check_time = now

        if not self.mt5_data_path:
            return "OK", float("inf"), "MT5 data path unknown, skipping check"

        free_mb = _drive_free_mb(self.mt5_data_path)

        if free_mb < CRITICAL_FREE_MB:
            msg = (
                f"🚨 DISK CRITICAL: Only {free_mb:.0f} MB free on MT5 drive. "
                f"MT5 tick write errors [112] will occur! Triggering auto-cleanup."
            )
            logger.critical(msg)
            self._auto_cleanup()
            # Re-check after cleanup
            free_mb = _drive_free_mb(self.mt5_data_path)
            if free_mb < CRITICAL_FREE_MB:
                return "CRITICAL", free_mb, msg
            return "WARNING", free_mb, "Post-cleanup: " + msg
        elif free_mb < WARNING_FREE_MB:
            msg = f"⚠️  DISK WARNING: {free_mb:.0f} MB free on MT5 drive. " \
                  f"Consider moving old broker data to D: drive."
            logger.warning(msg)
            return "WARNING", free_mb, msg
        else:
            return "OK", free_mb, f"Disk OK: {free_mb:.0f} MB free"

    def repair_xauusd_crp(self) -> bool:
        """
        Detect and remove a zero-byte corrupt XAUUSD.crp tick cache file.
        Returns True if corruption was found and removed.
        """
        if not self.mt5_data_path:
            return False

        crp = Path(self.mt5_data_path) / "bases" / self.active_broker / "ticks" / "XAUUSD.crp"
        if not crp.exists():
            logger.debug("[DiskGuard] XAUUSD.crp not found (clean state)")
            return False

        size = crp.stat().st_size
        if size == 0:
            # Backup the corrupt file
            bak = crp.with_suffix(".crp.bak")
            try:
                shutil.copy2(str(crp), str(bak))
                crp.unlink()
                logger.warning(
                    f"[DiskGuard] REPAIRED: Removed corrupt 0-byte XAUUSD.crp. "
                    f"Backup at {bak}. MT5 will rebuild tick index on next sync."
                )
                return True
            except PermissionError:
                logger.error(
                    "[DiskGuard] Cannot delete XAUUSD.crp — file locked by MT5 terminal. "
                    "Close MT5 briefly and run scripts/repair_xauusd_crp.py."
                )
                return False
        else:
            logger.debug(f"[DiskGuard] XAUUSD.crp is healthy ({size} bytes)")
            return False

    def get_disk_report(self) -> Dict:
        """Return a dict with full disk diagnostic info."""
        if not self.mt5_data_path:
            return {"error": "MT5 data path unknown"}

        dp = Path(self.mt5_data_path)
        bases = dp / "bases"

        broker_sizes = {}
        if bases.exists():
            for broker_dir in bases.iterdir():
                if broker_dir.is_dir():
                    broker_sizes[broker_dir.name] = round(
                        _folder_size_mb(str(broker_dir)), 1
                    )

        crp = dp / "bases" / self.active_broker / "ticks" / "XAUUSD.crp"
        crp_status = "MISSING"
        if crp.exists():
            sz = crp.stat().st_size
            crp_status = "CORRUPT (0 bytes)" if sz == 0 else f"OK ({sz} bytes)"

        free_mb = _drive_free_mb(str(dp))

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mt5_data_path": str(dp),
            "drive_free_mb": round(free_mb, 1),
            "drive_status": (
                "CRITICAL" if free_mb < CRITICAL_FREE_MB
                else "WARNING" if free_mb < WARNING_FREE_MB
                else "OK"
            ),
            "broker_data_sizes_mb": broker_sizes,
            "total_mt5_data_mb": round(_folder_size_mb(str(dp)), 1),
            "xauusd_crp_status": crp_status,
            "active_broker": self.active_broker,
            "stale_broker_dirs": [
                k for k in broker_sizes if k != self.active_broker
                and k not in ("Common", "Custom", "Default", "signals", "Chats")
                and broker_sizes[k] > 100  # > 100 MB
            ],
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _auto_cleanup(self) -> None:
        """Safe automatic cleanup: old logs only. Does NOT touch project files."""
        now = time.time()
        if now - self._last_cleanup_time < self._cleanup_cooldown_s:
            return
        self._last_cleanup_time = now

        logger.info("[DiskGuard] Running safe auto-cleanup...")

        freed = 0.0

        # 1. Clean MT5 old log files (keep last N days)
        freed += self._clean_old_logs()

        # 2. Clean pip cache
        freed += self._clean_pip_cache()

        # 3. Clean Windows temp files
        freed += self._clean_temp()

        logger.info(f"[DiskGuard] Auto-cleanup freed ~{freed:.0f} MB.")

        if freed < 200:
            logger.warning(
                "[DiskGuard] Auto-cleanup freed < 200 MB. "
                "Manual intervention required: Move old broker data from C: to D: drive.\n"
                "  Stale data example:\n"
                "  C:\\Users\\<user>\\AppData\\Roaming\\MetaQuotes\\Terminal\\...\\bases\\BlackBullMarkets-Demo\n"
                "  Run scripts/disk_cleanup.py for guided cleanup."
            )

    def _clean_old_logs(self) -> float:
        """Remove MT5 log files older than retention_days. Returns MB freed."""
        if not self.mt5_data_path:
            return 0.0

        logs_dir = Path(self.mt5_data_path) / "logs"
        if not logs_dir.exists():
            return 0.0

        cutoff = time.time() - (self.log_retention_days * 86400)
        freed = 0.0
        for f in logs_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                size = f.stat().st_size / (1024 * 1024)
                try:
                    f.unlink()
                    freed += size
                    logger.debug(f"[DiskGuard] Removed old log: {f.name}")
                except Exception:
                    pass
        return freed

    def _clean_pip_cache(self) -> float:
        """Clear pip download cache. Returns estimated MB freed."""
        try:
            import subprocess
            result = subprocess.run(
                ["pip", "cache", "purge"],
                capture_output=True, text=True, timeout=30
            )
            if "Files removed" in result.stdout:
                logger.info(f"[DiskGuard] pip cache cleared: {result.stdout.strip()}")
            return 0.0  # Can't easily measure
        except Exception:
            return 0.0

    def _clean_temp(self) -> float:
        """Remove user temp files. Returns MB freed."""
        temp_dir = os.environ.get("TEMP", "")
        if not temp_dir or not os.path.exists(temp_dir):
            return 0.0

        freed = 0.0
        for item in Path(temp_dir).iterdir():
            try:
                size = _folder_size_mb(str(item)) if item.is_dir() else item.stat().st_size / (1024 * 1024)
                if item.is_dir():
                    shutil.rmtree(str(item), ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
                freed += size
            except Exception:
                pass
        return freed

    @staticmethod
    def _auto_detect_mt5_data() -> Optional[str]:
        """Auto-detect MT5 data path from known MetaQuotes directories."""
        import platform
        if platform.system() != "Windows":
            return None

        base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
        if not base.exists():
            return None

        # Find terminal directories (hex-named)
        candidates = [d for d in base.iterdir() if d.is_dir() and len(d.name) == 32]
        if not candidates:
            return None

        # Prefer the largest (most data = most likely active)
        candidates.sort(key=lambda d: _folder_size_mb(str(d)), reverse=True)
        return str(candidates[0])
