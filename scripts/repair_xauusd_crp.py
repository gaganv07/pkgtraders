"""
scripts/repair_xauusd_crp.py — Fast inline MT5 XAUUSD.crp Repair
=================================================================
Uses mt5.initialize() without credentials (connects to running terminal).
Backed up to XAUUSD.crp.bak, then deleted to force MT5 to rebuild.
"""
import MetaTrader5 as mt5
import shutil
import time
from pathlib import Path

print("=" * 60)
print("XAUUSD.crp Repair — Inline Fast Mode")
print("=" * 60)

# Step 1: Connect to already-running terminal
if not mt5.initialize():
    print("ERROR: mt5.initialize() failed:", mt5.last_error())
    exit(1)

acct = mt5.account_info()
term = mt5.terminal_info()
print(f"Connected: Account #{acct.login} | {acct.server}")
print(f"Data path: {term.data_path}")

# Step 2: Locate XAUUSD.crp
bases = Path(term.data_path) / "bases"
bd = next((d for d in bases.iterdir() if "Vantage" in d.name), None)
if bd is None:
    # Fallback: search for ticks folder
    for d in bases.iterdir():
        ticks = d / "ticks" / "XAUUSD.crp"
        if ticks.exists():
            bd = d
            break

if bd is None:
    print("ERROR: Cannot find broker directory under", bases)
    exit(1)

print(f"Broker dir: {bd}")
crp = bd / "ticks" / "XAUUSD.crp"
sz = crp.stat().st_size if crp.exists() else -1
print(f"XAUUSD.crp: exists={crp.exists()} size={sz} bytes")

# Step 3: Remove if corrupt (0 bytes)
if crp.exists() and sz == 0:
    backup = bd / "ticks" / "XAUUSD.crp.bak"
    shutil.copy2(str(crp), str(backup))
    crp.unlink()
    print(f"DONE: Deleted corrupt XAUUSD.crp")
    print(f"      Backed up to: {backup}")
elif crp.exists() and sz > 0:
    print(f"XAUUSD.crp has data ({sz} bytes) — not corrupt, no action needed")
else:
    print("XAUUSD.crp not found — already clean or never created")

# Step 4: Force symbol resync
print("\nForcing XAUUSD symbol resync...")
mt5.symbol_select("XAUUSD", False)
time.sleep(1.0)
ok = mt5.symbol_select("XAUUSD", True)
time.sleep(2.0)
print(f"symbol_select resync: {ok}")

# Step 5: Verify
tick = mt5.symbol_info_tick("XAUUSD")
bars = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1, 0, 10)
crp_now = bd / "ticks" / "XAUUSD.crp"
crp_status = f"EXISTS size={crp_now.stat().st_size}" if crp_now.exists() else "GONE (will be rebuilt by MT5 on next sync)"

print("\n" + "=" * 60)
print("VERIFICATION RESULTS:")
print(f"  Live tick Bid: {tick.bid:.2f} Ask: {tick.ask:.2f}" if tick else "  Live tick: N/A (market closed?)")
print(f"  M1 bars: {len(bars) if bars is not None else 'FAIL'}")
print(f"  XAUUSD.crp: {crp_status}")
print("=" * 60)
print("REPAIR COMPLETE. MT5 Journal errors should stop.")
print("NOTE: MT5 connection preserved (bot continues running)")
