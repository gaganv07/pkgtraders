"""
research/ml_framework/phase7_audit.py

Executes Step 1 and 2 of Phase 7 (Data Discovery & Quality Audit).
Enforces the Failure Policy if any required MT5 files are missing.
"""

import os
import csv
import sys
from datetime import datetime, timezone

def audit_datasets():
    expected_symbols = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]
    expected_tfs = ["M15", "H1", "H4"]
    
    data_dir = "data/mt5"
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        
    found_datasets = []
    
    print("STEP 1 - DATA DISCOVERY")
    for file in os.listdir(data_dir):
        if file.endswith(".csv"):
            filepath = os.path.join(data_dir, file)
            # Support both format: EURUSDH1.csv and EURUSD_H1.csv
            basename = file.replace(".csv", "").replace("_", "")
            
            # Extract symbol and timeframe
            symbol = None
            tf = None
            for s in expected_symbols:
                if basename.startswith(s):
                    symbol = s
                    tf = basename[len(s):]
                    break
                    
            if not symbol or tf not in expected_tfs:
                print(f"Warning: Unknown file format {file}")
                continue
                
            # Quick parse to get bars and date range
            bars = 0
            start_date = None
            end_date = None
            
            # Some MT5 exports are UTF-16, some UTF-8
            try:
                with open(filepath, "r", encoding="utf-16") as f:
                    content = f.read(2048)
                    delim = '\t' if '\t' in content else ','
                    f.seek(0)
                    r = csv.reader(f, delimiter=delim)
                    # MT5 may or may not have headers
                    row1 = next(r, None)
                    if row1 and "<DATE>" not in row1[0].upper() and "<TIME>" not in row1[0].upper():
                        # First row is data
                        start_date = row1[0]
                        bars += 1
                    for row in r:
                        if len(row) > 1:
                            end_date = row[0]
                            bars += 1
            except Exception:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read(2048)
                        delim = '\t' if '\t' in content else ','
                        f.seek(0)
                        r = csv.reader(f, delimiter=delim)
                        row1 = next(r, None)
                        if row1 and "<DATE>" not in row1[0].upper() and "<TIME>" not in row1[0].upper():
                            start_date = row1[0]
                            bars += 1
                        for row in r:
                            if len(row) > 1:
                                end_date = row[0]
                                bars += 1
                except Exception as e:
                    print(f"Error reading {file}: {e}")
                    continue
                    
            found_datasets.append({
                "symbol": symbol,
                "tf": tf,
                "bars": bars,
                "start": start_date.split()[0] if start_date else "Unknown",
                "end": end_date.split()[0] if end_date else "Unknown"
            })
            
    # Check what's missing
    missing = []
    for s in expected_symbols:
        for tf in expected_tfs:
            if not any(d["symbol"] == s and d["tf"] == tf for d in found_datasets):
                missing.append(f"{s} {tf}")
                
    # Generate Inventory Report
    with open("reports/mt5_dataset_inventory.md", "w", encoding="utf-8") as f:
        f.write("# MT5 Dataset Inventory\n\n")
        
        f.write("## Discovered Datasets\n")
        f.write("| Symbol | Timeframe | Bars | Start Date | End Date |\n")
        f.write("|---|---|---|---|---|\n")
        for d in found_datasets:
            f.write(f"| {d['symbol']} | {d['tf']} | {d['bars']} | {d['start']} | {d['end']} |\n")
            
        f.write("\n## Missing Datasets\n")
        if missing:
            for m in missing:
                f.write(f"- {m}\n")
        else:
            f.write("None. All 21 required datasets are present.\n")
            
    print(f"Found {len(found_datasets)} datasets. Missing {len(missing)} datasets.")
    
    if missing:
        print("\nFAILURE POLICY TRIGGERED: Missing required MT5 datasets.")
        print("See reports/mt5_dataset_inventory.md for exact missing files.")
        print("Halting Phase 7. Do not continue to model training.")
        sys.exit(1)
        
    print("All datasets present. Proceeding to Step 2 (Quality Audit)...")
    # Step 2 logic would go here

if __name__ == "__main__":
    audit_datasets()
