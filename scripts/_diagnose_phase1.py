import datetime
import os
import shutil
import time
from pathlib import Path
import MetaTrader5 as mt5

if not mt5.initialize():
    print("INIT FAIL:", mt5.last_error())
    exit(1)

term = mt5.terminal_info()
dp = term.data_path
print("=== 1. MT5 DATA PATH ===")
print("Data Path:", dp)
print("Terminal Path:", term.path)
print("Connected:", term.connected)
print("Build:", term.build)
print()

print("=== 2. XAUUSD HISTORY DIRECTORY INSPECTION ===")
hist_dir = Path(dp) / "bases" / "VantageMarkets-Demo" / "history" / "XAUUSD"
ticks_dir = Path(dp) / "bases" / "VantageMarkets-Demo" / "ticks" / "XAUUSD"
crp_file = Path(dp) / "bases" / "VantageMarkets-Demo" / "ticks" / "XAUUSD.crp"

print("History dir exists:", hist_dir.exists())
if hist_dir.exists():
    for f in hist_dir.iterdir():
        if f.is_dir():
            print(f"  [DIR] {f.name}: {len(list(f.iterdir()))} files")
        else:
            print(f"  [FILE] {f.name}: {f.stat().st_size} bytes, attr={f.stat().st_file_attributes}")

print()
print("=== 3. XAUUSD TICK DIRECTORY & CRP INSPECTION ===")
print("CRP file exists:", crp_file.exists())
if crp_file.exists():
    print(f"CRP file size: {crp_file.stat().st_size} bytes, attr={crp_file.stat().st_file_attributes}")

print("Ticks dir exists:", ticks_dir.exists())
if ticks_dir.exists():
    for f in ticks_dir.iterdir():
        print(f"  [TICK FILE] {f.name}: {f.stat().st_size} bytes")

print()
print("=== 4. MT5 SYMBOL MAPPING DISCOVERY ===")
all_symbols = mt5.symbols_get()
xau_matches = [s.name for s in all_symbols if "XAU" in s.name or "GOLD" in s.name] if all_symbols else []
print("Matched Gold Symbols:", xau_matches)

print()
print("=== 5. MT5 API CALL TESTING FOR XAUUSD ===")
symbols_to_test = ["XAUUSD"] + [s for s in xau_matches if s != "XAUUSD"]
for sym in symbols_to_test:
    s_info = mt5.symbol_info(sym)
    s_tick = mt5.symbol_info_tick(sym)
    rates_m1 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 10)
    rates_m15 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 10)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    ticks_copy = mt5.copy_ticks_from(sym, now_utc, 10, mt5.COPY_TICKS_ALL)
    book = mt5.market_book_get(sym)
    
    print(f"--- {sym} ---")
    visible_str = str(s_info.visible) if s_info else "FAIL"
    bid_str = f"{s_tick.bid:.2f}" if s_tick else "FAIL"
    m1_str = f"OK ({len(rates_m1)} bars)" if rates_m1 is not None else "FAIL"
    m15_str = f"OK ({len(rates_m15)} bars)" if rates_m15 is not None else "FAIL"
    ticks_str = f"OK ({len(ticks_copy)} ticks)" if ticks_copy is not None else "FAIL"
    book_str = f"OK ({len(book)} depth)" if book else "EMPTY/UNSUBSCRIBED"
    
    print(f"  symbol_info():      {visible_str}")
    print(f"  symbol_info_tick(): {bid_str}")
    print(f"  copy_rates M1:      {m1_str}")
    print(f"  copy_rates M15:     {m15_str}")
    print(f"  copy_ticks_from:    {ticks_str}")
    print(f"  market_book_get:    {book_str}")
