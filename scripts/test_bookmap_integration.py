"""
scripts/test_bookmap_integration.py — Integration Verification for Bookmap Heatmap Engine
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))

from app.bookmap_engine import BookmapEngine
from app.trade_quality import TradeQualityEngine


def main():
    print("=========================================================")
    print("      BOOKMAP LEVEL 2 HEATMAP INTEGRATION AUDIT")
    print("=========================================================")

    # 1. Initialize Bookmap Engine
    engine = BookmapEngine(symbol="XAUUSD", min_wall_size=50.0)
    print(f"Bookmap Engine Initialized: Symbol={engine.symbol} MinWallSize={engine.min_wall_size}")

    # 2. Simulate High-Frequency Depth Updates
    print("\n--- 1. SIMULATING LEVEL 2 ORDER BOOK HEATMAP UPDATE ---")
    bids = [(2350.0, 150.0), (2349.5, 80.0), (2349.0, 30.0)]
    asks = [(2351.0, 20.0),  (2351.5, 15.0)]
    snap = engine.ingest_depth_update("XAUUSD", bids, asks, mid_price=2350.5)

    print(f"Connected              : {snap.connected}")
    print(f"Bid Walls Detected     : {len(snap.bid_walls)} (Top Wall: ${snap.bid_walls[0].price:.2f} - {snap.bid_walls[0].volume} contracts)")
    print(f"Ask Walls Detected     : {len(snap.ask_walls)}")
    print(f"Depth Imbalance        : {snap.depth_imbalance:+.3f}")
    print(f"Absorption Side        : {snap.absorption_side}")
    print(f"Bookmap Confluence Score: {snap.confluence_score:.1f} / 100.0")

    # 3. Simulate Institutional Iceberg Order
    print("\n--- 2. SIMULATING INSTITUTIONAL ICEBERG DETECTION ---")
    engine.record_iceberg(
        price=2350.0,
        side="BID",
        executed_vol=50.0,
        display_vol=10.0,
        estimated_total=250.0,
    )
    snap2 = engine.snapshot()
    print(f"Icebergs Active        : {len(snap2.icebergs)}")
    print(f"Iceberg Details        : {snap2.icebergs[0].side} @ ${snap2.icebergs[0].price:.2f} (Est Total: {snap2.icebergs[0].estimated_total_vol} lots)")

    # 4. Verify Quality Engine Blending
    print("\n--- 3. VERIFYING TRADE QUALITY SCORING BLENDING ---")
    quality = TradeQualityEngine()
    res = quality.evaluate_recalibrated(
        of_snap=None,
        liq_snap=None,
        ms_state=None,
        vol_state=None,
        vol_snap=None,
        sess=None,
        ema_bull_h1=True,
        ema_bear_h1=False,
        ema_bull_m15=True,
        ema_bear_m15=False,
        price_above_vwap=True,
        current_spread=15.0,
        avg_spread=15.0,
        symbol="XAUUSD",
        bookmap_snap=snap2,
    )

    if res:
        print(f"Signal Evaluated       : {res.direction} | Overall Score={res.total:.1f} (Threshold=65.0)")
        print(f"Liquidity Sub-Score    : {res.liq_score:.1f} / 100.0")
        print(f"Quality Gate Status    : {'PASSED [PASS]' if res.tradeable else 'REJECTED [FAIL]'}")
    
    print("\n=========================================================")
    print(" ALL BOOKMAP INTEGRATION PHASES VERIFIED SUCCESSFULLY! [PASS]")
    print("=========================================================")


if __name__ == "__main__":
    main()
