"""
tests/test_bookmap.py — PyTest Suite for Bookmap Engine & Heatmap Integration
"""

from __future__ import annotations

import pytest
from app.bookmap_engine import BookmapEngine, BookmapSnapshot, LiquidityWall, IcebergOrder
from app.trade_quality import TradeQualityEngine


def test_bookmap_engine_initialization():
    engine = BookmapEngine(symbol="XAUUSD", min_wall_size=50.0)
    assert engine.symbol == "XAUUSD"
    assert engine.min_wall_size == 50.0
    snap = engine.snapshot()
    assert isinstance(snap, BookmapSnapshot)
    assert snap.symbol == "XAUUSD"


def test_bookmap_liquidity_wall_detection():
    engine = BookmapEngine(symbol="XAUUSD", min_wall_size=50.0)
    bids = [(2350.0, 100.0), (2349.5, 20.0), (2349.0, 75.0)]
    asks = [(2351.0, 120.0), (2351.5, 10.0)]
    
    snap = engine.ingest_depth_update("XAUUSD", bids, asks, mid_price=2350.5)
    assert snap.connected is True
    assert len(snap.bid_walls) == 2   # 100.0 and 75.0
    assert len(snap.ask_walls) == 1   # 120.0
    assert snap.bid_walls[0].price == 2350.0
    assert snap.ask_walls[0].price == 2351.0
    assert snap.confluence_score > 50.0


def test_bookmap_iceberg_recording():
    engine = BookmapEngine(symbol="XAUUSD")
    engine.record_iceberg(
        price=2350.0,
        side="BID",
        executed_vol=40.0,
        display_vol=10.0,
        estimated_total=150.0,
    )
    snap = engine.snapshot()
    assert len(snap.icebergs) == 1
    assert snap.icebergs[0].price == 2350.0
    assert snap.icebergs[0].estimated_total_vol == 150.0


def test_bookmap_quality_engine_blending():
    quality_engine = TradeQualityEngine()
    engine = BookmapEngine(symbol="XAUUSD", min_wall_size=50.0)
    
    bids = [(2350.0, 200.0)]
    asks = [(2351.0, 10.0)]
    snap = engine.ingest_depth_update("XAUUSD", bids, asks, mid_price=2350.5)
    
    # Evaluate quality with Bookmap snapshot passed
    res = quality_engine.evaluate_recalibrated(
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
        bookmap_snap=snap,
    )
    assert res is not None
    assert res.liq_score > 0
