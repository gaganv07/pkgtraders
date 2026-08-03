import MetaTrader5 as mt5

if not mt5.initialize():
    print("MT5 init failed")
    exit()

sym = "XAUUSD"
for count in range(50000, 100000, 10000):
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, count)
    res_len = len(rates) if rates is not None else "None"
    print(f"Request M5 {count} bars: returned {res_len}")

mt5.shutdown()
