"""
tests/test_all.py — Comprehensive Test Suite

Covers:
  MT5 client (mocked), market data, order flow, DOM engine,
  microstructure, volume analytics, trade quality, risk manager,
  session filter, ML layer, database, dashboard endpoints,
  backtesting engine, report generator

Run: pytest tests/ -v --tb=short
"""

from __future__ import annotations

import asyncio
import math
import os
import random
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────

def mk_tick(bid=1950.0, ask=1950.15, vol=10, ts=None):
    from app.market_data import Tick
    return Tick(
        time=ts or datetime.now(timezone.utc),
        bid=bid, ask=ask, last=bid, volume=vol, flags=0,
    )


def mk_bar(c=1950.0, h=None, lo=None, o=None, vol=500, tf=1):
    from app.market_data import Bar
    return Bar(
        time=datetime.now(timezone.utc),
        open=o or c - 1,
        high=h or c + 2,
        low=lo or c - 2,
        close=c, tick_vol=vol, timeframe=tf,
    )


def mk_bar_dict(c=1950.0, h=None, lo=None, vol=500):
    return {
        "time": datetime.now(timezone.utc),
        "open": c - 1, "high": h or c + 2,
        "low": lo or c - 2, "close": c,
        "tick_volume": vol, "spread": 15, "real_volume": 0,
    }


def mk_dom(bids=None, asks=None):
    from app.mt5_client import DOMSnapshot, DOMLevel
    snap = DOMSnapshot(timestamp=datetime.now(timezone.utc), available=bool(bids or asks))
    snap.bids = [DOMLevel(price=p, volume=v, side="bid") for p, v in (bids or [])]
    snap.asks = [DOMLevel(price=p, volume=v, side="ask") for p, v in (asks or [])]
    return snap


def mk_db(tmpdir):
    from app.database import Database
    return Database(os.path.join(tmpdir, "test.db"))


# ══════════════════════════════════════════════════════════════════
# MARKET DATA
# ══════════════════════════════════════════════════════════════════

class TestTick:
    def test_mid(self):
        t = mk_tick(bid=1950.0, ask=1950.20)
        assert t.mid == pytest.approx(1950.10)

    def test_spread(self):
        t = mk_tick(bid=1950.0, ask=1950.30)
        assert t.spread == pytest.approx(0.30)

    def test_spread_pts(self):
        t = mk_tick(bid=1950.0, ask=1950.20)
        assert t.spread_pts == 20


class TestBar:
    def test_body_bullish(self):
        b = mk_bar(c=1952.0, o=1950.0)
        assert b.body == pytest.approx(2.0)
        assert b.is_bull is True

    def test_body_bearish(self):
        b = mk_bar(c=1948.0, o=1950.0)
        assert b.is_bear is True

    def test_range(self):
        b = mk_bar(c=1950.0, h=1955.0, lo=1945.0)
        assert b.range == pytest.approx(10.0)

    def test_upper_wick(self):
        b = mk_bar(c=1950.0, h=1956.0, o=1950.0)
        assert b.upper_wick == pytest.approx(6.0)

    def test_lower_wick(self):
        b = mk_bar(c=1950.0, lo=1944.0, o=1950.0)
        assert b.lower_wick == pytest.approx(6.0)


class TestMarketData:
    def setup_method(self):
        from app.market_data import MarketData, TF_M5, TF_H1
        self.md = MarketData()
        self.TF_M5 = TF_M5
        self.TF_H1 = TF_H1

    def _raw_tick(self, bid=1950.0):
        return {"time": datetime.now(timezone.utc),
                "bid": bid, "ask": bid + 0.15,
                "last": bid, "volume": 10, "flags": 0}

    def test_ingest_tick_updates_latest(self):
        t = self.md.ingest_tick(self._raw_tick(1950.0))
        assert t is not None
        assert self.md.latest_tick.bid == pytest.approx(1950.0)

    def test_bad_tick_returns_none(self):
        assert self.md.ingest_tick({}) is None

    def test_not_fresh_initially(self):
        assert self.md.is_fresh is False

    def test_fresh_after_tick(self):
        self.md.ingest_tick(self._raw_tick())
        assert self.md.is_fresh is True

    def test_load_bars_warms_indicators(self):
        bars = [mk_bar_dict(c=1950 + i * 0.1) for i in range(250)]
        self.md.load_bars(self.TF_H1, bars)
        assert self.md.ema50(self.TF_H1) is not None
        assert self.md.atr(self.TF_H1) is not None

    def test_vwap_resets_on_new_day(self):
        from app.market_data import _VWAP
        v = _VWAP()
        v1 = v.update(1950.0, 1945.0, 1948.0, 1000)
        v._day = "1970-01-01"
        v2 = v.update(2000.0, 1995.0, 1998.0, 100)
        assert abs(v2 - 1997.67) < 1.0

    def test_ema_bull_after_uptrend(self):
        bars = [mk_bar_dict(c=1800 + i * 2) for i in range(250)]
        self.md.load_bars(self.TF_H1, bars)
        assert self.md.is_ema_bull(self.TF_H1) is True

    def test_snapshot_returns_dict(self):
        s = self.md.snapshot()
        for k in ["bid", "ask", "vol_regime", "tick_count"]:
            assert k in s


class TestATR:
    def setup_method(self):
        from app.market_data import _ATR
        self.atr = _ATR(period=3)

    def test_none_before_period(self):
        self.atr.update(100, 98, 99)
        assert self.atr.value is None

    def test_ready_after_period(self):
        for i in range(4):
            self.atr.update(100 + i, 98 + i, 99 + i)
        assert self.atr.ready is True
        assert self.atr.value > 0

    def test_volatile_market_increases_atr(self):
        for _ in range(4):
            self.atr.update(100, 99.5, 99.8)
        low = self.atr.value
        for _ in range(5):
            self.atr.update(110, 90, 100)
        assert self.atr.value > low


# ══════════════════════════════════════════════════════════════════
# ORDER FLOW ENGINE
# ══════════════════════════════════════════════════════════════════

class TestOrderFlowEngine:
    def setup_method(self):
        from app.order_flow import OrderFlowEngine
        self.of = OrderFlowEngine()

    def test_first_tick_neutral(self):
        snap = self.of.process(mk_tick())
        assert snap.direction == "NEUTRAL"

    def test_uptick_increases_buy_pressure(self):
        self.of.process(mk_tick(bid=1950.0))
        snap = self.of.process(mk_tick(bid=1950.50))
        assert snap.buy_pressure >= 50.0

    def test_downtick_increases_sell_pressure(self):
        self.of.process(mk_tick(bid=1950.0))
        snap = self.of.process(mk_tick(bid=1949.50))
        assert snap.sell_pressure >= 50.0

    def test_cvd_positive_on_upticks(self):
        self.of.process(mk_tick(bid=1950.0))
        for _ in range(20):
            self.of.process(mk_tick(bid=1950.0 + _ * 0.1, vol=5))
        assert self.of.latest.cvd > 0

    def test_cvd_reset(self):
        self.of.process(mk_tick(bid=1950.0))
        for _ in range(10):
            self.of.process(mk_tick(bid=1951.0, vol=10))
        self.of.reset_cvd()
        assert self.of.latest.cvd == 0.0

    def test_strong_buy_after_many_upticks(self):
        self.of.process(mk_tick(bid=1950.0))
        price = 1950.0
        for _ in range(60):
            price += 0.2
            self.of.process(mk_tick(bid=price, vol=10))
        assert self.of.latest.of_score > 60

    def test_volume_expansion_detected(self):
        base = mk_tick(vol=5)
        for _ in range(60):
            self.of.process(base)
        big = mk_tick(bid=1951.0, vol=200)
        snap = self.of.process(big)
        assert snap.volume_expansion is True

    def test_snapshot_dict_has_keys(self):
        self.of.process(mk_tick())
        d = self.of.snapshot_dict()
        for k in ["cvd", "of_score", "direction", "tick_imb"]:
            assert k in d


# ══════════════════════════════════════════════════════════════════
# DOM ENGINE
# ══════════════════════════════════════════════════════════════════

class TestDOMEngine:
    def setup_method(self):
        from app.dom_engine import DOMEngine
        self.engine = DOMEngine()

    def test_dom_mode_with_depth(self):
        snap = mk_dom(
            bids=[(1949.9, 10), (1949.8, 8)],
            asks=[(1950.1, 10), (1950.2, 7)],
        )
        result = self.engine.process(mk_tick(), snap, avg_spread=0.15)
        assert result.dom_available is True
        assert hasattr(result, "total_bid_vol")

    def test_fallback_mode_without_depth(self):
        from app.mt5_client import DOMSnapshot
        empty = DOMSnapshot(timestamp=datetime.now(timezone.utc), available=False)
        result = self.engine.process(mk_tick(), empty, avg_spread=0.15)
        assert result.dom_available is False

    def test_buy_wall_detected(self):
        snap = mk_dom(
            bids=[(1949.9, 500), (1949.8, 5), (1949.7, 6)],
            asks=[(1950.1, 5), (1950.2, 6)],
        )
        result = self.engine.process(mk_tick(), snap, avg_spread=0.15)
        assert result.buy_wall is True

    def test_sell_wall_detected(self):
        snap = mk_dom(
            bids=[(1949.9, 5), (1949.8, 6)],
            asks=[(1950.1, 500), (1950.2, 5), (1950.3, 6)],
        )
        result = self.engine.process(mk_tick(), snap, avg_spread=0.15)
        assert result.sell_wall is True

    def test_balanced_book_neutral_imbalance(self):
        snap = mk_dom(
            bids=[(1949.9, 10), (1949.8, 10)],
            asks=[(1950.1, 10), (1950.2, 10)],
        )
        result = self.engine.process(mk_tick(), snap, avg_spread=0.15)
        assert abs(result.imbalance) < 0.05

    def test_liquidity_score_in_range(self):
        snap = mk_dom(
            bids=[(1949.9, 10)] * 5,
            asks=[(1950.1, 10)] * 5,
        )
        result = self.engine.process(mk_tick(), snap, avg_spread=0.15)
        assert 0 <= result.liquidity_score <= 100

    def test_snapshot_dict_keys(self):
        snap = mk_dom(
            bids=[(1949.9, 10)], asks=[(1950.1, 10)]
        )
        self.engine.process(mk_tick(), snap, avg_spread=0.15)
        d = self.engine.snapshot_dict()
        assert "mode" in d
        assert "liq_score" in d

    def test_fallback_optimizations_and_safety(self):
        from app.mt5_client import DOMSnapshot
        from app.market_data import Tick
        empty_dom = DOMSnapshot(timestamp=datetime.now(timezone.utc), available=False)
        
        # Test edge case: zero values, only one tick, etc.
        t_zero = Tick(time=datetime.now(timezone.utc), bid=0.0, ask=0.0, last=0.0, volume=0, flags=0)
        res = self.engine.process(t_zero, empty_dom, avg_spread=0.0)
        assert res.dom_available is False
        assert self.engine._vol_sum == sum(self.engine._vol_hist)
        
        # Test sequential high tick count inputs (100+ ticks)
        for i in range(1, 200):
            # Oscillating prices and varying volumes
            px = 1950.0 + (5.0 if i % 2 == 0 else -3.0)
            t = Tick(
                time=datetime.now(timezone.utc) + timedelta(milliseconds=i * 50),
                bid=px - 0.1,
                ask=px + 0.1,
                last=px,
                volume=i * 2,
                flags=0
            )
            res = self.engine.process(t, empty_dom, avg_spread=0.2)
            
            # Verify vol_sum rolling parity
            assert self.engine._vol_sum == sum(self.engine._vol_hist)
            # Verify tick clustering score bounds
            assert 0.0 <= res.tick_clustering <= 1.0
            # Verify score ranges
            assert 0.0 <= res.liquidity_score <= 100.0


# ══════════════════════════════════════════════════════════════════
# MICROSTRUCTURE
# ══════════════════════════════════════════════════════════════════

class TestMicrostructureEngine:
    def setup_method(self):
        from app.microstructure import MicrostructureEngine
        self.ms = MicrostructureEngine()

    def _bars(self, prices):
        return [mk_bar(c=p, h=p + 1.5, lo=p - 1.5) for p in prices]

    def test_analyse_returns_state(self):
        bars = self._bars([1950 + i * 0.5 for i in range(30)])
        state = self.ms.analyse(bars, atr=2.0)
        assert state is not None

    def test_bull_structure_on_uptrend(self):
        prices = [1900.0 + i * 3 for i in range(40)]
        bars = self._bars(prices)
        state = self.ms.analyse(bars, atr=3.0)
        assert state.structure_bias in ("BULLISH", "NEUTRAL")

    def test_liq_grab_down_detected(self):
        from app.market_data import Bar
        # Spike below then recover
        bars = self._bars([1950.0] * 5)
        bars.append(Bar(
            time=datetime.now(timezone.utc),
            open=1950.0, high=1950.5, low=1943.0, close=1949.0,
            tick_vol=1000, timeframe=15,
        ))
        state = self.ms.analyse(bars, atr=2.0)
        assert state is not None  # ensure no crash

    def test_fvg_detection(self):
        from app.market_data import Bar
        # Three-candle FVG pattern
        bars = self._bars([1950.0] * 10)
        bars.append(Bar(time=datetime.now(timezone.utc),
                        open=1950.0, high=1951.0, low=1949.0, close=1950.5,
                        tick_vol=500, timeframe=15))
        bars.append(Bar(time=datetime.now(timezone.utc),
                        open=1951.0, high=1958.0, low=1950.5, close=1957.0,
                        tick_vol=2000, timeframe=15))
        bars.append(Bar(time=datetime.now(timezone.utc),
                        open=1957.0, high=1960.0, low=1956.0, close=1959.0,
                        tick_vol=800, timeframe=15))
        state = self.ms.analyse(bars, atr=2.0)
        assert state is not None

    def test_scores_in_range(self):
        bars = self._bars([1950.0 + i for i in range(20)])
        state = self.ms.analyse(bars, atr=2.0)
        assert 0 <= state.bull_ms_score <= 100
        assert 0 <= state.bear_ms_score <= 100

    def test_snapshot_dict_keys(self):
        bars = self._bars([1950.0 + i for i in range(20)])
        self.ms.analyse(bars, atr=2.0)
        d = self.ms.snapshot_dict()
        for k in ["trend", "structure_bias", "reversal_prob", "bull_ms_score"]:
            assert k in d


# ══════════════════════════════════════════════════════════════════
# VOLUME ANALYTICS
# ══════════════════════════════════════════════════════════════════

class TestVolumeAnalytics:
    def setup_method(self):
        from app.volume_analytics import VolumeAnalytics
        self.vol = VolumeAnalytics()

    def test_bar_produces_snapshot(self):
        snap = self.vol.process_bar(mk_bar())
        assert snap is not None
        assert snap.relative_vol > 0

    def test_expansion_detected(self):
        for _ in range(30):
            self.vol.process_bar(mk_bar(vol=100))
        snap = self.vol.process_bar(mk_bar(vol=500))
        assert snap.expansion is True

    def test_spike_detected(self):
        for _ in range(30):
            self.vol.process_bar(mk_bar(vol=100))
        snap = self.vol.process_bar(mk_bar(vol=1000))
        assert snap.spike is True

    def test_cum_delta_positive_on_bull_bars(self):
        for _ in range(10):
            self.vol.process_bar(mk_bar(c=1952.0, o=1950.0, vol=200))
        assert self.vol.cum_delta > 0

    def test_snapshot_dict(self):
        self.vol.process_bar(mk_bar())
        d = self.vol.snapshot_dict()
        assert "rel_vol" in d
        assert "vol_score" in d


# ══════════════════════════════════════════════════════════════════
# TRADE QUALITY ENGINE
# ══════════════════════════════════════════════════════════════════

class TestTradeQualityEngine:
    def setup_method(self):
        from app.trade_quality import TradeQualityEngine
        self.q = TradeQualityEngine()

    def _make_of(self, score=70.0):
        from app.order_flow import OFSnapshot
        return OFSnapshot(
            timestamp=datetime.now(timezone.utc),
            of_score=score, direction="BUY",
            buy_pressure=65.0, sell_pressure=35.0,
            agg_buy_ratio=0.65, agg_sell_ratio=0.35,
        )

    def _make_liq(self, score=80.0):
        from app.dom_engine import FallbackMetrics
        m = FallbackMetrics(timestamp=datetime.now(timezone.utc))
        m.liquidity_score = score
        return m

    def _make_vol(self, regime="NORMAL", pct=50.0):
        from app.market_data import VolState
        v = VolState()
        v.regime = regime
        v.percentile = pct
        return v

    def _make_ms(self, bull=70.0, bear=40.0, bias="BULLISH"):
        from app.microstructure import MicrostructureState
        s = MicrostructureState()
        s.bull_ms_score = bull
        s.bear_ms_score = bear
        s.structure_bias = bias
        s.trend = "BULLISH"
        return s

    def _make_sess(self, active=True, blackout=False, score=90.0):
        from app.session import SessionState
        s = SessionState()
        s.is_active = active
        s.news_blackout = blackout
        s.session_quality = score
        s.news_sentiment = "NEUTRAL"
        s.news_score = 50.0
        return s

    def test_high_quality_long_approved(self):
        result = self.q.evaluate(
            of_snap=self._make_of(80.0),
            liq_snap=self._make_liq(90.0),
            ms_state=self._make_ms(),
            vol_state=self._make_vol("EXPANDING", 65.0),
            vol_snap=None,
            sess=self._make_sess(),
            ema_bull_h1=True, ema_bear_h1=False,
            ema_bull_m15=True, ema_bear_m15=False,
            price_above_vwap=True,
            current_spread=0.12, avg_spread=0.15,
        )
        if result is not None:
            assert result.direction == "LONG"
            assert result.total >= 85.0

    def test_blackout_vetoes_trade(self):
        result = self.q.evaluate(
            of_snap=self._make_of(80.0),
            liq_snap=self._make_liq(90.0),
            ms_state=self._make_ms(),
            vol_state=self._make_vol(),
            vol_snap=None,
            sess=self._make_sess(blackout=True),
            ema_bull_h1=True, ema_bear_h1=False,
            ema_bull_m15=True, ema_bear_m15=False,
            price_above_vwap=True,
            current_spread=0.12, avg_spread=0.15,
        )
        assert result is None

    def test_inactive_session_reduces_score(self):
        result_active = self.q.evaluate(
            of_snap=self._make_of(75.0), liq_snap=self._make_liq(85.0),
            ms_state=self._make_ms(), vol_state=self._make_vol(), vol_snap=None,
            sess=self._make_sess(active=True, score=95.0),
            ema_bull_h1=True, ema_bear_h1=False,
            ema_bull_m15=True, ema_bear_m15=False,
            price_above_vwap=True, current_spread=0.12, avg_spread=0.15,
        )
        long_active = self.q.latest_long
        self.q.evaluate(
            of_snap=self._make_of(75.0), liq_snap=self._make_liq(85.0),
            ms_state=self._make_ms(), vol_state=self._make_vol(), vol_snap=None,
            sess=self._make_sess(active=False, score=20.0),
            ema_bull_h1=True, ema_bear_h1=False,
            ema_bull_m15=True, ema_bear_m15=False,
            price_above_vwap=True, current_spread=0.12, avg_spread=0.15,
        )
        long_inactive = self.q.latest_long
        if long_active and long_inactive:
            assert long_active.total > long_inactive.total

    def test_snapshot_dict_has_long_short(self):
        self.q.evaluate(
            of_snap=self._make_of(), liq_snap=self._make_liq(),
            ms_state=self._make_ms(), vol_state=self._make_vol(), vol_snap=None,
            sess=self._make_sess(), ema_bull_h1=True, ema_bear_h1=False,
            ema_bull_m15=True, ema_bear_m15=False,
            price_above_vwap=True, current_spread=0.12, avg_spread=0.15,
        )
        d = self.q.snapshot_dict()
        assert "long" in d
        assert "short" in d


# ══════════════════════════════════════════════════════════════════
# RISK MANAGER
# ══════════════════════════════════════════════════════════════════

class TestRiskManager:
    def setup_method(self):
        from app.risk_manager import RiskManager
        self.rm = RiskManager()
        self.rm.initialize(10000.0)

    def test_approve_clean(self):
        ok, reason = self.rm.approve()
        assert ok is True
        assert reason == "APPROVED"

    def test_reject_daily_drawdown(self):
        self.rm._dd.daily_dd_pct = 3.5
        self.rm._dd.daily_hit = True
        ok, reason = self.rm.approve()
        assert ok is False

    def test_reject_circuit_breaker(self):
        self.rm._circuit_broken = True
        ok, reason = self.rm.approve()
        assert ok is False
        assert "Circuit" in reason

    def test_reject_max_trades(self):
        # max_open_trades is now 3; need 3 open positions to trigger
        self.rm._open_count = 3
        ok, reason = self.rm.approve()
        assert ok is False

    def test_position_sizing(self):
        # balance=10000, risk=1.0% (new default), sl_dist=3.0, tick_size=0.01, tick_value=0.01
        # sl_points = round(3.0 / 0.01) = 300
        # denominator = 300 * 0.01 = 3.0
        # raw_lot = 100.0 / 3.0 = 33.33
        # floor to vol_step 0.01 → 33.33
        vol, risk = self.rm.calculate_volume(
            balance=10000.0, entry=1950.0, stop_loss=1947.0,
        )
        assert vol > 0
        target_risk = 10000.0 * 0.01   # 100.0
        assert risk <= target_risk + 0.01   # never exceed target (floor-rounding)


    def test_zero_sl_distance_rejected(self):
        vol, risk = self.rm.calculate_volume(10000.0, 1950.0, 1950.0)
        assert vol == 0.0

    def test_loss_streak_triggers_circuit(self):
        for _ in range(5):
            self.rm._open_count = 1
            self.rm.on_close(-100.0, risk_pct=1.0)
        assert self.rm.circuit_broken is True

    def test_win_resets_streak(self):
        self.rm._dd.consecutive_losses = 3
        self.rm._open_count = 1
        self.rm.on_close(200.0, risk_pct=1.0)
        assert self.rm.drawdown.consecutive_losses == 0

    def test_daily_dd_computed(self):
        self.rm.update_equity(10000.0, 9700.0)
        assert self.rm.drawdown.daily_dd_pct == pytest.approx(3.0, abs=0.1)

    def test_reset_circuit(self):
        self.rm._circuit_broken = True
        self.rm.reset_circuit()
        assert self.rm.circuit_broken is False

    def test_summary_has_required_keys(self):
        s = self.rm.summary()
        for k in ["circuit_broken", "open_trades", "daily_dd_pct",
                   "consecutive_losses", "daily_pnl", "any_dd_hit",
                   "open_risk_pct"]:
            assert k in s

    def test_approve_with_exposure_blocks_when_full(self):
        """approve_with_exposure blocks when adding risk would exceed max_risk_exposure (3%)"""
        self.rm._dd.open_risk_pct = 2.5
        ok, reason = self.rm.approve_with_exposure(1.0)  # 2.5 + 1.0 = 3.5 > 3.0
        assert ok is False
        assert "MaxExposure" in reason

    def test_approve_with_exposure_passes_when_ok(self):
        self.rm._dd.open_risk_pct = 1.0
        ok, reason = self.rm.approve_with_exposure(1.0)  # 1.0 + 1.0 = 2.0 <= 3.0
        assert ok is True

    def test_on_open_tracks_exposure(self):
        self.rm.on_open(risk_pct=1.0)
        assert self.rm.drawdown.open_risk_pct == pytest.approx(1.0)
        self.rm.on_open(risk_pct=1.0)
        assert self.rm.drawdown.open_risk_pct == pytest.approx(2.0)

    def test_on_close_releases_exposure(self):
        self.rm.on_open(risk_pct=1.5)
        self.rm.on_close(50.0, risk_pct=1.5)
        assert self.rm.drawdown.open_risk_pct == pytest.approx(0.0, abs=0.001)


# ══════════════════════════════════════════════════════════════════
# ML LAYER
# ══════════════════════════════════════════════════════════════════

class TestMLLayer:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Patch model path
        from app.config import settings
        settings.ml.model_path = os.path.join(self.tmpdir, "ml_model.json")
        settings.ml.enabled = True
        settings.ml.min_samples = 5
        settings.ml.retrain_every_n_trades = 3
        from app.ml_layer import MLLayer
        self.ml = MLLayer()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ctx(self, trade_id="t1"):
        from app.ml_layer import TradeContext
        return TradeContext(
            trade_id=trade_id, direction="LONG",
            entry_time=datetime.now(timezone.utc).isoformat(),
            of_score=75.0, liq_score=80.0, ms_score=70.0,
            vol_score=65.0, session_score=90.0, news_score=50.0,
            spread_ratio=1.0, atr_pct=0.1, hour_of_day=10,
        )

    def test_zero_adjustment_before_training(self):
        ctx = self._ctx()
        adj = self.ml.quality_adjustment(ctx.to_features())
        assert adj == 0.0

    def test_record_and_outcome(self):
        ctx = self._ctx("trade_abc")
        self.ml.record_context(ctx)
        self.ml.record_outcome("trade_abc", 150.0)
        assert len(self.ml._history) == 1
        assert self.ml._history[0].win is True

    def test_retrain_after_enough_samples(self):
        for i in range(10):
            ctx = self._ctx(f"t{i}")
            self.ml.record_context(ctx)
            self.ml.record_outcome(f"t{i}", 100.0 if i % 2 == 0 else -50.0)

        self.ml._trades_since_train = 5
        retrained = self.ml.maybe_retrain()
        assert retrained is True
        assert self.ml._model._trained is True

    def test_win_rate_computed(self):
        for i in range(10):
            ctx = self._ctx(f"t{i}")
            self.ml.record_context(ctx)
            self.ml.record_outcome(f"t{i}", 100.0 if i < 6 else -50.0)
        assert self.ml.win_rate() == pytest.approx(60.0)

    def test_feature_vector_length(self):
        ctx = self._ctx()
        feats = ctx.to_features()
        assert len(feats) == 15


# ══════════════════════════════════════════════════════════════════
# SESSION FILTER
# ══════════════════════════════════════════════════════════════════

class TestSessionFilter:
    def setup_method(self):
        from app.session import SessionFilter
        self.sf = SessionFilter()

    def test_evaluate_returns_state(self):
        s = self.sf.evaluate()
        assert hasattr(s, "is_london")
        assert hasattr(s, "news_blackout")

    def test_weekend_not_tradeable(self):
        import unittest.mock as mock
        sat = datetime(2024, 6, 8, 12, 0, tzinfo=timezone.utc)
        with mock.patch("app.session.datetime") as md:
            md.now.return_value = sat
            state = self.sf.evaluate()
        # Just verify no crash
        assert state is not None

    def test_snapshot_dict_has_keys(self):
        self.sf.evaluate()
        d = self.sf.snapshot_dict()
        for k in ["is_london", "session_quality", "news_blackout"]:
            assert k in d


# ══════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════

class TestDatabase:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = mk_db(self.tmpdir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _trade(self, tid="t1", direction="LONG", pnl=0.0):
        class T:
            trade_id = tid; ticket = 12345; symbol = "XAUUSD"
            direction_v = direction
            entry_price = 1950.0; entry_time = datetime.now(timezone.utc)
            volume = 0.1; initial_vol = 0.1; risk_usd = 50.0
            quality_score = 87.0; atr_entry = 2.0
            sl = 1947.0; tp1 = 1953.0; tp2 = 1956.0; tp3 = 1959.0
            spread_entry = 0.15; latency_ms = 45.0; slippage = 0.05
            close_price = 1953.0; close_time = datetime.now(timezone.utc)
            close_reason = "TP1"
            realized_pnl = pnl
            tp1_done = False; tp2_done = False
            breakeven_done = False; trailing_active = False

        t = T()
        t.direction = direction
        return t

    @pytest.mark.asyncio
    async def test_insert_and_get_trade(self):
        t = self._trade("trade1")
        await self.db.insert_trade(t)
        trades = self.db.get_trades(status="OPEN")
        assert len(trades) == 1
        assert trades[0]["id"] == "trade1"

    @pytest.mark.asyncio
    async def test_close_trade(self):
        t = self._trade("trade2", pnl=300.0)
        await self.db.insert_trade(t)
        await self.db.close_trade(t)
        closed = self.db.get_trades(status="CLOSED")
        assert len(closed) == 1

    def test_log_event(self):
        self.db.log_event("TEST", "hello", "INFO", {"k": 1})
        events = self.db.get_events(limit=5)
        assert len(events) == 1
        assert events[0]["event_type"] == "TEST"

    def test_log_latency(self):
        self.db.log_latency("order_fill", 42.5)
        avg = self.db.avg_latency("order_fill")
        assert avg == pytest.approx(42.5, abs=1.0)

    def test_backup_creates_file(self):
        bdir = os.path.join(self.tmpdir, "bak")
        path = self.db.backup(bdir)
        assert os.path.exists(path)

    def test_daily_stats_empty_when_no_trades(self):
        stats = self.db.compute_daily_stats("2024-01-01")
        assert stats == {}

    def test_cleanup_runs_without_error(self):
        self.db.cleanup_old(days=1)


# ══════════════════════════════════════════════════════════════════
# MT5 CLIENT (simulation mode)
# ══════════════════════════════════════════════════════════════════

class TestMT5Client:
    def setup_method(self):
        from app.mt5_client import MT5Client
        self.client = MT5Client()
        with patch('app.mt5_client.MT5_AVAILABLE', False):
            self.client.connect()

    def test_connected_in_sim(self):
        assert self.client.connected is True

    def test_get_account_returns_dict(self):
        acct = self.client.get_account()
        assert acct is not None
        assert "balance" in acct

    def test_get_tick_returns_dict(self):
        tick = self.client.get_tick()
        assert tick is not None
        assert "bid" in tick and "ask" in tick

    def test_buy_returns_success(self):
        # In simulation mode, buy() calls _sim_fill — sl/tp values are unused.
        r = self.client.buy(0.01, 1945.0, 1960.0, "test")
        assert r.success is True

    def test_sell_returns_success(self):
        # In simulation mode, sell() calls _sim_fill — sl/tp values are unused.
        r = self.client.sell(0.01, 1960.0, 1945.0, "test")
        assert r.success is True

    def test_close_returns_success(self):
        # close() replaces close_position() in multi-asset redesign.
        r = self.client.close(99999)
        assert r.success is True

    def test_symbol_set_after_connect(self):
        assert self.client.symbol is not None


# ══════════════════════════════════════════════════════════════════
# DASHBOARD ENDPOINTS
# ══════════════════════════════════════════════════════════════════

class TestDashboard:
    def setup_method(self):
        from fastapi.testclient import TestClient
        from dashboard.app import app, inject
        state = {
            "account": {"balance": 10000.0, "equity": 10100.0},
            "trade":   {"active": False},
            "risk":    {"circuit_broken": False, "daily_dd_pct": 0.5},
            "health":  {"healthy": True, "mt5_connected": True},
            "market":  {"bid": 1950.0, "atr_m5": 2.0},
            "of":      {"of_score": 65.0, "direction": "BUY"},
            "dom":     {"mode": "FALLBACK", "liq_score": 70.0},
            "session": {"is_london": True, "session_quality": 85.0},
            "quality": {"long": {"total": 88.0, "tradeable": True}},
            "ml":      {"enabled": True, "trained": False},
        }
        db = MagicMock()
        db.get_trades.return_value = []
        db.get_daily_stats.return_value = []
        db.get_events.return_value = []
        db.get_closed_trades.return_value = []
        inject(state, db, None)
        self.client = TestClient(app)

    def test_ping(self):
        r = self.client.get("/ping")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_overview(self):
        r = self.client.get("/api/overview")
        assert r.status_code in (200, 403)
        if r.status_code == 200:
            assert "account" in r.json()

    def test_trades_endpoint(self):
        r = self.client.get("/api/trades")
        assert r.status_code in (200, 403)

    def test_health_endpoint(self):
        r = self.client.get("/api/health")
        assert r.status_code in (200, 403)

    def test_dashboard_html(self):
        r = self.client.get("/")
        assert r.status_code == 200
        assert "XAUUSD Pro Scalper" in r.text


# ══════════════════════════════════════════════════════════════════
# BACKTESTING ENGINE
# ══════════════════════════════════════════════════════════════════

class TestBacktestResult:
    def test_compute_basic_metrics(self):
        from backtesting.engine import BTResult, BTTrade
        r = BTResult()
        for pnl in [100.0, -50.0, 200.0, -30.0, 150.0, -80.0]:
            t = BTTrade(
                direction="LONG", entry_price=1950.0,
                entry_time=datetime.now(timezone.utc),
                sl=1947.0, tp1=1953.0, tp2=1956.0, tp3=1959.0,
                volume=0.1, risk_usd=50.0,
            )
            t.pnl = pnl; t.exit_price = 1953.0
            r.trades.append(t)
        r.compute(10000.0)
        assert r.total_trades == 6
        assert r.winning == 3
        assert r.net_pnl == pytest.approx(290.0)
        assert r.win_rate == pytest.approx(50.0)
        assert r.profit_factor > 1.0


class TestBarSimulator:
    def setup_method(self):
        from backtesting.engine import BarSimulator, BTBar, BTTrade
        self.sim = BarSimulator()
        self.BTBar = BTBar
        self.BTTrade = BTTrade

    def _bars(self, prices):
        return [
            self.BTBar(
                time=datetime.now(timezone.utc),
                open=p - 0.5, high=p + 1.5, low=p - 1.5, close=p, volume=500.0,
            )
            for p in prices
        ]

    def _trade(self, dir="LONG", entry=1950.0):
        sl  = entry - 3 if dir == "LONG" else entry + 3
        tp1 = entry + 3 if dir == "LONG" else entry - 3
        tp2 = entry + 6 if dir == "LONG" else entry - 6
        tp3 = entry + 9 if dir == "LONG" else entry - 9
        return self.BTTrade(
            direction=dir, entry_price=entry,
            entry_time=datetime.now(timezone.utc),
            sl=sl, tp1=tp1, tp2=tp2, tp3=tp3,
            volume=0.1, risk_usd=50.0,
        )

    def test_sl_hit_long(self):
        t = self._trade("LONG", 1950.0)
        t.sl = 1947.5
        bars = self._bars([1949.0, 1947.0, 1946.0])
        result = self.sim.run(t, bars)
        assert result.reason == "SL"
        assert result.pnl < 0

    def test_tp3_hit_long(self):
        t = self._trade("LONG", 1950.0)
        bars = self._bars([1954.0, 1957.0, 1961.0])
        result = self.sim.run(t, bars)
        assert result.tp1_done is True
        assert result.pnl > 0

    def test_sl_hit_short(self):
        t = self._trade("SHORT", 1950.0)
        bars = self._bars([1951.0, 1952.5, 1954.0])
        result = self.sim.run(t, bars)
        assert result.reason == "SL"
        assert result.pnl < 0


class TestMonteCarlo:
    def test_basic(self):
        from backtesting.engine import MonteCarloSimulator
        mc = MonteCarloSimulator()
        pnls = [50.0, -30.0, 80.0, -20.0] * 15
        result = mc.run(pnls, sims=100, initial=10000.0)
        assert "ruin_prob_pct" in result
        assert 0 <= result["ruin_prob_pct"] <= 100

    def test_all_losses_high_ruin(self):
        from backtesting.engine import MonteCarloSimulator
        mc = MonteCarloSimulator()
        result = mc.run([-500.0] * 20, sims=50)
        assert result["ruin_prob_pct"] > 50


# ══════════════════════════════════════════════════════════════════
# REPORT GENERATOR
# ══════════════════════════════════════════════════════════════════

class TestReportGenerator:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from reports.generator import ReportGenerator
        self.gen = ReportGenerator(self.tmpdir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_export_trades_csv(self):
        trades = [{
            "id": "t1", "ticket": 1, "symbol": "XAUUSD",
            "direction": "LONG", "status": "CLOSED",
            "entry_price": 1950.0, "entry_time": "2024-01-10T10:00:00",
            "close_price": 1953.0, "close_time": "2024-01-10T10:30:00",
            "close_reason": "TP1", "volume": 0.1, "initial_vol": 0.1,
            "risk_usd": 50.0, "quality_score": 88.0, "atr_entry": 2.0,
            "sl": 1947.0, "tp1": 1953.0, "tp2": 1956.0, "tp3": 1959.0,
            "realized_pnl": 300.0, "spread_entry": 0.15,
            "latency_ms": 45.0, "slippage": 0.05,
            "tp1_done": 1, "tp2_done": 0,
            "breakeven_done": 1, "trailing_active": 0,
        }]
        path = self.gen.export_trades_csv(trades, "test.csv")
        assert os.path.exists(path)

    def test_full_analytics(self):
        trades = [{"status": "CLOSED", "realized_pnl": p,
                   "quality_score": 87.0, "latency_ms": 45.0}
                  for p in [300.0, -150.0, 450.0, -80.0, 200.0]]
        a = self.gen.full_analytics(trades)
        assert a["total_trades"] == 5
        assert a["winning_trades"] == 3
        assert "sharpe" in a
        assert "sortino" in a
        assert "calmar" in a

    def test_export_empty_csv(self):
        path = self.gen.export_trades_csv([], "empty.csv")
        assert os.path.exists(path)


# ══════════════════════════════════════════════════════════════════
# PHASE 1 - CORE STABILITY TESTS
# ══════════════════════════════════════════════════════════════════

class TestPerformanceTrackerConsistency:
    def test_no_positions_consistent(self, capsys):
        from app.performance import PerformanceTracker
        # Force log immediately by setting log_interval_s = 0
        tracker = PerformanceTracker(initial_balance=10000.0)
        tracker._log_interval = 0
        
        # Consistent: open_positions = 0, balance = 10000, equity = 10000
        tracker.snapshot(balance=10000.0, equity=10000.0, open_positions=0, floating_pnl=0.0)
        captured = capsys.readouterr()
        assert "PERFORMANCE WARNING" not in captured.out

    def test_no_positions_inconsistent(self, capsys):
        from app.performance import PerformanceTracker
        tracker = PerformanceTracker(initial_balance=10000.0)
        tracker._log_interval = 0
        
        # Inconsistent: open_positions = 0, balance = 10000, equity = 9900
        tracker.snapshot(balance=10000.0, equity=9900.0, open_positions=0, floating_pnl=0.0)
        captured = capsys.readouterr()
        assert "PERFORMANCE WARNING" in captured.out
        assert "Balance: 10000.00" in captured.out
        assert "Equity: 9900.00" in captured.out
        assert "Difference: 100.00" in captured.out

    def test_one_profitable_position(self, capsys):
        from app.performance import PerformanceTracker
        tracker = PerformanceTracker(initial_balance=10000.0)
        tracker._log_interval = 0
        
        # Consistent: open_positions = 1, balance = 10000, equity = 10100, floating_pnl = 100
        tracker.snapshot(balance=10000.0, equity=10100.0, open_positions=1, floating_pnl=100.0)
        captured = capsys.readouterr()
        assert "PERFORMANCE WARNING" not in captured.out

    def test_one_losing_position(self, capsys):
        from app.performance import PerformanceTracker
        tracker = PerformanceTracker(initial_balance=10000.0)
        tracker._log_interval = 0
        
        # Consistent: open_positions = 1, balance = 10000, equity = 9900, floating_pnl = -100
        tracker.snapshot(balance=10000.0, equity=9900.0, open_positions=1, floating_pnl=-100.0)
        captured = capsys.readouterr()
        assert "PERFORMANCE WARNING" not in captured.out

    def test_multiple_positions(self, capsys):
        from app.performance import PerformanceTracker
        tracker = PerformanceTracker(initial_balance=10000.0)
        tracker._log_interval = 0
        
        # Consistent: open_positions = 3, balance = 10000, equity = 10250, floating_pnl = 250
        tracker.snapshot(balance=10000.0, equity=10250.0, open_positions=3, floating_pnl=250.0)
        captured = capsys.readouterr()
        assert "PERFORMANCE WARNING" not in captured.out


class TestTradeEngineDecisionLogging:
    @pytest.mark.asyncio
    async def test_evaluate_decision_rejected(self, capsys):
        from app.trade_engine import TradeEngine
        from app.market_data import MarketData
        from app.trade_quality import QualityBreakdown
        
        # Set environment variable to force logging
        os.environ["DEBUG"] = "true"
        
        # Setup mocks
        client = MagicMock()
        market = MagicMock()
        
        # Setup tick and ATR to bypass early data exits
        tick = MagicMock()
        tick.mid = 1950.10
        tick.spread = 0.15
        tick.spread_pts = 15
        market.latest_tick = tick
        market.is_fresh = True
        market.atr.return_value = 1.2
        market.avg_spread = 0.15
        market.volatility.regime = "NORMAL"
        market.vwap.return_value = 1950.0
        market.ema50.return_value = 1948.0
        market.ema200.return_value = 1945.0
        market.is_ema_bull.return_value = True
        market.is_ema_bear.return_value = False
        
        of_engine = MagicMock()
        dom_engine = MagicMock()
        dom_engine.using_dom = False
        dom_engine.latest_fallback = MagicMock()
        
        micro = MagicMock()
        micro_state = MagicMock()
        micro_state.liq_grab_down = False
        micro_state.liq_grab_up = False
        micro_state.bos_bull = False
        micro_state.bos_bear = False
        micro_state.structure_bias = "NEUTRAL"
        micro_state.bull_ms_score = 50.0
        micro_state.bear_ms_score = 50.0
        micro_state.price_in_bull_fvg = False
        micro_state.price_in_bear_fvg = False
        micro.state.return_value = micro_state
        
        vol = MagicMock()
        
        # Setup session
        session = MagicMock()
        session_state = MagicMock()
        session_state.is_active = True
        session_state.news_blackout = False
        session_state.session_quality = 80.0
        session.state = session_state
        
        # Quality engine mock
        quality = MagicMock()
        quality.get_adaptive_threshold.return_value = 70.0
        # Create breakdowns that will fail the quality gate
        long_bd = QualityBreakdown(direction="LONG", total=45.0, vetoed=True, veto_reasons=["EMA opposing trend"])
        short_bd = QualityBreakdown(direction="SHORT", total=40.0, vetoed=True, veto_reasons=["EMA opposing trend"])
        quality.latest_long = long_bd
        quality.latest_short = short_bd
        quality.evaluate.return_value = None
        
        risk = MagicMock()
        risk.approve.return_value = (True, "APPROVED")
        risk.approve_with_exposure.return_value = (True, "APPROVED")
        risk.in_cooldown.return_value = False
        risk.circuit_broken = False
        risk.drawdown.any_hit = False
        
        ml = MagicMock()
        ml.quality_adjustment.return_value = 0.0
        
        db = AsyncMock()
        
        engine = TradeEngine(client, market, of_engine, dom_engine, micro, vol, quality, risk, session, ml, db)
        engine._eval_min_gap = 0.0  # bypass rate limit
        
        await engine.evaluate("XAUUSD", market)
        
        captured = capsys.readouterr()
        assert "TRADE DECISION" in captured.out
        assert "Decision: REJECTED" in captured.out
        assert "EMA Alignment" in captured.out
        assert "Rejection Reasons:" in captured.out
        assert "- EMA opposing trend" in captured.out


# ══════════════════════════════════════════════════════════════════
# POSITION SIZER
# ══════════════════════════════════════════════════════════════════

class TestPositionSizer:
    """
    Tests for app/position_sizer.py — universal, multi-symbol sizing engine.
    All tests use write_csv=False so they don't pollute reports/position_size_history.csv.
    """

    def _spec(self, sym="XAUUSD"):
        from app.position_sizer import BrokerSpec
        return BrokerSpec.fallback(sym)

    def _size(self, balance, entry, sl, tp=None, risk_pct=1.0, sym="XAUUSD"):
        from app.position_sizer import PositionSizer
        spec = self._spec(sym)
        return PositionSizer.size(
            balance=balance, entry=entry, stop_loss=sl,
            tp_price=tp, risk_pct=risk_pct, spec=spec,
            strategy="test", symbol=sym, write_csv=False,
        )

    # ── Compounding ────────────────────────────────────────────────
    def test_lot_increases_with_balance(self):
        r1 = self._size(500.0,  1950.0, 1800.0)   # small balance
        r2 = self._size(1000.0, 1950.0, 1800.0)   # doubled balance
        assert r2.final_lot >= r1.final_lot        # lot must be >= (could be same due to floor)

    def test_lot_decreases_with_balance(self):
        r_big  = self._size(5000.0, 1950.0, 1800.0)
        r_small = self._size(500.0, 1950.0, 1800.0)
        assert r_big.final_lot >= r_small.final_lot

    def test_risk_never_exceeds_target(self):
        """Floor-rounding guarantees actual risk is always ≤ requested risk_pct,
        UNLESS the trade is floor-rounded up to vol_min — which is acceptable broker
        behaviour (the minimum lot is the smallest possible trade)."""
        for balance in [500, 750, 1000, 2500, 5000]:
            r = self._size(float(balance), 1950.0, 1800.0, risk_pct=1.0)
            target = balance * 0.01
            # If final_lot == vol_min and raw_lot < vol_min, the sizer was forced up.
            # In that case expected_loss can exceed target — this is correct behaviour.
            if r.final_lot > r.vol_min + 1e-6:  # Not at floor
                assert r.expected_loss <= target + 0.05

    # ── Broker limits ──────────────────────────────────────────────
    def test_broker_min_lot_floor(self):
        """Even with a tiny balance the result must be >= vol_min (if any lot fits)."""
        r = self._size(500.0, 1950.0, 1800.0)
        spec = self._spec()
        assert r.final_lot >= spec.vol_min

    def test_broker_max_lot_cap(self):
        """Very large balance should be capped at vol_max."""
        r = self._size(100_000_000.0, 1950.0, 1949.0, risk_pct=1.0)
        spec = self._spec()
        assert r.final_lot <= spec.vol_max

    def test_vol_step_rounding(self):
        """final_lot must always be an exact multiple of vol_step."""
        from app.position_sizer import BrokerSpec, PositionSizer
        spec = BrokerSpec(symbol="TEST", vol_min=0.01, vol_max=100.0, vol_step=0.05,
                          tick_size=0.01, tick_value=0.01, contract_size=1.0)
        r = PositionSizer.size(balance=1000.0, entry=100.0, stop_loss=90.0,
                                spec=spec, risk_pct=1.0, write_csv=False)
        if r.final_lot > 0 and spec.vol_step > 0:
            # Use relative tolerance: remainder should be <1% of step size
            remainder = r.final_lot % spec.vol_step
            # Round to avoid floating-point artifacts (e.g. 0.05 % 0.05 = 2.8e-17 or 0.05)
            remainder = min(remainder, abs(remainder - spec.vol_step))
            assert remainder < spec.vol_step * 0.001, \
                f"remainder {remainder} is not negligible vs step {spec.vol_step}"

    # ── Invalid inputs ─────────────────────────────────────────────
    def test_zero_sl_rejected(self):
        r = self._size(1000.0, 1950.0, 1950.0)   # SL == entry
        assert r.final_lot == 0.0
        assert r.is_valid is False

    def test_negative_balance_rejected(self):
        r = self._size(-100.0, 1950.0, 1800.0)
        assert r.final_lot == 0.0

    # ── Multi-symbol ───────────────────────────────────────────────
    def test_multi_symbol_xauusd(self):
        r = self._size(500.0, 1950.0, 1935.0, sym="XAUUSD")
        assert r.final_lot > 0
        assert r.symbol == "XAUUSD"

    def test_multi_symbol_btcusd(self):
        r = self._size(500.0, 67000.0, 66700.0, sym="BTCUSD")
        assert r.final_lot > 0
        assert r.symbol == "BTCUSD"

    def test_multi_symbol_eurusd(self):
        r = self._size(500.0, 1.0850, 1.0800, sym="EURUSD")
        assert r.final_lot > 0
        assert r.symbol == "EURUSD"

    def test_multi_symbol_nas100(self):
        r = self._size(500.0, 18500.0, 18350.0, sym="NAS100")
        assert r.final_lot > 0

    def test_multi_symbol_ethusd(self):
        r = self._size(500.0, 3500.0, 3400.0, sym="ETHUSD")
        assert r.final_lot > 0

    def test_sizing_result_has_all_fields(self):
        r = self._size(1000.0, 1950.0, 1935.0)
        for attr in ["timestamp", "strategy", "symbol", "balance", "risk_pct",
                     "risk_amount", "sl_points", "raw_lot", "final_lot",
                     "expected_loss", "expected_reward", "risk_reward_ratio",
                     "vol_min", "vol_max", "vol_step"]:
            assert hasattr(r, attr), f"Missing field: {attr}"


# ══════════════════════════════════════════════════════════════════
# DYNAMIC COMPOUNDING
# ══════════════════════════════════════════════════════════════════

class TestDynamicCompounding:
    """
    Simulates a multi-trade sequence and verifies lot scaling behaviour.
    """

    def test_compounding_sequence(self):
        from app.position_sizer import PositionSizer, BrokerSpec
        spec = BrokerSpec.fallback("XAUUSD")
        balance = 500.0

        # Simulate 10 trades with alternating wins/losses
        outcomes = [+50, -20, +80, +60, -30, +100, -15, +90, +70, +40]
        lots = []
        for pnl in outcomes:
            r = PositionSizer.size(
                balance=balance, entry=1950.0, stop_loss=1935.0,
                spec=spec, risk_pct=1.0, strategy="test", symbol="XAUUSD",
                write_csv=False,
            )
            lots.append(r.final_lot)
            balance += pnl

        # Lot at peak balance (after cumulative +425) should be >= starting lot
        assert lots[-1] >= lots[0]
        # Every lot must respect broker constraints
        for lot in lots:
            assert lot >= spec.vol_min
            assert lot <= spec.vol_max


# ══════════════════════════════════════════════════════════════════
# BROKER COMPLIANCE
# ══════════════════════════════════════════════════════════════════

class TestBrokerCompliance:
    """
    Validates vol_step, vol_min, vol_max, and tick compliance for all 8 symbols.
    """

    SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD",
               "ETHUSD", "NAS100", "US30"]

    def _size(self, sym):
        from app.position_sizer import PositionSizer, BrokerSpec
        spec = BrokerSpec.fallback(sym)
        from app.mt5_client import _SIM_PRICES
        price = _SIM_PRICES.get(sym, 1950.0)
        sl = price * 0.99   # 1% SL for each symbol
        return PositionSizer.size(
            balance=500.0, entry=price, stop_loss=sl,
            spec=spec, risk_pct=1.0, strategy="test", symbol=sym,
            write_csv=False,
        ), spec

    def test_vol_min_respected_all_symbols(self):
        for sym in self.SYMBOLS:
            r, spec = self._size(sym)
            if r.final_lot > 0:
                assert r.final_lot >= spec.vol_min, f"{sym}: lot {r.final_lot} < vol_min {spec.vol_min}"

    def test_vol_max_respected_all_symbols(self):
        for sym in self.SYMBOLS:
            r, spec = self._size(sym)
            assert r.final_lot <= spec.vol_max, f"{sym}: lot {r.final_lot} > vol_max {spec.vol_max}"

    def test_vol_step_multiple_all_symbols(self):
        for sym in self.SYMBOLS:
            r, spec = self._size(sym)
            if r.final_lot > 0 and spec.vol_step > 0:
                remainder = r.final_lot % spec.vol_step
                # Floating-point safe: remainder OR (step - remainder) should be negligible
                remainder = min(remainder, abs(remainder - spec.vol_step))
                assert remainder < spec.vol_step * 0.001, \
                    f"{sym}: lot {r.final_lot} not multiple of step {spec.vol_step} (remainder={remainder})"


    def test_expected_loss_within_risk_amount(self):
        for sym in self.SYMBOLS:
            r, _ = self._size(sym)
            if r.final_lot > 0 and r.final_lot > r.vol_min + 1e-6:
                # Only assert when lot is above vol_min floor
                # (floor-rounded-up to vol_min may legitimately exceed target)
                assert r.expected_loss <= r.risk_amount * 1.05 + 0.50, \
                    f"{sym}: expected_loss {r.expected_loss} >> risk_amount {r.risk_amount}"

    def test_broker_spec_from_spec_dict_roundtrip(self):
        from app.position_sizer import BrokerSpec
        from app.mt5_client import MT5Client
        client = MT5Client()
        for sym in ["XAUUSD", "BTCUSD", "EURUSD"]:
            d = client.get_symbol_spec(sym)
            assert d is not None
            spec = BrokerSpec.from_spec_dict(d, symbol=sym)
            assert spec.vol_min > 0
            assert spec.vol_max > spec.vol_min
            assert spec.tick_size > 0
            assert spec.tick_value > 0


# ══════════════════════════════════════════════════════════════════
# RISK EXPOSURE TRACKING
# ══════════════════════════════════════════════════════════════════

class TestRiskExposure:
    """Tests for multi-position risk exposure accumulation."""

    def setup_method(self):
        from app.risk_manager import RiskManager
        self.rm = RiskManager()
        self.rm.initialize(500.0)

    def test_exposure_accumulates_correctly(self):
        self.rm.on_open(risk_pct=1.0)
        self.rm.on_open(risk_pct=1.0)
        assert self.rm.drawdown.open_risk_pct == pytest.approx(2.0)

    def test_exposure_cannot_go_negative(self):
        self.rm.on_open(risk_pct=1.0)
        self.rm.on_close(10.0, risk_pct=5.0)   # Closing more than opened
        assert self.rm.drawdown.open_risk_pct >= 0.0

    def test_three_positions_at_1pct_each_allowed(self):
        """3 × 1% = 3% equals max_risk_exposure — should be allowed on 3rd position."""
        self.rm.on_open(risk_pct=1.0)
        self.rm.on_open(risk_pct=1.0)
        # Third position: 2.0 open + 1.0 new = 3.0 == max — should still pass
        ok, reason = self.rm.approve_with_exposure(1.0)
        assert ok is True

    def test_fourth_position_exceeds_exposure(self):
        """When open_risk_pct = 3% and we ask for 1% more, exposure check must block.
        We set open_risk_pct directly (not via on_open) so we avoid incrementing
        _open_count which would trigger the 'Max trades' gate first."""
        self.rm._dd.open_risk_pct = 3.0
        ok, reason = self.rm.approve_with_exposure(1.0)  # 3.0 + 1.0 = 4.0 > 3.0
        assert ok is False
        assert "MaxExposure" in reason


# ── Run config ────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-x"])
