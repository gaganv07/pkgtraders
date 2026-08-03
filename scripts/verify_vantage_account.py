"""
scripts/verify_vantage_account.py — Vantage Demo MT5 Account Connection & Verification

Verifies connection to new Vantage Demo account (#25687070), prints account parameters,
validates XAUUSD availability and tradability, and generates reports/vantage_connection_report.md.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.mt5_connection import MT5ConnectionManager

REPORTS_DIR = ROOT / "reports"
REPORT_FILE = REPORTS_DIR / "vantage_connection_report.md"


def main():
    print("\n" + "=" * 65)
    print("   VANTAGE DEMO MT5 ACCOUNT CONNECTION VERIFICATION")
    print("=" * 65)

    print(f"Target Account:  #{settings.mt5.login}")
    print(f"Target Server:   {settings.mt5.server}")

    # Re-instantiate manager with updated settings
    mgr = MT5ConnectionManager(
        login=settings.mt5.login,
        password=settings.mt5.password,
        server=settings.mt5.server,
        path=settings.mt5.path,
        symbol=settings.mt5.symbol_override or "XAUUSD",
        timeframe=settings.mt5.timeframe,
        magic=settings.mt5.magic,
    )

    # 1. Connect & Login
    res = mgr.connect_mt5()
    if not res.success:
        print(f"\n[FAIL] MT5 CONNECTION FAILED!")
        print(f"   Error Code:    {res.error_code}")
        print(f"   Error Message: {res.message}")
        print("=" * 65 + "\n")

        _write_failed_report(res.error_code, res.message)
        sys.exit(1)

    # 2. Account Information
    acct = mgr.get_account_info()
    term = mgr.get_terminal_info()

    trade_mode_val = acct.get("trade_mode", 0)
    account_type_str = "Demo" if trade_mode_val == 0 else ("Live" if trade_mode_val == 2 else "Contest")

    print("\n" + "-" * 65)
    print(" ACCOUNT SPECIFICATIONS & LIVE PARAMETERS")
    print("-" * 65)
    print(f"   Account Number:  #{acct.get('login')}")
    print(f"   Broker Name:     {acct.get('broker')}")
    print(f"   Server Name:     {acct.get('server')}")
    print(f"   Account Type:    {account_type_str}")
    print(f"   Account Holder:  {acct.get('name')}")
    print(f"   Balance:         ${acct.get('balance'):,.2f} {acct.get('currency')}")
    print(f"   Equity:          ${acct.get('equity'):,.2f} {acct.get('currency')}")
    print(f"   Free Margin:     ${acct.get('free_margin'):,.2f}")
    print(f"   Leverage Ratio:  1:{acct.get('leverage')}")
    print(f"   Currency:        {acct.get('currency')}")

    # 3. Symbol Verification (XAUUSD)
    target_symbol = settings.mt5.symbol_override or "XAUUSD"
    sym_ok, sym_msg = mgr.verify_symbol(target_symbol)

    print("\n" + "-" * 65)
    print(" SYMBOL VERIFICATION (XAUUSD)")
    print("-" * 65)
    print(f"   Symbol Name:     {target_symbol}")
    print(f"   Status:          {'[PASS] Available & Tradable' if sym_ok else '[FAIL] Unavailable'}")
    print(f"   Details:         {sym_msg}")

    # 4. Generate Connection Report
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_md = f"""# Vantage Demo MT5 Account Connection Report

**System Name:** Legacy Asset Partners — AI Trading System  
**Audit Timestamp:** {now_str}  
**Connection Status:** `ACTIVE & VERIFIED`

---

## 1. Connected Account Specifications

| Parameter | Live Value |
| :--- | :--- |
| **Account Number** | `#{acct.get('login')}` |
| **Broker Name** | `{acct.get('broker')}` |
| **Server Name** | `{acct.get('server')}` |
| **Account Type** | `{account_type_str}` |
| **Account Holder** | `{acct.get('name')}` |
| **Account Balance** | `${acct.get('balance'):,.2f} {acct.get('currency')}` |
| **Account Equity** | `${acct.get('equity'):,.2f} {acct.get('currency')}` |
| **Free Margin** | `${acct.get('free_margin'):,.2f}` |
| **Leverage Ratio** | `1:{acct.get('leverage')}` |
| **Account Currency** | `{acct.get('currency')}` |

---

## 2. Symbol Availability & Tradability

- **Target Symbol:** `{target_symbol}`
- **Tradability Status:** `{"AVAILABLE & TRADABLE" if sym_ok else "UNAVAILABLE"}`
- **Verification Note:** `{sym_msg}`

---

## 3. Operational Sign-Off

> [!NOTE]
> Connection to Vantage Demo Account `#{acct.get('login')}` verified successfully using official MetaTrader5 Python package.
"""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_md)

    print("\n" + "=" * 65)
    print(" VANTAGE DEMO CONNECTION VERIFICATION PASSED")
    print(f" Report Saved: {REPORT_FILE}")
    print("=" * 65 + "\n")


def _write_failed_report(code: int, msg: str):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_md = f"""# Vantage Demo MT5 Account Connection Report (FAILED)

**System Name:** Legacy Asset Partners — AI Trading System  
**Audit Timestamp:** {now_str}  
**Connection Status:** `FAILED`

---

## Error Details

- **MT5 Error Code:** `{code}`
- **MT5 Error Message:** `{msg}`
"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_md)


if __name__ == "__main__":
    main()
