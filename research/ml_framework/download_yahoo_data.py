"""
research/ml_framework/download_yahoo_data.py

Downloads real historical data via yfinance and saves it in MT5 CSV format,
so the Phase 6 pipeline can operate on real market data.
"""

import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime

def download_data():
    os.makedirs("data/mt5", exist_ok=True)
    
    # yfinance symbol mapping
    symbols = {
        "BTCUSD": "BTC-USD",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "JPY=X",
        "XAUUSD": "GC=F", # Gold futures
        "NAS100": "NQ=F", # Nasdaq futures
        "US30": "YM=F"    # Dow futures
    }
    
    for mt5_sym, yf_sym in symbols.items():
        print(f"Downloading real data for {mt5_sym} ({yf_sym})...")
        try:
            # yfinance allows 60 days of 15m data max
            df = yf.download(yf_sym, interval="15m", period="60d", progress=False)
            
            if df.empty:
                print(f"Failed to get data for {yf_sym}")
                continue
                
            # Flatten multi-index columns if present (yfinance does this sometimes)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            # We want: Date, Time, Open, High, Low, Close, TickVol, Vol, Spread
            # <DATE>	<TIME>	<OPEN>	<HIGH>	<LOW>	<CLOSE>	<TICKVOL>	<VOL>	<SPREAD>
            
            formatted_rows = []
            formatted_rows.append("<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<TICKVOL>,<VOL>,<SPREAD>")
            
            for idx, row in df.iterrows():
                dt = idx.strftime("%Y.%m.%d")
                tm = idx.strftime("%H:%M:%S")
                o = f"{row['Open']:.6f}"
                h = f"{row['High']:.6f}"
                l = f"{row['Low']:.6f}"
                c = f"{row['Close']:.6f}"
                v = int(row.get('Volume', 0))
                # For MT5 format: TickVol (we'll just use Vol or a default), Vol (0), Spread (15)
                formatted_rows.append(f"{dt},{tm},{o},{h},{l},{c},{v},0,15")
                
            filepath = f"data/mt5/{mt5_sym}_M15.csv"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(formatted_rows))
                
            print(f"Saved {len(formatted_rows)-1} real bars for {mt5_sym} to {filepath}")
            
        except Exception as e:
            print(f"Error downloading {mt5_sym}: {e}")

if __name__ == "__main__":
    download_data()
