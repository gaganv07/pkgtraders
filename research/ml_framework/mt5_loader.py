"""
research/ml_framework/mt5_loader.py

Parses and validates genuine historical OHLCV data exported from MetaTrader 5.
Supports combined datetime or separate date/time columns, commas/tabs, and UTF-8/UTF-16.
"""

import os
import csv
from datetime import datetime, timezone
from typing import List, Dict
import logging

logger = logging.getLogger("mt5_loader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# Supported symbols and timeframes
SUPPORTED_SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]
SUPPORTED_TFS = ["M15", "H1", "H4"]

def parse_mt5_row(row: List[str]) -> Dict:
    """Parses a single MT5 row with high robustness."""
    # Strip whitespace
    row = [r.strip() for r in row]
    if not row or len(row) < 5:
        return None
        
    first_col = row[0]
    
    # 1. Detect if datetime is combined or separate
    if " " in first_col:
        # Combined datetime (e.g. "2008.09.05 00:00")
        datetime_str = first_col
        # Expected structure: Datetime, Open, High, Low, Close, TickVol, (optional Spread/RealVol)
        if len(row) < 6:
            return None
        try:
            open_val = float(row[1])
            high_val = float(row[2])
            low_val = float(row[3])
            close_val = float(row[4])
            tick_vol = int(float(row[5]))
            # If spread exists as index 6 or 8
            spread_val = int(float(row[8])) if len(row) > 8 else (int(float(row[6])) if len(row) > 6 else 15)
        except ValueError:
            return None  # Skip headers or malformed rows
    else:
        # Separate columns (e.g. "2008.09.05", "00:00")
        if len(row) < 7:
            return None
        # Check if the second column looks like a time string (contains colon)
        if ":" in row[1]:
            datetime_str = f"{row[0]} {row[1]}"
            try:
                open_val = float(row[2])
                high_val = float(row[3])
                low_val = float(row[4])
                close_val = float(row[5])
                tick_vol = int(float(row[6]))
                spread_val = int(float(row[8])) if len(row) > 8 else 15
            except ValueError:
                return None
        else:
            # Fallback if separate but no colon (shouldn't happen for intraday)
            return None

    # 2. Parse datetime with multiple format fallbacks
    datetime_str = datetime_str.replace(".", "-").replace("/", "-")
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(datetime_str, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
            
    if not dt:
        return None
        
    return {
        "time": dt,
        "open": open_val,
        "high": high_val,
        "low": low_val,
        "close": close_val,
        "tick_volume": tick_vol,
        "spread": spread_val
    }

def parse_mt5_csv(filepath: str) -> List[Dict]:
    """Reads an MT5 CSV (UTF-8 or UTF-16) and returns a list of bar dictionaries."""
    # Attempt UTF-16 first
    try:
        with open(filepath, "r", encoding="utf-16") as f:
            content = f.read(2048)
            delim = '\t' if '\t' in content else ','
            f.seek(0)
            reader = csv.reader(f, delimiter=delim)
            bars = []
            for row in reader:
                parsed = parse_mt5_row(row)
                if parsed:
                    bars.append(parsed)
            if bars:
                bars.sort(key=lambda x: x["time"])
                return bars
    except Exception as e:
        logger.debug(f"UTF-16 parsing failed for {filepath}: {e}")

    # Fallback to UTF-8
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(2048)
        delim = '\t' if '\t' in content else ','
        f.seek(0)
        reader = csv.reader(f, delimiter=delim)
        bars = []
        for row in reader:
            parsed = parse_mt5_row(row)
            if parsed:
                bars.append(parsed)
        bars.sort(key=lambda x: x["time"])
        return bars

def validate_data(symbol: str, tf: str, bars: List[Dict]) -> Dict:
    """Performs deep data quality checks on parsed bars."""
    if not bars:
        return {}
        
    duplicates = 0
    non_positive = 0
    bad_ohlc = 0
    time_ordering_violations = 0
    weekend_gaps = 0
    holiday_gaps = 0
    zero_volume = 0
    
    # Track expected timeframe difference in seconds
    tf_secs = 900 if tf == "M15" else (3600 if tf == "H1" else 14400)
    
    for i in range(len(bars)):
        b = bars[i]
        
        # Check non-positive prices
        if b["open"] <= 0 or b["high"] <= 0 or b["low"] <= 0 or b["close"] <= 0:
            non_positive += 1
            
        # Check incorrect OHLC values
        if b["high"] < b["low"] or b["high"] < max(b["open"], b["close"]) or b["low"] > min(b["open"], b["close"]):
            bad_ohlc += 1
            
        # Check volume integrity
        if b["tick_volume"] <= 0:
            zero_volume += 1
            
        if i > 0:
            prev = bars[i-1]
            diff = (b["time"] - prev["time"]).total_seconds()
            
            # Duplicates & Ordering
            if diff == 0:
                duplicates += 1
            elif diff < 0:
                time_ordering_violations += 1
                
            # Gaps analysis
            if diff > tf_secs:
                # Is it a weekend gap? (Friday evening to Sunday evening)
                # Friday is weekday 4, Sunday is 6, Monday is 0
                prev_day = prev["time"].weekday()
                curr_day = b["time"].weekday()
                if (prev_day == 4 and curr_day in (6, 0)) or (diff > 86400 * 2):
                    weekend_gaps += 1
                else:
                    holiday_gaps += 1
                    
    # Calculate quality score (simple heuristic starting at 100)
    quality_score = 100.0
    if len(bars) > 0:
        penalty = (duplicates + non_positive + bad_ohlc + time_ordering_violations + zero_volume) / len(bars) * 100.0
        quality_score = max(0.0, 100.0 - penalty)
        
    return {
        "symbol": symbol,
        "tf": tf,
        "total_bars": len(bars),
        "start": bars[0]["time"],
        "end": bars[-1]["time"],
        "duplicates": duplicates,
        "non_positive": non_positive,
        "bad_ohlc": bad_ohlc,
        "time_ordering_violations": time_ordering_violations,
        "weekend_gaps": weekend_gaps,
        "holiday_gaps": holiday_gaps,
        "zero_volume": zero_volume,
        "quality_score": round(quality_score, 2)
    }

def load_all_mt5_data(data_dir: str = "data/mt5") -> Dict[str, List[Dict]]:
    """Loads all available MT5 CSV files dynamically."""
    if not os.path.exists(data_dir):
        logger.error(f"Directory {data_dir} does not exist.")
        return {}
        
    all_data = {}
    validations = []
    
    for file in os.listdir(data_dir):
        if file.endswith(".csv"):
            filepath = os.path.join(data_dir, file)
            basename = file.replace(".csv", "").replace("_", "").upper()
            
            # Discover symbol and timeframe
            symbol = None
            tf = None
            for s in SUPPORTED_SYMBOLS:
                if basename.startswith(s):
                    symbol = s
                    tf = basename[len(s):]
                    break
                    
            if not symbol or tf not in SUPPORTED_TFS:
                logger.warning(f"Skipping file with unrecognized format: {file}")
                continue
                
            logger.info(f"Loading genuine MT5 data for {symbol} ({tf}) from {file}...")
            
            try:
                bars = parse_mt5_csv(filepath)
                if not bars:
                    logger.error(f"No bars parsed from file {file}")
                    continue
                    
                # Use "SYMBOL_TF" as the key to prevent conflicts between timeframes
                key = f"{symbol}_{tf}"
                all_data[key] = bars
                val = validate_data(symbol, tf, bars)
                validations.append(val)
                logger.info(f"Successfully loaded {len(bars)} bars for {symbol} ({tf}).")
            except Exception as e:
                logger.error(f"Fatal error reading {file}: {e}")
                
    # Generate reports/mt5_data_quality.md (if data was loaded)
    if validations:
        os.makedirs("reports", exist_ok=True)
        with open("reports/mt5_data_quality.md", "w", encoding="utf-8") as f:
            f.write("# MT5 Real Data Quality Report (PARTIAL VALIDATION)\n\n")
            f.write("> [!WARNING]\n")
            f.write("> **PARTIAL VALIDATION DISCLAIMER**: Several symbol/timeframe combinations are missing. This audit represents only the available datasets.\n\n")
            f.write("| Symbol | TF | Total Bars | Start | End | Duplicates | Bad OHLC | Non-Pos | Order Violations | Zero Vol | Quality Score |\n")
            f.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
            for v in validations:
                start_str = v["start"].strftime("%Y-%m-%d %H:%M")
                end_str = v["end"].strftime("%Y-%m-%d %H:%M")
                f.write(f"| {v['symbol']} | {v['tf']} | {v['total_bars']} | {start_str} | {end_str} | {v['duplicates']} | {v['bad_ohlc']} | {v['non_positive']} | {v['time_ordering_violations']} | {v['zero_volume']} | {v['quality_score']}% |\n")
                
    return all_data

if __name__ == "__main__":
    load_all_mt5_data()
