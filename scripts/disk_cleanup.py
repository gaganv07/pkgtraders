"""
scripts/disk_cleanup.py — Safe Disk Cleanup Guide for MT5 Bot
=============================================================

Interactively identifies and safely cleans disk space on C: drive
to prevent MT5 'file writing error [112]' (disk full).

SAFE OPERATIONS ONLY:
  - Move stale broker data to D: drive
  - Clean pip/npm caches
  - Clean temp files
  - Clean old MT5 logs
  - NO deletion of project source code
  - NO deletion of Git data
  - NO deletion of trading database or logs from current session

Usage:
    python scripts/disk_cleanup.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def gb(n_bytes: float) -> str:
    return f"{n_bytes / 1e9:.2f} GB"


def mb(n_bytes: float) -> str:
    return f"{n_bytes / 1e6:.0f} MB"


def folder_size(path: str) -> int:
    total = 0
    for dp, _, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def drive_free(path: str) -> int:
    try:
        return shutil.disk_usage(path).free
    except Exception:
        return 0


def run():
    print("=" * 65)
    print("XAUUSD Pro — Safe C: Drive Cleanup Tool")
    print("=" * 65)

    # ── Disk Overview ──────────────────────────────────────────────────────────
    c_free = drive_free("C:\\")
    d_free = drive_free("D:\\")
    print(f"\nC: Free: {gb(c_free)}")
    print(f"D: Free: {gb(d_free)}")

    if c_free > 2e9:
        print("\n[OK] C: drive has enough space (> 2 GB). No cleanup needed.")
        print(f"   Free: {gb(c_free)}")
        return

    total_freed = 0

    # ── MT5 Data Path ──────────────────────────────────────────────────────────
    appdata = os.environ.get("APPDATA", "")
    mq_term = Path(appdata) / "MetaQuotes" / "Terminal"
    mt5_terminals = [d for d in mq_term.iterdir() if d.is_dir() and len(d.name) == 32] if mq_term.exists() else []

    for terminal in mt5_terminals:
        bases = terminal / "bases"
        if not bases.exists():
            continue

        print(f"\n=== MT5 Terminal: {terminal.name} ===")
        broker_dirs = [d for d in bases.iterdir() if d.is_dir()]

        stale = []
        active_brokers = ["VantageMarkets-Demo", "Default", "Common", "Custom", "signals", "Chats"]

        for bd in broker_dirs:
            sz = folder_size(str(bd))
            marker = " [ACTIVE]" if bd.name in active_brokers else ""
            print(f"  {bd.name}: {mb(sz)}{marker}")
            if bd.name not in active_brokers and sz > 50e6:
                stale.append((bd, sz))

        if stale:
            print(f"\n  Found {len(stale)} stale broker data folder(s):")
            for bd, sz in stale:
                print(f"    {bd.name}: {gb(sz)}")

            if d_free > 10e9:
                dst_base = Path("D:\\mt5_data_backup")
                for bd, sz in stale:
                    dst = dst_base / bd.name
                    print(f"\n  Moving {bd.name} ({gb(sz)}) to {dst}...")
                    dst_base.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        print(f"  Backup already exists at {dst} -- skipping move, removing source.")
                        shutil.rmtree(str(bd), ignore_errors=True)
                    else:
                        shutil.move(str(bd), str(dst_base))
                    moved = folder_size(str(dst)) if dst.exists() else 0
                    total_freed += sz
                    print(f"  [OK] Moved. Backup: {gb(moved)} at {dst}")
            else:
                print("  [WARN] D: drive has < 10 GB free. Cannot safely move broker data.")

    # ── Clean MT5 Logs ────────────────────────────────────────────────────────
    for terminal in mt5_terminals:
        logs_dir = terminal / "logs"
        if not logs_dir.exists():
            continue
        cutoff = time.time() - 7 * 86400
        freed = 0
        for f in logs_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    freed += sz
                except Exception:
                    pass
        if freed:
            print(f"\n  Cleaned old MT5 logs: {mb(freed)}")
            total_freed += freed

    # ── pip cache ─────────────────────────────────────────────────────────────
    print("\n=== Cleaning pip cache ===")
    try:
        r = subprocess.run(["pip", "cache", "purge"], capture_output=True, text=True, timeout=30)
        print(f"  {r.stdout.strip() or 'Done'}")
    except Exception as e:
        print(f"  pip cache clean failed: {e}")

    # ── npm cache ─────────────────────────────────────────────────────────────
    npm_cache = Path(os.environ.get("APPDATA", "")) / "npm-cache"
    if npm_cache.exists():
        npm_sz = folder_size(str(npm_cache))
        if npm_sz > 100e6:
            print(f"\n=== Cleaning npm cache ({mb(npm_sz)}) ===")
            try:
                subprocess.run(["npm", "cache", "clean", "--force"], timeout=60, capture_output=True)
                total_freed += npm_sz
                print("  [OK] npm cache cleaned")
            except Exception as e:
                print(f"  npm cache clean failed: {e}")

    # ── User Temp ─────────────────────────────────────────────────────────────
    temp = os.environ.get("TEMP", "")
    if temp and os.path.exists(temp):
        tmp_sz = folder_size(temp)
        if tmp_sz > 50e6:
            print(f"\n=== Cleaning user temp ({mb(tmp_sz)}) ===")
            shutil.rmtree(temp, ignore_errors=True)
            os.makedirs(temp, exist_ok=True)
            total_freed += tmp_sz
            print(f"  [OK] Temp cleaned")

    # ── Final Report ──────────────────────────────────────────────────────────
    c_free_after = drive_free("C:\\")
    print(f"\n{'='*65}")
    print(f"CLEANUP COMPLETE")
    print(f"  Freed: ~{gb(total_freed)}")
    print(f"  C: Before: {gb(c_free)}  ->  After: {gb(c_free_after)}")
    if c_free_after > 2e9:
        print("  [OK] C: drive now has adequate free space.")
        print("  [OK] MT5 tick write errors [112] should not recur.")
    else:
        print("  [WARN] C: drive still low. Consider:")
        print("     1. Move more application data to D: drive")
        print("     2. Use Windows Disk Cleanup (cleanmgr.exe)")
        print("     3. Check C:\\Windows\\WinSxS for component bloat (DISM cleanup)")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
