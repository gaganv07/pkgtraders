"""
scripts/find_mt5_terminals.py — MT5 Terminal Discovery & Account Audit Tool

Scans the local filesystem for all MT5 executable paths, inspects active processes,
and determines which terminal is connected to Live vs Demo accounts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Dict, Any

try:
    import psutil
except ImportError:
    psutil = None

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


def scan_for_mt5_executables() -> List[Path]:
    """Scan common installation paths for terminal64.exe."""
    found = []
    search_roots = [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path(os.path.expanduser("~")) / "AppData" / "Roaming" / "MetaQuotes",
        Path(os.path.expanduser("~")) / "AppData" / "Local" / "Programs",
    ]

    for root in search_roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("terminal64.exe"):
                if p not in found:
                    found.append(p)
            for p in root.rglob("terminal.exe"):
                if p not in found:
                    found.append(p)
        except Exception as e:
            print(f"Warning scanning {root}: {e}")

    return found


def inspect_terminal_path(exe_path: Path) -> Dict[str, Any]:
    """Initialize MT5 with specific path and inspect logged-in account details."""
    if mt5 is None:
        return {"error": "MetaTrader5 package not installed"}

    mt5.shutdown()
    init_ok = mt5.initialize(path=str(exe_path), timeout=10000)

    if not init_ok:
        err = mt5.last_error()
        return {"path": str(exe_path), "init_ok": False, "error": err}

    acct = mt5.account_info()
    term = mt5.terminal_info()

    res = {
        "path": str(exe_path),
        "init_ok": True,
        "connected": term.connected if term else False,
        "login": acct.login if acct else 0,
        "server": acct.server if acct else "Unknown",
        "company": acct.company if acct else "Unknown",
        "trade_mode": "Demo" if (acct and acct.trade_mode == 0) else ("Live" if (acct and acct.trade_mode == 2) else "Unknown"),
        "balance": acct.balance if acct else 0.0,
        "equity": acct.equity if acct else 0.0,
        "currency": acct.currency if acct else "USD",
        "leverage": acct.leverage if acct else 1,
    }

    mt5.shutdown()
    return res


def main():
    print("\n" + "=" * 70)
    print("   METATRADER 5 TERMINAL DISCOVERY & ACCOUNT AUDIT")
    print("=" * 70)

    # 1. Active Processes
    print("\n1. Active MT5 Processes:")
    if psutil:
        procs = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = (proc.info["name"] or "").lower()
                if "terminal64" in name or "terminal.exe" in name:
                    procs.append(proc.info)
            except Exception:
                pass
        if procs:
            for p in procs:
                print(f"   - PID {p['pid']}: {p['name']} -> Path: {p['exe']}")
        else:
            print("   - No active terminal64.exe process running.")

    # 2. Installed Terminal Executables
    print("\n2. Scanning Filesystem for Installed MT5 Terminals:")
    terminals = scan_for_mt5_executables()
    if not terminals:
        print("   - No MT5 executables found in standard directories.")
    else:
        for idx, tpath in enumerate(terminals, 1):
            print(f"   [{idx}] {tpath}")

    # 3. Account Inspection per Terminal
    print("\n3. Inspecting Accounts Logged into Each Terminal:")
    vantage_demo_found = None
    live_account_found = None

    for idx, tpath in enumerate(terminals, 1):
        print(f"\n   Testing Terminal [{idx}]: {tpath}")
        info = inspect_terminal_path(tpath)
        if not info.get("init_ok"):
            print(f"     └── Failed to initialize: {info.get('error')}")
        else:
            login = info.get("login", 0)
            server = info.get("server", "Unknown")
            mode = info.get("trade_mode", "Unknown")
            broker = info.get("company", "Unknown")
            balance = info.get("balance", 0.0)
            equity = info.get("equity", 0.0)
            curr = info.get("currency", "USD")

            print(f"     ├── Broker:   {broker}")
            print(f"     ├── Server:   {server}")
            print(f"     ├── Login:    #{login}")
            print(f"     ├── Mode:     {mode}")
            print(f"     └── Balance:  ${balance:,.2f} {curr} | Equity: ${equity:,.2f}")

            if login == 25687070 or "Vantage" in server or "Vantage" in broker:
                vantage_demo_found = str(tpath)

            if mode == "Live":
                live_account_found = (str(tpath), login, server, broker)

    print("\n" + "=" * 70)
    print(" AUDIT SUMMARY:")
    if live_account_found:
        print(f" ⚠️ LIVE ACCOUNT DETECTED on Terminal: {live_account_found[0]}")
        print(f"    Account: #{live_account_found[1]} | Server: {live_account_found[2]} | Broker: {live_account_found[3]}")
    else:
        print(" [OK] No active Live trading account detected on inspected terminals.")

    if vantage_demo_found:
        print(f" ✅ VANTAGE DEMO TERMINAL CONFIRMED: {vantage_demo_found}")
    else:
        print(" ⚠️ Vantage Demo terminal path not automatically resolved.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
