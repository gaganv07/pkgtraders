"""
app/market_data.py — Market Data Engine

Processes live tick stream and OHLCV bars.
Computes: ATR, EMA50/200, VWAP (session), realized/rolling volatility,
volatility percentile, spread tracking, daily range.

Multi-asset upgrade: adds MultiSymbolMarketData registry which holds
one MarketData instance per enabled symbol.
"""

import logging
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

# Timeframe constants (match MT5 TIMEFRAME_* values)
TF_M1  = 1
TF_M5  = 5
TF_M15 = 15
TF_H1  = 60


# ── Primitive models ──────────────────────────────────────────────

@dataclass
class Tick:
    time:   datetime
    bid:    float
    ask:    float
    last:   float
    volume: int
    flags:  int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_pts(self) -> int:
        return round(self.spread * 100)


@dataclass
class Bar:
    time:       datetime
    open:       float
    high:       float
    low:        float
    close:      float
    tick_vol:   int
    spread:     float = 0.0
    real_vol:   int   = 0
    timeframe:  int   = TF_M1

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bull(self) -> bool:
        return self.close > self.open

    @property
    def is_bear(self) -> bool:
        return self.close < self.open


# ── Indicator primitives ──────────────────────────────────────────

class _ATR:
    def __init__(self, period: int = 14):
        self.period = period
        self._atr:  Optional[float] = None
        self._prev: Optional[float] = None
        self._buf:  List[float] = []

    def update(self, h: float, l: float, c: float) -> Optional[float]:
        if self._prev is None:
            self._prev = c
            return None
        tr = max(h - l, abs(h - self._prev), abs(l - self._prev))
        self._prev = c
        if self._atr is None:
            self._buf.append(tr)
            if len(self._buf) >= self.period:
                self._atr = sum(self._buf) / self.period
        else:
            self._atr = (self._atr * (self.period - 1) + tr) / self.period
        return self._atr

    @property
    def value(self) -> Optional[float]:
        return self._atr

    @property
    def ready(self) -> bool:
        return self._atr is not None


class _EMA:
    def __init__(self, period: int):
        self.period = period
        self._v:   Optional[float] = None
        self._k    = 2.0 / (period + 1)
        self._buf: List[float] = []

    def update(self, price: float) -> Optional[float]:
        if self._v is None:
            self._buf.append(price)
            if len(self._buf) >= self.period:
                self._v = sum(self._buf) / self.period
        else:
            self._v = price * self._k + self._v * (1 - self._k)
        return self._v

    @property
    def value(self) -> Optional[float]:
        return self._v

    @property
    def ready(self) -> bool:
        return self._v is not None


class _VWAP:
    """Session VWAP — resets at UTC midnight."""

    def __init__(self):
        self._cum_pv: float = 0.0
        self._cum_v:  float = 0.0
        self._day:    Optional[str] = None
        self._v:      Optional[float] = None
        self._slope:  float = 0.0
        self._prev:   Optional[float] = None

    def _reset_check(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._day != today:
            self._cum_pv = 0.0
            self._cum_v  = 0.0
            self._day    = today
            self._v      = None
            self._prev   = None

    def update(self, h: float, l: float, c: float, vol: float) -> Optional[float]:
        self._reset_check()
        tp = (h + l + c) / 3.0
        self._cum_pv += tp * max(vol, 1)
        self._cum_v  += max(vol, 1)
        prev = self._v
        self._v = self._cum_pv / self._cum_v
        if prev is not None:
            self._slope = self._v - prev
        return self._v

    @property
    def value(self) -> Optional[float]:
        return self._v

    @property
    def slope(self) -> float:
        return self._slope


class _BarBuffer:
    def __init__(self, tf: int, maxlen: int = 350):
        self.tf = tf
        self._buf: Deque[Bar] = deque(maxlen=maxlen)

    def push_dict(self, d: Dict) -> None:
        b = Bar(
            time=d["time"], open=d["open"], high=d["high"],
            low=d["low"], close=d["close"],
            tick_vol=d.get("tick_volume", 0),
            spread=d.get("spread", 0),
            real_vol=d.get("real_volume", 0),
            timeframe=self.tf,
        )
        if self._buf and self._buf[-1].time == b.time:
            self._buf[-1] = b
        else:
            self._buf.append(b)

    @property
    def bars(self) -> List[Bar]:
        return list(self._buf)

    @property
    def latest(self) -> Optional[Bar]:
        return self._buf[-1] if self._buf else None

    @property
    def prev(self) -> Optional[Bar]:
        return self._buf[-2] if len(self._buf) >= 2 else None

    def __len__(self) -> int:
        return len(self._buf)


# ── Volatility state ──────────────────────────────────────────────

@dataclass
class VolState:
    atr:                float = 0.0
    realized_vol:       float = 0.0   # std-dev of returns
    rolling_vol:        float = 0.0   # shorter window
    percentile:         float = 50.0
    regime:             str   = "NORMAL"  # COMPRESSED|NORMAL|EXPANDING|EXPLOSIVE
    compression:        bool  = False
    expansion:          bool  = False
    breakout_prob:      float = 0.5
    daily_range:        float = 0.0
    daily_range_used_pct: float = 0.0


# ── Main class ────────────────────────────────────────────────────

class MarketData:
    """
    Central market data repository.
    Processes ticks, maintains bars for 4 timeframes,
    computes all indicators in-place.
    """

    _SPREAD_WIN  = 200
    _ATR_HIST    = 120
    _RETURN_WIN  = 50

    def __init__(self):
        # Tick state
        self._ticks:      Deque[Tick]  = deque(maxlen=1000)
        self._latest:     Optional[Tick] = None
        self._tick_count: int = 0
        self._last_ts:    float = 0.0

        # Bar buffers
        self._bars: Dict[int, _BarBuffer] = {
            TF_M1:  _BarBuffer(TF_M1),
            TF_M5:  _BarBuffer(TF_M5),
            TF_M15: _BarBuffer(TF_M15),
            TF_H1:  _BarBuffer(TF_H1),
        }

        # Indicators per TF
        self._atr:   Dict[int, _ATR] = {tf: _ATR(14) for tf in self._bars}
        self._ema50: Dict[int, _EMA] = {tf: _EMA(50) for tf in self._bars}
        self._ema200:Dict[int, _EMA] = {tf: _EMA(200) for tf in self._bars}
        self._vwap = _VWAP()

        # ATR history for percentile
        self._atr_hist: Dict[int, Deque[float]] = {
            tf: deque(maxlen=self._ATR_HIST) for tf in self._bars
        }

        # Realized volatility (log returns)
        self._log_returns: Deque[float] = deque(maxlen=self._RETURN_WIN)
        self._short_returns: Deque[float] = deque(maxlen=20)
        self._prev_close: Optional[float] = None

        # Spread
        self._spread_hist: Deque[float] = deque(maxlen=self._SPREAD_WIN)
        self._avg_spread:  float = 0.0
        self._spread_pct:  float = 50.0

        # Daily range
        self._day_high: float = 0.0
        self._day_low:  float = float("inf")
        self._day_key:  Optional[str] = None

        # Volatility state
        self._vol = VolState()

    # ── Tick ingestion ────────────────────────────────────────────

    def ingest_tick(self, raw: Dict) -> Optional[Tick]:
        try:
            tick = Tick(
                time=raw["time"], bid=raw["bid"], ask=raw["ask"],
                last=raw.get("last", raw["bid"]),
                volume=int(raw.get("volume", 1)),
                flags=int(raw.get("flags", 0)),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Bad tick: {e}")
            return None

        self._latest = tick
        self._ticks.append(tick)
        self._tick_count += 1
        self._last_ts = time.time()

        self._update_spread(tick.spread)
        self._update_daily(tick)
        self._update_returns(tick.mid)
        return tick

    def _update_spread(self, sp: float) -> None:
        self._spread_hist.append(sp)
        if self._spread_hist:
            self._avg_spread = statistics.mean(self._spread_hist)
            sorted_s = sorted(self._spread_hist)
            pos = sum(1 for s in sorted_s if s <= sp)
            self._spread_pct = pos / len(sorted_s) * 100

    def _update_daily(self, tick: Tick) -> None:
        day = tick.time.strftime("%Y-%m-%d")
        if self._day_key != day:
            self._day_high = tick.mid
            self._day_low  = tick.mid
            self._day_key  = day
        self._day_high = max(self._day_high, tick.ask)
        self._day_low  = min(self._day_low,  tick.bid)

    def _update_returns(self, price: float) -> None:
        if self._prev_close and self._prev_close > 0:
            ret = math.log(price / self._prev_close)
            self._log_returns.append(ret)
            self._short_returns.append(ret)
        self._prev_close = price

    # ── Bar management ────────────────────────────────────────────

    def load_bars(self, tf: int, raw_bars: List[Dict]) -> None:
        buf = self._bars.get(tf)
        if buf is None:
            return
        for d in raw_bars:
            buf.push_dict(d)
            b = buf.latest
            if b:
                self._atr[tf].update(b.high, b.low, b.close)
                self._ema50[tf].update(b.close)
                self._ema200[tf].update(b.close)
                if tf == TF_M1:
                    self._vwap.update(b.high, b.low, b.close, b.tick_vol)
                atr_v = self._atr[tf].value
                if atr_v:
                    self._atr_hist[tf].append(atr_v)
        self._refresh_vol()

    def push_bar(self, tf: int, raw: Dict) -> None:
        buf = self._bars.get(tf)
        if buf is None:
            return
        buf.push_dict(raw)
        b = buf.latest
        if b:
            self._atr[tf].update(b.high, b.low, b.close)
            self._ema50[tf].update(b.close)
            self._ema200[tf].update(b.close)
            if tf == TF_M1:
                self._vwap.update(b.high, b.low, b.close, b.tick_vol)
            atr_v = self._atr[tf].value
            if atr_v:
                self._atr_hist[tf].append(atr_v)
        self._refresh_vol()

    # ── Volatility refresh ────────────────────────────────────────

    def _refresh_vol(self) -> None:
        atr = self._atr[TF_M5].value
        if atr is None:
            return

        price = self._latest.mid if self._latest else 1950.0
        hist  = list(self._atr_hist[TF_M5])

        self._vol.atr = atr

        # Realized vol (annualised)
        if len(self._log_returns) >= 10:
            rv = statistics.stdev(self._log_returns) * math.sqrt(252 * 24 * 12)
            self._vol.realized_vol = rv
        if len(self._short_returns) >= 5:
            self._vol.rolling_vol = statistics.stdev(self._short_returns)

        # Percentile
        if len(hist) >= 10:
            sorted_h = sorted(hist)
            pos = sum(1 for v in sorted_h if v <= atr)
            self._vol.percentile = pos / len(sorted_h) * 100
        else:
            self._vol.percentile = 50.0

        p = self._vol.percentile
        if p < 20:
            self._vol.regime = "COMPRESSED"
        elif p < 50:
            self._vol.regime = "NORMAL"
        elif p < 80:
            self._vol.regime = "EXPANDING"
        else:
            self._vol.regime = "EXPLOSIVE"

        self._vol.compression    = p < 25
        self._vol.expansion      = p > 65
        self._vol.breakout_prob  = max(0.1, min(0.9, 1.0 - p / 110.0))

        dr = self._day_high - self._day_low
        self._vol.daily_range = dr
        if dr > 0 and self._latest:
            used = abs(self._latest.mid - self._day_low)
            self._vol.daily_range_used_pct = used / dr * 100

    # ── Public accessors ──────────────────────────────────────────

    @property
    def latest_tick(self) -> Optional[Tick]:
        return self._latest

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self._last_ts) < 5.0

    @property
    def feed_age_ms(self) -> float:
        return (time.time() - self._last_ts) * 1000 if self._last_ts else float("inf")

    @property
    def volatility(self) -> VolState:
        return self._vol

    @property
    def avg_spread(self) -> float:
        return self._avg_spread

    @property
    def spread_pct(self) -> float:
        return self._spread_pct

    def bars(self, tf: int) -> List[Bar]:
        return self._bars[tf].bars if tf in self._bars else []

    def latest_bar(self, tf: int) -> Optional[Bar]:
        return self._bars[tf].latest if tf in self._bars else None

    def atr(self, tf: int = TF_M5) -> Optional[float]:
        return self._atr[tf].value if tf in self._atr else None

    def ema50(self, tf: int = TF_H1) -> Optional[float]:
        return self._ema50[tf].value if tf in self._ema50 else None

    def ema200(self, tf: int = TF_H1) -> Optional[float]:
        return self._ema200[tf].value if tf in self._ema200 else None

    def vwap(self) -> Optional[float]:
        return self._vwap.value

    def vwap_slope(self) -> float:
        return self._vwap.slope

    def vwap_deviation(self, price: float) -> Optional[float]:
        v = self._vwap.value
        if v is None or v == 0:
            return None
        return (price - v) / v * 100.0

    def is_ema_bull(self, tf: int = TF_H1) -> bool:
        e50 = self.ema50(tf)
        e200 = self.ema200(tf)
        return e50 is not None and e200 is not None and e50 > e200

    def is_ema_bear(self, tf: int = TF_H1) -> bool:
        e50 = self.ema50(tf)
        e200 = self.ema200(tf)
        return e50 is not None and e200 is not None and e50 < e200

    def recent_ticks(self, n: int = 200) -> List[Tick]:
        buf = list(self._ticks)
        return buf[-n:] if len(buf) >= n else buf

    def spread_score(self) -> float:
        if self._avg_spread <= 0:
            return 50.0
        ratio = (self._latest.spread if self._latest else self._avg_spread) / self._avg_spread
        if ratio <= 0.8:  return 100.0
        if ratio <= 1.2:  return 80.0
        if ratio <= 1.5:  return 60.0
        if ratio <= 2.0:  return 30.0
        return 0.0

    def snapshot(self) -> Dict:
        t = self._latest
        return {
            "bid":        t.bid if t else 0,
            "ask":        t.ask if t else 0,
            "mid":        t.mid if t else 0,
            "spread":     t.spread if t else 0,
            "atr_m5":     self.atr(TF_M5),
            "atr_h1":     self.atr(TF_H1),
            "ema50_h1":   self.ema50(TF_H1),
            "ema200_h1":  self.ema200(TF_H1),
            "vwap":       self.vwap(),
            "vwap_slope": self.vwap_slope(),
            "vol_regime": self._vol.regime,
            "vol_pct":    round(self._vol.percentile, 1),
            "realized_vol": round(self._vol.realized_vol, 4),
            "daily_range": round(self._vol.daily_range, 2),
            "feed_age_ms": round(self.feed_age_ms, 0),
            "tick_count":  self._tick_count,
        }


# ── Multi-Symbol Registry ─────────────────────────────────────────────────────

class MultiSymbolMarketData:
    """
    Registry of per-symbol MarketData instances.

    Each enabled symbol gets its own isolated MarketData object with its own
    tick history, bar buffers, indicators, and volatility state.
    The existing MarketData class is unchanged — this is a pure registry layer.

    Usage:
        msd = MultiSymbolMarketData(["XAUUSD", "EURUSD", "GBPUSD"])
        msd.get("EURUSD").ingest_tick(raw_tick)
        msd.get("XAUUSD").atr(TF_M5)
    """

    def __init__(self, symbols: List[str]):
        self._data: Dict[str, MarketData] = {s: MarketData() for s in symbols}
        logger.info(f"MultiSymbolMarketData: tracking {symbols}")

    def get(self, symbol: str) -> Optional[MarketData]:
        """Returns the MarketData instance for the symbol, or None if not tracked."""
        return self._data.get(symbol)

    def symbols(self) -> List[str]:
        return list(self._data.keys())

    def snapshots(self) -> Dict[str, Dict]:
        """Returns snapshot dicts for all symbols."""
        return {sym: md.snapshot() for sym, md in self._data.items()}

    def add_symbol(self, symbol: str) -> None:
        """Dynamically add a symbol to the registry."""
        if symbol not in self._data:
            self._data[symbol] = MarketData()
            logger.info(f"MultiSymbolMarketData: added {symbol}")

    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from the registry."""
        self._data.pop(symbol, None)


import logging
import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

# Timeframe constants (match MT5 TIMEFRAME_* values)
TF_M1  = 1
TF_M5  = 5
TF_M15 = 15
TF_H1  = 60


# ── Primitive models ──────────────────────────────────────────────

@dataclass
class Tick:
    time:   datetime
    bid:    float
    ask:    float
    last:   float
    volume: int
    flags:  int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_pts(self) -> int:
        return round(self.spread * 100)


@dataclass
class Bar:
    time:       datetime
    open:       float
    high:       float
    low:        float
    close:      float
    tick_vol:   int
    spread:     float = 0.0
    real_vol:   int   = 0
    timeframe:  int   = TF_M1

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bull(self) -> bool:
        return self.close > self.open

    @property
    def is_bear(self) -> bool:
        return self.close < self.open


# ── Indicator primitives ──────────────────────────────────────────

class _ATR:
    def __init__(self, period: int = 14):
        self.period = period
        self._atr:  Optional[float] = None
        self._prev: Optional[float] = None
        self._buf:  List[float] = []

    def update(self, h: float, l: float, c: float) -> Optional[float]:
        if self._prev is None:
            self._prev = c
            return None
        tr = max(h - l, abs(h - self._prev), abs(l - self._prev))
        self._prev = c
        if self._atr is None:
            self._buf.append(tr)
            if len(self._buf) >= self.period:
                self._atr = sum(self._buf) / self.period
        else:
            self._atr = (self._atr * (self.period - 1) + tr) / self.period
        return self._atr

    @property
    def value(self) -> Optional[float]:
        return self._atr

    @property
    def ready(self) -> bool:
        return self._atr is not None


class _EMA:
    def __init__(self, period: int):
        self.period = period
        self._v:   Optional[float] = None
        self._k    = 2.0 / (period + 1)
        self._buf: List[float] = []

    def update(self, price: float) -> Optional[float]:
        if self._v is None:
            self._buf.append(price)
            if len(self._buf) >= self.period:
                self._v = sum(self._buf) / self.period
        else:
            self._v = price * self._k + self._v * (1 - self._k)
        return self._v

    @property
    def value(self) -> Optional[float]:
        return self._v

    @property
    def ready(self) -> bool:
        return self._v is not None


class _VWAP:
    """Session VWAP — resets at UTC midnight."""

    def __init__(self):
        self._cum_pv: float = 0.0
        self._cum_v:  float = 0.0
        self._day:    Optional[str] = None
        self._v:      Optional[float] = None
        self._slope:  float = 0.0
        self._prev:   Optional[float] = None

    def _reset_check(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._day != today:
            self._cum_pv = 0.0
            self._cum_v  = 0.0
            self._day    = today
            self._v      = None
            self._prev   = None

    def update(self, h: float, l: float, c: float, vol: float) -> Optional[float]:
        self._reset_check()
        tp = (h + l + c) / 3.0
        self._cum_pv += tp * max(vol, 1)
        self._cum_v  += max(vol, 1)
        prev = self._v
        self._v = self._cum_pv / self._cum_v
        if prev is not None:
            self._slope = self._v - prev
        return self._v

    @property
    def value(self) -> Optional[float]:
        return self._v

    @property
    def slope(self) -> float:
        return self._slope


class _BarBuffer:
    def __init__(self, tf: int, maxlen: int = 350):
        self.tf = tf
        self._buf: Deque[Bar] = deque(maxlen=maxlen)

    def push_dict(self, d: Dict) -> None:
        b = Bar(
            time=d["time"], open=d["open"], high=d["high"],
            low=d["low"], close=d["close"],
            tick_vol=d.get("tick_volume", 0),
            spread=d.get("spread", 0),
            real_vol=d.get("real_volume", 0),
            timeframe=self.tf,
        )
        if self._buf and self._buf[-1].time == b.time:
            self._buf[-1] = b
        else:
            self._buf.append(b)

    @property
    def bars(self) -> List[Bar]:
        return list(self._buf)

    @property
    def latest(self) -> Optional[Bar]:
        return self._buf[-1] if self._buf else None

    @property
    def prev(self) -> Optional[Bar]:
        return self._buf[-2] if len(self._buf) >= 2 else None

    def __len__(self) -> int:
        return len(self._buf)


# ── Volatility state ──────────────────────────────────────────────

@dataclass
class VolState:
    atr:                float = 0.0
    realized_vol:       float = 0.0   # std-dev of returns
    rolling_vol:        float = 0.0   # shorter window
    percentile:         float = 50.0
    regime:             str   = "NORMAL"  # COMPRESSED|NORMAL|EXPANDING|EXPLOSIVE
    compression:        bool  = False
    expansion:          bool  = False
    breakout_prob:      float = 0.5
    daily_range:        float = 0.0
    daily_range_used_pct: float = 0.0


# ── Main class ────────────────────────────────────────────────────

class MarketData:
    """
    Central market data repository.
    Processes ticks, maintains bars for 4 timeframes,
    computes all indicators in-place.
    """

    _SPREAD_WIN  = 200
    _ATR_HIST    = 120
    _RETURN_WIN  = 50

    def __init__(self):
        # Tick state
        self._ticks:      Deque[Tick]  = deque(maxlen=1000)
        self._latest:     Optional[Tick] = None
        self._tick_count: int = 0
        self._last_ts:    float = 0.0

        # Bar buffers
        self._bars: Dict[int, _BarBuffer] = {
            TF_M1:  _BarBuffer(TF_M1),
            TF_M5:  _BarBuffer(TF_M5),
            TF_M15: _BarBuffer(TF_M15),
            TF_H1:  _BarBuffer(TF_H1),
        }

        # Indicators per TF
        self._atr:   Dict[int, _ATR] = {tf: _ATR(14) for tf in self._bars}
        self._ema50: Dict[int, _EMA] = {tf: _EMA(50) for tf in self._bars}
        self._ema200:Dict[int, _EMA] = {tf: _EMA(200) for tf in self._bars}
        self._vwap = _VWAP()

        # ATR history for percentile
        self._atr_hist: Dict[int, Deque[float]] = {
            tf: deque(maxlen=self._ATR_HIST) for tf in self._bars
        }

        # Realized volatility (log returns)
        self._log_returns: Deque[float] = deque(maxlen=self._RETURN_WIN)
        self._short_returns: Deque[float] = deque(maxlen=20)
        self._prev_close: Optional[float] = None

        # Spread
        self._spread_hist: Deque[float] = deque(maxlen=self._SPREAD_WIN)
        self._avg_spread:  float = 0.0
        self._spread_pct:  float = 50.0

        # Daily range
        self._day_high: float = 0.0
        self._day_low:  float = float("inf")
        self._day_key:  Optional[str] = None

        # Volatility state
        self._vol = VolState()

    # ── Tick ingestion ────────────────────────────────────────────

    def ingest_tick(self, raw: Dict) -> Optional[Tick]:
        try:
            tick = Tick(
                time=raw["time"], bid=raw["bid"], ask=raw["ask"],
                last=raw.get("last", raw["bid"]),
                volume=int(raw.get("volume", 1)),
                flags=int(raw.get("flags", 0)),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.debug(f"Bad tick: {e}")
            return None

        self._latest = tick
        self._ticks.append(tick)
        self._tick_count += 1
        self._last_ts = time.time()

        self._update_spread(tick.spread)
        self._update_daily(tick)
        self._update_returns(tick.mid)
        return tick

    def _update_spread(self, sp: float) -> None:
        self._spread_hist.append(sp)
        if self._spread_hist:
            self._avg_spread = statistics.mean(self._spread_hist)
            sorted_s = sorted(self._spread_hist)
            pos = sum(1 for s in sorted_s if s <= sp)
            self._spread_pct = pos / len(sorted_s) * 100

    def _update_daily(self, tick: Tick) -> None:
        day = tick.time.strftime("%Y-%m-%d")
        if self._day_key != day:
            self._day_high = tick.mid
            self._day_low  = tick.mid
            self._day_key  = day
        self._day_high = max(self._day_high, tick.ask)
        self._day_low  = min(self._day_low,  tick.bid)

    def _update_returns(self, price: float) -> None:
        if self._prev_close and self._prev_close > 0:
            ret = math.log(price / self._prev_close)
            self._log_returns.append(ret)
            self._short_returns.append(ret)
        self._prev_close = price

    # ── Bar management ────────────────────────────────────────────

    def load_bars(self, tf: int, raw_bars: List[Dict]) -> None:
        buf = self._bars.get(tf)
        if buf is None:
            return
        for d in raw_bars:
            buf.push_dict(d)
            b = buf.latest
            if b:
                self._atr[tf].update(b.high, b.low, b.close)
                self._ema50[tf].update(b.close)
                self._ema200[tf].update(b.close)
                if tf == TF_M1:
                    self._vwap.update(b.high, b.low, b.close, b.tick_vol)
                atr_v = self._atr[tf].value
                if atr_v:
                    self._atr_hist[tf].append(atr_v)
        self._refresh_vol()

    def push_bar(self, tf: int, raw: Dict) -> None:
        buf = self._bars.get(tf)
        if buf is None:
            return
        buf.push_dict(raw)
        b = buf.latest
        if b:
            self._atr[tf].update(b.high, b.low, b.close)
            self._ema50[tf].update(b.close)
            self._ema200[tf].update(b.close)
            if tf == TF_M1:
                self._vwap.update(b.high, b.low, b.close, b.tick_vol)
            atr_v = self._atr[tf].value
            if atr_v:
                self._atr_hist[tf].append(atr_v)
        self._refresh_vol()

    # ── Volatility refresh ────────────────────────────────────────

    def _refresh_vol(self) -> None:
        atr = self._atr[TF_M5].value
        if atr is None:
            return

        price = self._latest.mid if self._latest else 1950.0
        hist  = list(self._atr_hist[TF_M5])

        self._vol.atr = atr

        # Realized vol (annualised)
        if len(self._log_returns) >= 10:
            rv = statistics.stdev(self._log_returns) * math.sqrt(252 * 24 * 12)
            self._vol.realized_vol = rv
        if len(self._short_returns) >= 5:
            self._vol.rolling_vol = statistics.stdev(self._short_returns)

        # Percentile
        if len(hist) >= 10:
            sorted_h = sorted(hist)
            pos = sum(1 for v in sorted_h if v <= atr)
            self._vol.percentile = pos / len(sorted_h) * 100
        else:
            self._vol.percentile = 50.0

        p = self._vol.percentile
        if p < 20:
            self._vol.regime = "COMPRESSED"
        elif p < 50:
            self._vol.regime = "NORMAL"
        elif p < 80:
            self._vol.regime = "EXPANDING"
        else:
            self._vol.regime = "EXPLOSIVE"

        self._vol.compression    = p < 25
        self._vol.expansion      = p > 65
        self._vol.breakout_prob  = max(0.1, min(0.9, 1.0 - p / 110.0))

        dr = self._day_high - self._day_low
        self._vol.daily_range = dr
        if dr > 0 and self._latest:
            used = abs(self._latest.mid - self._day_low)
            self._vol.daily_range_used_pct = used / dr * 100

    # ── Public accessors ──────────────────────────────────────────

    @property
    def latest_tick(self) -> Optional[Tick]:
        return self._latest

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self._last_ts) < 5.0

    @property
    def feed_age_ms(self) -> float:
        return (time.time() - self._last_ts) * 1000 if self._last_ts else float("inf")

    @property
    def volatility(self) -> VolState:
        return self._vol

    @property
    def avg_spread(self) -> float:
        return self._avg_spread

    @property
    def spread_pct(self) -> float:
        return self._spread_pct

    def bars(self, tf: int) -> List[Bar]:
        return self._bars[tf].bars if tf in self._bars else []

    def latest_bar(self, tf: int) -> Optional[Bar]:
        return self._bars[tf].latest if tf in self._bars else None

    def atr(self, tf: int = TF_M5) -> Optional[float]:
        return self._atr[tf].value if tf in self._atr else None

    def ema50(self, tf: int = TF_H1) -> Optional[float]:
        return self._ema50[tf].value if tf in self._ema50 else None

    def ema200(self, tf: int = TF_H1) -> Optional[float]:
        return self._ema200[tf].value if tf in self._ema200 else None

    def vwap(self) -> Optional[float]:
        return self._vwap.value

    def vwap_slope(self) -> float:
        return self._vwap.slope

    def vwap_deviation(self, price: float) -> Optional[float]:
        v = self._vwap.value
        if v is None or v == 0:
            return None
        return (price - v) / v * 100.0

    def is_ema_bull(self, tf: int = TF_H1) -> bool:
        e50 = self.ema50(tf)
        e200 = self.ema200(tf)
        return e50 is not None and e200 is not None and e50 > e200

    def is_ema_bear(self, tf: int = TF_H1) -> bool:
        e50 = self.ema50(tf)
        e200 = self.ema200(tf)
        return e50 is not None and e200 is not None and e50 < e200

    def recent_ticks(self, n: int = 200) -> List[Tick]:
        buf = list(self._ticks)
        return buf[-n:] if len(buf) >= n else buf

    def spread_score(self) -> float:
        if self._avg_spread <= 0:
            return 50.0
        ratio = (self._latest.spread if self._latest else self._avg_spread) / self._avg_spread
        if ratio <= 0.8:  return 100.0
        if ratio <= 1.2:  return 80.0
        if ratio <= 1.5:  return 60.0
        if ratio <= 2.0:  return 30.0
        return 0.0

    def snapshot(self) -> Dict:
        t = self._latest
        return {
            "bid":        t.bid if t else 0,
            "ask":        t.ask if t else 0,
            "mid":        t.mid if t else 0,
            "spread":     t.spread if t else 0,
            "atr_m5":     self.atr(TF_M5),
            "atr_h1":     self.atr(TF_H1),
            "ema50_h1":   self.ema50(TF_H1),
            "ema200_h1":  self.ema200(TF_H1),
            "vwap":       self.vwap(),
            "vwap_slope": self.vwap_slope(),
            "vol_regime": self._vol.regime,
            "vol_pct":    round(self._vol.percentile, 1),
            "realized_vol": round(self._vol.realized_vol, 4),
            "daily_range": round(self._vol.daily_range, 2),
            "feed_age_ms": round(self.feed_age_ms, 0),
            "tick_count":  self._tick_count,
        }
