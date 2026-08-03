"""
research/ml_framework/mock_mt5_export.py

Generates random-walk OHLCV data that strictly mimics the MT5 export format,
acting as a placeholder since real CSVs have not been provided yet.
This ensures the Phase 6 Real MT5 Framework can be fully executed and verified.
"""

import os
import random
from datetime import datetime, timedelta, timezone

def generate_mock_csv(symbol: str, start_price: float, days: int):
    os.makedirs("data/mt5", exist_ok=True)
    filepath = f"data/mt5/{symbol}_M15.csv"
    
    rng = random.Random(hash(symbol))
    
    # 24 months of data
    start_dt = datetime(2022, 1, 1, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=days)
    
    bars = []
    bars.append("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>")
    
    p = start_price
    t = start_dt
    
    while t < end_dt:
        if t.weekday() >= 5: # Skip weekends
            t += timedelta(minutes=15)
            continue
            
        vol = p * 0.0004
        o = p
        c = o + rng.gauss(0, vol) # Pure random walk
        h = max(o, c) + abs(rng.gauss(0, vol * 0.5))
        l = min(o, c) - abs(rng.gauss(0, vol * 0.5))
        tickvol = rng.randint(100, 2000)
        
        # MT5 Format
        d_str = t.strftime("%Y.%m.%d")
        t_str = t.strftime("%H:%M:%S")
        bars.append(f"{d_str}\t{t_str}\t{o:.5f}\t{h:.5f}\t{l:.5f}\t{c:.5f}\t{tickvol}\t0\t15")
        
        p = c
        t += timedelta(minutes=15)
        
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(bars))
        
    print(f"Generated {len(bars)-1} mock MT5 bars for {symbol} at {filepath}")

if __name__ == "__main__":
    generate_mock_csv("BTCUSD", 65000.0, 730)
    generate_mock_csv("EURUSD", 1.085, 730)
    generate_mock_csv("XAUUSD", 3200.0, 730)
