import MetaTrader5 as mt5
import shutil
from pathlib import Path

mt5.initialize()
acct = mt5.account_info()
term = mt5.terminal_info()

print("=== ACCOUNT VALIDATION ===")
print(f"Login:          {acct.login}")
print(f"Server:         {acct.server}")
print(f"Company:        {acct.company}")
print(f"Balance:        {acct.balance}")
print(f"Mode:           {'DEMO' if acct.trade_mode==0 else 'LIVE'}")
print(f"Trade_Allowed:  {acct.trade_allowed}")
print(f"Trade_Expert:   {acct.trade_expert}")
print(f"Leverage:       {acct.leverage}")
print()

print("=== TERMINAL STATUS ===")
print(f"Build:          {term.build}")
print(f"Connected:      {term.connected}")
print(f"AutoTrading:    {term.trade_allowed}")
print(f"DLL_allowed:    {term.dlls_allowed}")
print(f"Data path:      {term.data_path}")
print()

dp = term.data_path
free_mb = shutil.disk_usage(dp).free / 1e6
print("=== DISK STATUS ===")
print(f"C: Free:        {free_mb:.0f} MB")
print(f"Status:         {'CRITICAL' if free_mb<500 else 'WARNING' if free_mb<1000 else 'OK'}")
print()

print("=== XAUUSD VALIDATION ===")
sym = mt5.symbol_info("XAUUSD")
tick = mt5.symbol_info_tick("XAUUSD")
bars_m1  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M1,  0, 100)
bars_m5  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5,  0, 100)
bars_m15 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M15, 0, 100)
bars_h1  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1,  0, 100)
bars_d1  = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_D1,  0, 100)
print(f"Symbol visible: {sym.visible if sym else None}")
print(f"Trade mode:     {sym.trade_mode if sym else None}")
if tick and sym:
    print(f"Bid/Ask:        {tick.bid:.2f}/{tick.ask:.2f}")
    print(f"Spread pts:     {round((tick.ask-tick.bid)/sym.point)}")
print(f"M1 bars:        {len(bars_m1) if bars_m1 is not None else 'FAIL'}")
print(f"M5 bars:        {len(bars_m5) if bars_m5 is not None else 'FAIL'}")
print(f"M15 bars:       {len(bars_m15) if bars_m15 is not None else 'FAIL'}")
print(f"H1 bars:        {len(bars_h1) if bars_h1 is not None else 'FAIL'}")
print(f"D1 bars:        {len(bars_d1) if bars_d1 is not None else 'FAIL'}")
print(f"Last error:     {mt5.last_error()}")
print()

print("=== TICK SYNC STATUS ===")
crp = Path(dp) / "bases" / "VantageMarkets-Demo" / "ticks" / "XAUUSD.crp"
tkc_dir = Path(dp) / "bases" / "VantageMarkets-Demo" / "ticks" / "XAUUSD"
crp_sz = crp.stat().st_size if crp.exists() else "NOT FOUND"
print(f"XAUUSD.crp:     {crp_sz} bytes")
if tkc_dir.exists():
    for f in tkc_dir.iterdir():
        print(f"  {f.name}: {f.stat().st_size/1e6:.1f} MB")
else:
    print("  Tick dir: EMPTY")
print()

print("=== MULTI-SYMBOL DATA TEST ===")
for sn in ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]:
    b = mt5.copy_rates_from_pos(sn, mt5.TIMEFRAME_M15, 0, 10)
    t = mt5.symbol_info_tick(sn)
    bid = f"{t.bid:.5f}" if t else "None"
    print(f"{sn:<10}: M15 bars={len(b) if b is not None else 'FAIL'}  bid={bid}")
