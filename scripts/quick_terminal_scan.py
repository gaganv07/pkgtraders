"""
scripts/quick_terminal_scan.py — Targeted MT5 Executable Discovery & Account Inspector
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


def main():
    print("=" * 70)
    print("   TARGETED METATRADER 5 TERMINAL DISCOVERY")
    print("=" * 70)

    # 1. Active process paths
    print("\n1. Active MT5 Processes:")
    if psutil:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                name = (proc.info["name"] or "").lower()
                if "terminal64" in name or "terminal.exe" in name:
                    print(f"   - PID {proc.info['pid']}: {proc.info['exe']}")
            except Exception:
                pass

    # 2. Known Candidate Paths
    candidates = [
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files\Vantage FX MetaTrader 5\terminal64.exe",
        r"C:\Program Files\Vantage Markets MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
        r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe",
        r"C:\Program Files\ICMarkets MetaTrader 5\terminal64.exe",
        r"C:\Program Files\BlackBull Markets MetaTrader 5\terminal64.exe",
    ]

    print("\n2. Checking Candidate Executable Paths:")
    existing = []
    for c in candidates:
        if os.path.exists(c):
            existing.append(c)
            print(f"   [FOUND] {c}")
        else:
            print(f"   [MISSING] {c}")

    # Also search Program Files top-level folders
    pf = Path("C:/Program Files")
    if pf.exists():
        for d in pf.iterdir():
            if d.is_dir() and ("metatrader" in d.name.lower() or "vantage" in d.name.lower() or "broker" in d.name.lower()):
                t64 = d / "terminal64.exe"
                if t64.exists() and str(t64) not in existing:
                    existing.append(str(t64))
                    print(f"   [FOUND IN PF] {t64}")

    # 3. Test Connecting to Each Found Executable
    print("\n3. Testing API Account Inspection on Found Executables:")
    for exepath in existing:
        print(f"\n---> Testing: {exepath}")
        if mt5:
            mt5.shutdown()
            init_ok = mt5.initialize(path=exepath)
            if not init_ok:
                print(f"     Init Failed: {mt5.last_error()}")
            else:
                acct = mt5.account_info()
                term = mt5.terminal_info()
                if acct:
                    mode_str = "DEMO" if acct.trade_mode == 0 else ("LIVE" if acct.trade_mode == 2 else "CONTEST")
                    print(f"     CONNECTED ACCOUNT: #{acct.login} ({mode_str})")
                    print(f"     Company:  {acct.company}")
                    print(f"     Server:   {acct.server}")
                    print(f"     Holder:   {acct.name}")
                    print(f"     Balance:  ${acct.balance:,.2f} {acct.currency}")
                else:
                    print("     Connected to terminal but no account_info() returned.")
                mt5.shutdown()

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
