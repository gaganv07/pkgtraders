import datetime
import os
import shutil
import time
from pathlib import Path
import MetaTrader5 as mt5

print("=" * 60)
print("XAUUSD POST-REPAIR FULL VALIDATION")
print("=" * 60)

# Connect to freshly launched terminal
if not mt5.initialize():
    print("❌ MT5 initialize() failed:", mt5.last_error())
    exit(1)

term = mt5.terminal_info()
acct = mt5.account_info()

print(f"✅ Terminal Connected: Build {term.build} | AutoTrading: {term.trade_allowed}")
print(f"✅ Account Connected: #{acct.login} on {acct.server} ({acct.company})")

# 1. Symbol Resolution & Discovery
sym = "XAUUSD"
s_info = mt5.symbol_info(sym)
s_tick = mt5.symbol_info_tick(sym)

if not s_info:
    print(f"❌ symbol_info('{sym}') returned None")
    exit(1)

print(f"✅ Symbol Resolution: {sym} found (digits={s_info.digits}, point={s_info.point}, trade_mode={s_info.trade_mode})")

# Force symbol selection
mt5.symbol_select(sym, True)
time.sleep(2.0)

# 2. Test copy_rates_from_pos for all timeframes
timeframes = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}

print("\n--- OHLCV Bar Synchronization (copy_rates_from_pos) ---")
all_bars_ok = True
for tf_name, tf_const in timeframes.items():
    rates = mt5.copy_rates_from_pos(sym, tf_const, 0, 100)
    if rates is not None and len(rates) > 0:
        last_bar = rates[-1]
        bar_time = datetime.datetime.fromtimestamp(last_bar["time"], tz=datetime.timezone.utc)
        print(f"  {tf_name:<4}: ✅ OK ({len(rates)} bars) | Latest Close: {last_bar['close']:.2f} at {bar_time.strftime('%H:%M UTC')}")
    else:
        all_bars_ok = False
        print(f"  {tf_name:<4}: ❌ FAIL (last_error: {mt5.last_error()})")

# 3. Test Live Ticks & copy_ticks_from
print("\n--- Tick Stream Synchronization (copy_ticks_from & symbol_info_tick) ---")
live_tick = mt5.symbol_info_tick(sym)
if live_tick:
    spread_pts = round((live_tick.ask - live_tick.bid) / s_info.point)
    print(f"  symbol_info_tick: ✅ Bid={live_tick.bid:.2f} Ask={live_tick.ask:.2f} Spread={spread_pts} pts")
else:
    print(f"  symbol_info_tick: ❌ FAIL (last_error: {mt5.last_error()})")

now_utc = datetime.datetime.now(datetime.timezone.utc)
ticks_copy = mt5.copy_ticks_from(sym, now_utc, 100, mt5.COPY_TICKS_ALL)
if ticks_copy is not None and len(ticks_copy) > 0:
    last_t = ticks_copy[-1]
    print(f"  copy_ticks_from:  ✅ OK ({len(ticks_copy)} ticks) | Latest Bid={last_t['bid']:.2f}")
else:
    print(f"  copy_ticks_from:  ❌ FAIL (last_error: {mt5.last_error()})")

# 4. Check File System & CRP Status
dp = term.data_path
crp_check = Path(dp) / "bases" / "VantageMarkets-Demo" / "ticks" / "XAUUSD.crp"
print("\n--- File System Status ---")
print(f"  XAUUSD.crp Directory Status: {'❌ STILL EXISTS' if crp_check.exists() else '✅ CLEANLY DELETED (Normal tick cache restored)'}")

print("\n" + "=" * 60)
if all_bars_ok and live_tick and ticks_copy is not None and len(ticks_copy) > 0 and not crp_check.exists():
    print("RESULT: ✅ ALL TESTS PASSED SUCCESSFULLY!")
else:
    print("RESULT: ❌ SOME TESTS FAILED")
print("=" * 60)
