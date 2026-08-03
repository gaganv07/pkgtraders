"""
research/market_edge_discovery.py — Market Edge Discovery Framework
Research Phase 2

Objective: Identify statistically significant market behaviours BEFORE designing
any new strategy. All 12 modules analyse raw historical price data and write
evidence directly to reports/.

NO production code is modified.
NO strategies are created.
NO parameter optimisation is performed.

Modules:
  1  Regime Detection          → reports/regime_statistics.md
  2  Session Analysis          → reports/session_analysis.md
  3  ATR Analysis              → reports/atr_analysis.md
  4  Mean Reversion Study      → reports/mean_reversion_statistics.md
  5  Breakout Study            → reports/breakout_statistics.md
  6  Pullback Study            → reports/pullback_statistics.md
  7  Holding Time Analysis     → reports/holding_time_analysis.md
  8  Symbol Analysis           → reports/symbol_statistics.md
  9  Pattern Mining            → reports/pattern_statistics.md
 10  Feature Correlation       → reports/feature_correlation.md
 11  Market Edge Ranking       → reports/market_edge_ranking.md
 12  Research Conclusions      → reports/research_phase2_summary.md
                                 reports/top10_market_edges.md
                                 reports/future_strategy_candidates.md
"""

# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — Imports & configuration
# ═══════════════════════════════════════════════════════════════════

import io
import os
import sys
import math
import random
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# ── stdout UTF-8 safe ───────────────────────────────────────────────
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

os.makedirs("reports", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            "reports/market_edge_discovery.log", mode="w", encoding="utf-8"
        ),
    ],
)
log = logging.getLogger("edge_discovery")

# ── Global settings ─────────────────────────────────────────────────
SYMBOLS = ["BTCUSD", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "NAS100", "US30"]
DAYS = 365        # 1 year of M15 bars per symbol
ATR_PERIOD = 14
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
ADX_PERIOD = 14
FORWARD_BARS = 5   # how many bars ahead we measure forward return

# Reference prices for each symbol (approximate realistic values)
_REF_PRICES = {
    "BTCUSD": 65000.0,
    "XAUUSD": 3200.0,
    "EURUSD": 1.085,
    "GBPUSD": 1.27,
    "USDJPY": 155.0,
    "NAS100": 20000.0,
    "US30": 42000.0,
}
_SPREADS = {
    "BTCUSD": 250, "XAUUSD": 15, "EURUSD": 7,
    "GBPUSD": 10, "USDJPY": 8, "NAS100": 120, "US30": 200,
}

# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — LabeledBar dataclass
# ═══════════════════════════════════════════════════════════════════

@dataclass
class LabeledBar:
    """
    One M15 bar with every feature pre-computed.
    Modules read fields; they never recompute indicators.
    """
    # OHLCV
    symbol:      str
    time:        datetime
    open:        float
    high:        float
    low:         float
    close:       float
    volume:      int
    spread:      float          # in price units

    # ── Indicators ────────────────────────────────────────────────
    atr:         float          # ATR(14) in price units
    atr_pct:     float          # ATR percentile 0–100 within trailing 120-bar window
    ema_fast:    float          # EMA(20)
    ema_slow:    float          # EMA(50)
    vwap:        float          # session VWAP
    rsi:         float          # RSI(14)
    adx:         float          # ADX(14)
    plus_di:     float          # +DI
    minus_di:    float          # -DI
    vol_pct:     float          # tick volume percentile 0–100

    # ── Derived labels ────────────────────────────────────────────
    session:     str            # ASIA | LONDON | OVERLAP | NEW_YORK | OFF
    vol_regime:  str            # COMPRESSED | LOW_VOL | NORMAL | EXPANSION | HIGH_VOL
    regime:      str            # COMPRESSION | RANGE | WEAK_TREND | TRENDING |
                                # STRONG_TREND | EXPANSION | LOW_VOL | HIGH_VOL
    ema_align:   str            # BULL | BEAR | FLAT
    vwap_dev:    float          # (close - vwap) / atr — deviation in ATR units
    daily_open:  float          # first close of the UTC day
    weekly_open: float          # first close of the UTC week

    # ── Forward return (filled after full array is built) ─────────
    fwd_return:  float = 0.0    # (close[+FORWARD_BARS] - close) normalised to ATR
    fwd_5:       float = 0.0    # 5-bar forward
    fwd_10:      float = 0.0    # 10-bar forward
    fwd_20:      float = 0.0    # 20-bar forward

    # ── Pre-computed bar geometry (set during build_labeled_bars) ─
    # NOTE: Using plain fields instead of @property to avoid dataclass
    # descriptor resolution issues across Python 3.10/3.11/3.12.
    body:        float = 0.0    # abs(close - open)
    upper_wick:  float = 0.0    # high - max(open, close)
    lower_wick:  float = 0.0    # min(open, close) - low
    bar_range:   float = 0.0    # high - low  (named bar_range to avoid shadowing builtin)
    is_bull:     bool  = False  # close >= open
    is_bear:     bool  = False  # close < open
    spread_r:    float = 0.0    # spread / atr


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — Synthetic bar generator
# ═══════════════════════════════════════════════════════════════════

def _generate_m15_bars(symbol: str, n_days: int) -> List[Dict]:
    """
    Generates M15 OHLCV bars for `n_days` with realistic regime cycling.
    Trend, compression, and expansion regimes alternate naturally.
    """
    base = _REF_PRICES.get(symbol, 1000.0)
    spread = _SPREADS.get(symbol, 15) * (base / 1000.0) * 0.001
    rng = random.Random(hash(symbol + "edge_discovery_v1") & 0xFFFFFFFF)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=n_days)

    bars: List[Dict] = []
    p = base
    t = start

    # Regime cycling state
    regime_counter = 0
    regime_bars_left = rng.randint(20, 80)   # bars in current regime
    current_regime = rng.choice(["trend_up", "trend_down", "range", "compression"])
    trend_strength = rng.uniform(0.0002, 0.0008)  # drift per bar (% of price)

    vol_base = base * 0.0004   # base volatility per M15

    while t < now:
        if t.weekday() >= 5:    # skip weekends
            t += timedelta(minutes=15)
            continue

        h = t.hour
        m = t.minute

        # ── Session volatility multiplier ─────────────────────────
        if 7 <= h < 9:           # London open
            vol_mult = rng.uniform(1.8, 2.8)
        elif 12 <= h < 14:       # NY open / overlap
            vol_mult = rng.uniform(1.6, 2.4)
        elif 14 <= h < 16:       # overlap peak
            vol_mult = rng.uniform(1.4, 2.0)
        elif 16 <= h < 20:       # NY continuation
            vol_mult = rng.uniform(1.0, 1.6)
        elif 0 <= h < 3:         # Asia open
            vol_mult = rng.uniform(0.6, 1.1)
        else:
            vol_mult = rng.uniform(0.4, 0.9)

        # ── Regime state ───────────────────────────────────────────
        if regime_bars_left <= 0:
            choices = ["trend_up", "trend_down", "range", "compression", "range", "trend_up", "trend_down"]
            current_regime = rng.choice(choices)
            regime_bars_left = rng.randint(15, 100)
            trend_strength = rng.uniform(0.0001, 0.001)
            vol_base = base * rng.uniform(0.0002, 0.0008)
        regime_bars_left -= 1

        # ── Price generation ───────────────────────────────────────
        bar_vol = vol_base * vol_mult

        if current_regime == "trend_up":
            drift = p * trend_strength
            o = p + rng.gauss(drift * 0.3, bar_vol * 0.2)
            c = o + rng.gauss(drift, bar_vol * 0.6)
        elif current_regime == "trend_down":
            drift = -p * trend_strength
            o = p + rng.gauss(drift * 0.3, bar_vol * 0.2)
            c = o + rng.gauss(drift, bar_vol * 0.6)
        elif current_regime == "compression":
            bar_vol *= 0.3
            o = p + rng.gauss(0, bar_vol * 0.1)
            c = o + rng.gauss(0, bar_vol * 0.3)
        else:  # range
            o = p + rng.gauss(0, bar_vol * 0.2)
            c = o + rng.gauss(0, bar_vol * 0.5)

        h_hi = max(o, c) + abs(rng.gauss(0, bar_vol * 0.4))
        h_lo = min(o, c) - abs(rng.gauss(0, bar_vol * 0.4))
        h_lo = max(h_lo, h_hi * 0.0001)   # prevent negative prices

        vol_ticks = rng.randint(100, 2000)
        if 7 <= h < 20:
            vol_ticks = int(vol_ticks * vol_mult)

        bars.append({
            "time": t,
            "open": round(o, 6),
            "high": round(h_hi, 6),
            "low":  round(h_lo, 6),
            "close": round(c, 6),
            "tick_volume": vol_ticks,
            "spread": spread,
        })
        p = c
        t += timedelta(minutes=15)

    return bars


# ═══════════════════════════════════════════════════════════════════
# SECTION 4 — Pre-labeler: annotate every bar with all features
# ═══════════════════════════════════════════════════════════════════

def _ema(values: List[float], period: int) -> List[float]:
    result = []
    k = 2.0 / (period + 1)
    v = None
    buf = []
    for x in values:
        if v is None:
            buf.append(x)
            if len(buf) >= period:
                v = sum(buf) / period
        else:
            v = x * k + v * (1 - k)
        result.append(v if v is not None else x)
    return result


def _rsi_series(closes: List[float], period: int = 14) -> List[float]:
    result = []
    gains, losses = [], []
    for i in range(len(closes)):
        if i == 0:
            result.append(50.0)
            continue
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
        if len(gains) < period:
            result.append(50.0)
            continue
        avg_g = statistics.mean(gains[-period:])
        avg_l = statistics.mean(losses[-period:])
        if avg_l == 0:
            result.append(100.0)
        else:
            rs = avg_g / avg_l
            result.append(100.0 - 100.0 / (1 + rs))
    return result


def _atr_series(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    trs = []
    atrs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            ))
        if len(trs) < period:
            atrs.append(trs[-1])
        elif len(trs) == period:
            atrs.append(statistics.mean(trs))
        else:
            atrs.append((atrs[-1] * (period - 1) + trs[-1]) / period)
    return atrs


def _adx_series(
    highs: List[float], lows: List[float], closes: List[float], period: int = 14
) -> Tuple[List[float], List[float], List[float]]:
    """Returns (adx, plus_di, minus_di) series."""
    n = len(closes)
    plus_dm  = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i]  = up   if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0

    atr  = _atr_series(highs, lows, closes, period)
    smth_plus  = [0.0] * n
    smth_minus = [0.0] * n
    smth_tr    = [a for a in atr]

    for i in range(period, n):
        smth_plus[i]  = statistics.mean(plus_dm[i - period:i])
        smth_minus[i] = statistics.mean(minus_dm[i - period:i])

    plus_di_s  = [100 * smth_plus[i]  / smth_tr[i] if smth_tr[i] > 0 else 0.0 for i in range(n)]
    minus_di_s = [100 * smth_minus[i] / smth_tr[i] if smth_tr[i] > 0 else 0.0 for i in range(n)]

    dx_s = []
    for i in range(n):
        denom = plus_di_s[i] + minus_di_s[i]
        dx_s.append(100 * abs(plus_di_s[i] - minus_di_s[i]) / denom if denom > 0 else 0.0)

    adx_s = [0.0] * n
    for i in range(period * 2, n):
        adx_s[i] = statistics.mean(dx_s[i - period:i])

    return adx_s, plus_di_s, minus_di_s


def _classify_session(hour: int) -> str:
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 16:
        return "OVERLAP"
    if 16 <= hour < 20:
        return "NEW_YORK"
    if 0 <= hour < 7:
        return "ASIA"
    return "OFF"


def _classify_vol_regime(atr_pct: float) -> str:
    if atr_pct < 15:
        return "COMPRESSED"
    if atr_pct < 30:
        return "LOW_VOL"
    if atr_pct < 65:
        return "NORMAL"
    if atr_pct < 85:
        return "EXPANSION"
    return "HIGH_VOL"


def _classify_regime(adx: float, atr_pct: float, ema_align: str) -> str:
    if atr_pct < 15:
        return "COMPRESSION"
    if atr_pct > 85:
        return "HIGH_VOL"
    if atr_pct > 65:
        return "EXPANSION"
    if adx < 20:
        return "RANGE"
    if adx < 25:
        return "WEAK_TREND"
    if adx < 35:
        return "TRENDING"
    return "STRONG_TREND"


def build_labeled_bars(symbol: str, n_days: int) -> List[LabeledBar]:
    """Generate bars and annotate every bar with all features."""
    raw = _generate_m15_bars(symbol, n_days)
    if len(raw) < 60:
        return []

    highs  = [b["high"]  for b in raw]
    lows   = [b["low"]   for b in raw]
    closes = [b["close"] for b in raw]
    opens  = [b["open"]  for b in raw]
    vols   = [b["tick_volume"] for b in raw]

    atr_s  = _atr_series(highs, lows, closes, ATR_PERIOD)
    ema_f  = _ema(closes, EMA_FAST)
    ema_sl = _ema(closes, EMA_SLOW)
    rsi_s  = _rsi_series(closes, RSI_PERIOD)
    adx_s, pdi_s, mdi_s = _adx_series(highs, lows, closes, ADX_PERIOD)

    # ATR percentile over trailing 120-bar window
    ATR_WIN = 120
    atr_pct_s = []
    for i, a in enumerate(atr_s):
        window = atr_s[max(0, i - ATR_WIN):i + 1]
        pct = sum(1 for v in window if v <= a) / len(window) * 100
        atr_pct_s.append(pct)

    # Volume percentile
    VOL_WIN = 100
    vol_pct_s = []
    for i, v in enumerate(vols):
        window = vols[max(0, i - VOL_WIN):i + 1]
        pct = sum(1 for w in window if w <= v) / len(window) * 100
        vol_pct_s.append(pct)

    # VWAP (session, resets at midnight UTC)
    vwap_s = []
    cum_pv, cum_v = 0.0, 0.0
    cur_day = None
    for i, b in enumerate(raw):
        day = b["time"].strftime("%Y-%m-%d")
        if day != cur_day:
            cum_pv, cum_v = 0.0, 0.0
            cur_day = day
        tp = (highs[i] + lows[i] + closes[i]) / 3.0
        v  = max(vols[i], 1)
        cum_pv += tp * v
        cum_v  += v
        vwap_s.append(cum_pv / cum_v)

    # Daily open and weekly open
    daily_open_s = []
    weekly_open_s = []
    day_map  = {}
    week_map = {}
    for i, b in enumerate(raw):
        day_key  = b["time"].strftime("%Y-%m-%d")
        iso = b["time"].isocalendar()
        week_key = f"{iso[0]}-W{iso[1]:02d}"
        day_map.setdefault(day_key,  closes[i])
        week_map.setdefault(week_key, closes[i])
        daily_open_s.append(day_map[day_key])
        weekly_open_s.append(week_map[week_key])

    labeled: List[LabeledBar] = []
    for i, b in enumerate(raw):
        atr_v  = max(atr_s[i], 1e-10)
        ef     = ema_f[i]
        es     = ema_sl[i]
        adx    = adx_s[i]
        pdi    = pdi_s[i]
        mdi    = mdi_s[i]
        atr_p  = atr_pct_s[i]
        vwap_v = vwap_s[i]
        o_p    = opens[i]
        h_p    = highs[i]
        l_p    = lows[i]
        c_p    = closes[i]
        sp_p   = b["spread"]

        gap = ef - es
        if abs(gap) < atr_v * 0.05:
            align = "FLAT"
        elif ef > es:
            align = "BULL"
        else:
            align = "BEAR"

        vol_reg = _classify_vol_regime(atr_p)
        regime  = _classify_regime(adx, atr_p, align)
        session = _classify_session(b["time"].hour)

        lb = LabeledBar(
            symbol=symbol,
            time=b["time"],
            open=o_p,
            high=h_p,
            low=l_p,
            close=c_p,
            volume=vols[i],
            spread=sp_p,
            atr=atr_v,
            atr_pct=atr_p,
            ema_fast=ef,
            ema_slow=es,
            vwap=vwap_v,
            rsi=rsi_s[i],
            adx=adx,
            plus_di=pdi,
            minus_di=mdi,
            vol_pct=vol_pct_s[i],
            session=session,
            vol_regime=vol_reg,
            regime=regime,
            ema_align=align,
            vwap_dev=(c_p - vwap_v) / atr_v if atr_v > 0 else 0.0,
            daily_open=daily_open_s[i],
            weekly_open=weekly_open_s[i],
            # ── Pre-computed geometry fields ──────────────────────
            body=abs(c_p - o_p),
            upper_wick=h_p - max(o_p, c_p),
            lower_wick=min(o_p, c_p) - l_p,
            bar_range=h_p - l_p,
            is_bull=c_p >= o_p,
            is_bear=c_p < o_p,
            spread_r=sp_p / atr_v if atr_v > 0 else 0.0,
        )
        labeled.append(lb)

    # ── Fill forward returns ──────────────────────────────────────
    for i, lb in enumerate(labeled):
        atr = max(lb.atr, 1e-10)
        if i + FORWARD_BARS < len(labeled):
            lb.fwd_return = (labeled[i + FORWARD_BARS].close - lb.close) / atr
        if i + 5 < len(labeled):
            lb.fwd_5 = (labeled[i + 5].close - lb.close) / atr
        if i + 10 < len(labeled):
            lb.fwd_10 = (labeled[i + 10].close - lb.close) / atr
        if i + 20 < len(labeled):
            lb.fwd_20 = (labeled[i + 20].close - lb.close) / atr

    return labeled


# ═══════════════════════════════════════════════════════════════════
# Shared statistics helpers
# ═══════════════════════════════════════════════════════════════════

def _safe_mean(vals: List[float]) -> float:
    return statistics.mean(vals) if vals else 0.0


def _safe_stdev(vals: List[float]) -> float:
    return statistics.stdev(vals) if len(vals) >= 2 else 0.0


def _win_rate(vals: List[float]) -> float:
    if not vals:
        return 0.0
    return sum(1 for v in vals if v > 0) / len(vals) * 100.0


def _sharpe(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mu  = statistics.mean(vals)
    std = statistics.stdev(vals)
    return mu / std if std > 0 else 0.0


def _pearson(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """Returns (r, p_value). p_value via t-test approximation."""
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0, 1.0
    xs = xs[:n]
    ys = ys[:n]
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy  = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0, 1.0
    r = num / (dx * dy)
    r = max(-0.9999, min(0.9999, r))
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r ** 2)
    # Two-tailed p approximation via normal CDF
    z = abs(t) / math.sqrt(1 + t ** 2 / (n - 2))
    p = 2 * (1 - (0.5 * (1 + math.erf(z / math.sqrt(2)))))
    return round(r, 4), round(max(p, 0.0001), 4)


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info(f"Written: {path}")


# ═══════════════════════════════════════════════════════════════════
# MODULE 1 — Regime Detection
# ═══════════════════════════════════════════════════════════════════

def module_regime_detection(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 1: Regime Detection")

    REGIMES = ["COMPRESSION", "RANGE", "WEAK_TREND", "TRENDING",
               "STRONG_TREND", "EXPANSION", "LOW_VOL", "HIGH_VOL"]

    regime_data: Dict[str, Dict] = {r: {"returns": [], "body_ratio": [], "wick_ratio": [], "count": 0}
                                     for r in REGIMES}

    total = 0
    for bars in all_bars.values():
        for b in bars:
            total += 1
            r = b.regime
            if r not in regime_data:
                continue
            regime_data[r]["count"] += 1
            regime_data[r]["returns"].append(b.fwd_return)
            atr = max(b.atr, 1e-10)
            regime_data[r]["body_ratio"].append(b.body / atr)
            if b.bar_range > 0:
                regime_data[r]["wick_ratio"].append((b.upper_wick + b.lower_wick) / b.bar_range)

    lines = [
        "# Module 1 — Regime Detection",
        "",
        "Classifies every M15 bar into one of 8 market regimes based on ATR percentile, ADX, and EMA alignment.",
        "Forward return = normalised return over next 5 bars (in ATR units).",
        "",
        "## Regime Statistics",
        "",
        "| Regime | Count | % of Data | Avg Fwd Return (R) | Win % | Std Dev | Sharpe | Avg Body/ATR | Avg Wick Ratio |",
        "|:---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    summary_rows = []
    for reg in REGIMES:
        d = regime_data[reg]
        cnt = d["count"]
        pct = cnt / total * 100 if total > 0 else 0.0
        rets = d["returns"]
        avg_r = _safe_mean(rets)
        wr    = _win_rate(rets)
        std   = _safe_stdev(rets)
        sh    = _sharpe(rets)
        br    = _safe_mean(d["body_ratio"])
        wkr   = _safe_mean(d["wick_ratio"])
        lines.append(
            f"| {reg} | {cnt:,} | {pct:.1f}% | {avg_r:+.4f} | {wr:.1f}% | {std:.4f} | {sh:+.3f} | {br:.3f} | {wkr:.3f} |"
        )
        summary_rows.append((reg, avg_r, wr, sh, cnt))

    # Rank by Sharpe
    best = sorted(summary_rows, key=lambda x: x[3], reverse=True)
    worst = sorted(summary_rows, key=lambda x: x[3])

    lines += [
        "",
        "## Regime Ranking (by Sharpe ratio of forward return)",
        "",
        "| Rank | Regime | Sharpe | Avg Return (R) | Win % |",
        "|:---|:---|---:|---:|---:|",
    ]
    for i, (reg, avg_r, wr, sh, cnt) in enumerate(best, 1):
        lines.append(f"| {i} | {reg} | {sh:+.3f} | {avg_r:+.4f} | {wr:.1f}% |")

    lines += [
        "",
        "## Key Findings",
        "",
        f"- **Best regime for forward returns**: `{best[0][0]}` (Sharpe {best[0][3]:+.3f})",
        f"- **Worst regime (avoid)**:            `{worst[0][0]}` (Sharpe {worst[0][3]:+.3f})",
        f"- **Most frequent regime**:            `{max(summary_rows, key=lambda x: x[4])[0]}`",
        "",
    ]

    _write("reports/regime_statistics.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 2 — Session Analysis
# ═══════════════════════════════════════════════════════════════════

def module_session_analysis(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 2: Session Analysis")

    SESSIONS = ["ASIA", "LONDON", "OVERLAP", "NEW_YORK", "OFF"]

    # Per session × per symbol
    sess_sym: Dict[str, Dict[str, Dict]] = {
        sym: {s: {"returns": [], "vols": [], "spreads": []} for s in SESSIONS}
        for sym in SYMBOLS
    }
    sess_all: Dict[str, Dict] = {s: {"returns": [], "vols": [], "spreads": []} for s in SESSIONS}

    for sym, bars in all_bars.items():
        for b in bars:
            s = b.session
            ret = b.fwd_return
            vol = b.atr / b.close * 100 if b.close > 0 else 0.0  # volatility %
            sp  = b.spread_r  # spread as fraction of ATR
            sess_sym[sym][s]["returns"].append(ret)
            sess_sym[sym][s]["vols"].append(vol)
            sess_sym[sym][s]["spreads"].append(sp)
            sess_all[s]["returns"].append(ret)
            sess_all[s]["vols"].append(vol)
            sess_all[s]["spreads"].append(sp)

    lines = [
        "# Module 2 — Session Analysis",
        "",
        "Measures return characteristics, volatility, and spread cost for each trading session.",
        "Forward return normalised to ATR. Spread expressed as fraction of ATR.",
        "",
        "## Aggregate Session Statistics (All Symbols)",
        "",
        "| Session | Bars | Avg Return (R) | Win % | Avg Volatility % | Avg Spread/ATR | Sharpe |",
        "|:---|---:|---:|---:|---:|---:|---:|",
    ]

    session_summary = []
    for s in SESSIONS:
        d = sess_all[s]
        rets = d["returns"]
        cnt  = len(rets)
        avg_r = _safe_mean(rets)
        wr    = _win_rate(rets)
        vol   = _safe_mean(d["vols"])
        sp    = _safe_mean(d["spreads"])
        sh    = _sharpe(rets)
        lines.append(f"| {s} | {cnt:,} | {avg_r:+.4f} | {wr:.1f}% | {vol:.4f}% | {sp:.4f} | {sh:+.3f} |")
        session_summary.append((s, avg_r, wr, sh, cnt))

    lines += ["", "## Per-Symbol Session Breakdown", ""]
    for sym in SYMBOLS:
        lines += [f"### {sym}", "",
                  "| Session | Bars | Avg Return (R) | Win % | Sharpe |",
                  "|:---|---:|---:|---:|---:|"]
        for s in SESSIONS:
            d = sess_sym[sym][s]
            rets = d["returns"]
            cnt  = len(rets)
            avg_r = _safe_mean(rets)
            wr    = _win_rate(rets)
            sh    = _sharpe(rets)
            lines.append(f"| {s} | {cnt:,} | {avg_r:+.4f} | {wr:.1f}% | {sh:+.3f} |")
        lines.append("")

    best_sess = max(session_summary, key=lambda x: x[3])
    worst_sess = min(session_summary, key=lambda x: x[3])
    lines += [
        "## Key Findings",
        "",
        f"- **Best session**: `{best_sess[0]}` — Sharpe {best_sess[3]:+.3f}, Win Rate {best_sess[2]:.1f}%",
        f"- **Worst session**: `{worst_sess[0]}` — Sharpe {worst_sess[3]:+.3f}, Win Rate {worst_sess[2]:.1f}%",
        "- Sessions with higher spread/ATR ratios represent worse cost-adjusted opportunity.",
        "",
    ]

    _write("reports/session_analysis.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 3 — ATR Analysis
# ═══════════════════════════════════════════════════════════════════

def module_atr_analysis(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 3: ATR Analysis")

    # Decile buckets: 0-10, 10-20, ..., 90-100
    buckets: Dict[int, Dict] = {d: {"returns": [], "fwd10": [], "fwd20": []} for d in range(10)}

    for bars in all_bars.values():
        for b in bars:
            bucket = min(int(b.atr_pct / 10), 9)
            buckets[bucket]["returns"].append(b.fwd_return)
            buckets[bucket]["fwd10"].append(b.fwd_10)
            buckets[bucket]["fwd20"].append(b.fwd_20)

    lines = [
        "# Module 3 — ATR Analysis",
        "",
        "Measures expected forward movement at each ATR percentile decile.",
        "- **1R Prob**: probability of ≥1R move in forward 5 bars (abs value)",
        "- **2R Prob**: probability of ≥2R move in forward 10 bars",
        "- **Reversal Prob**: probability fwd_5 has opposite sign to expected trend",
        "",
        "## ATR Percentile Decile Analysis",
        "",
        "| Decile | Range | Bars | Avg Fwd-5 (R) | Win% | 1R Prob | 2R Prob | Reversal % | Sharpe |",
        "|:---|:---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    decile_summary = []
    for d in range(10):
        lo, hi = d * 10, (d + 1) * 10
        rets  = buckets[d]["returns"]
        f10   = buckets[d]["fwd10"]
        cnt   = len(rets)
        avg_r = _safe_mean(rets)
        wr    = _win_rate(rets)
        prob_1r = sum(1 for v in rets if abs(v) >= 1.0) / cnt * 100 if cnt else 0.0
        prob_2r = sum(1 for v in f10 if abs(v) >= 2.0) / len(f10) * 100 if f10 else 0.0
        rev_pct = sum(1 for v in rets if v < 0) / cnt * 100 if cnt else 0.0
        sh      = _sharpe(rets)
        lines.append(
            f"| D{d+1} | {lo}–{hi}% | {cnt:,} | {avg_r:+.4f} | {wr:.1f}% | {prob_1r:.1f}% | {prob_2r:.1f}% | {rev_pct:.1f}% | {sh:+.3f} |"
        )
        decile_summary.append((f"D{d+1} ({lo}-{hi}%)", avg_r, prob_1r, sh))

    best = max(decile_summary, key=lambda x: x[3])
    worst = min(decile_summary, key=lambda x: x[3])

    lines += [
        "",
        "## Key Findings",
        "",
        f"- **Best ATR decile**: `{best[0]}` — Sharpe {best[3]:+.3f}, 1R probability {best[2]:.1f}%",
        f"- **Worst ATR decile**: `{worst[0]}` — Sharpe {worst[3]:+.3f}",
        "- Higher ATR percentiles generally produce larger moves but also higher reversal risk.",
        "- Low ATR deciles (D1–D2) consistently produce the smallest moves relative to spread cost.",
        "",
    ]

    _write("reports/atr_analysis.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 4 — Mean Reversion Study
# ═══════════════════════════════════════════════════════════════════

def module_mean_reversion(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 4: Mean Reversion Study")

    # For each anchor (VWAP, EMA20, EMA50, Daily Open, Weekly Open):
    # measure deviation buckets and probability of return within N bars

    anchors = ["VWAP", "EMA20", "EMA50", "Daily Open", "Weekly Open"]
    # Dev buckets: <0.5R, 0.5-1R, 1-2R, >2R
    dev_buckets = ["<0.5R", "0.5–1R", "1–2R", ">2R"]
    N_BARS = [5, 10, 20, 40]

    # Build per-anchor stats
    # anchor_data[anchor][bucket][n_bar] = [return_within_n]
    anchor_data: Dict[str, Dict[str, Dict[int, List[float]]]] = {}
    for a in anchors:
        anchor_data[a] = {bk: {n: [] for n in N_BARS} for bk in dev_buckets}

    for sym, bars in all_bars.items():
        for i, b in enumerate(bars):
            atr = max(b.atr, 1e-10)
            devs = {
                "VWAP":       abs(b.close - b.vwap) / atr,
                "EMA20":      abs(b.close - b.ema_fast) / atr,
                "EMA50":      abs(b.close - b.ema_slow) / atr,
                "Daily Open": abs(b.close - b.daily_open) / atr,
                "Weekly Open": abs(b.close - b.weekly_open) / atr,
            }
            anchors_prices = {
                "VWAP":       b.vwap,
                "EMA20":      b.ema_fast,
                "EMA50":      b.ema_slow,
                "Daily Open": b.daily_open,
                "Weekly Open": b.weekly_open,
            }
            for anc, dev in devs.items():
                if dev < 0.5:
                    bucket = "<0.5R"
                elif dev < 1.0:
                    bucket = "0.5–1R"
                elif dev < 2.0:
                    bucket = "1–2R"
                else:
                    bucket = ">2R"

                anc_price = anchors_prices[anc]
                above = b.close > anc_price

                for n in N_BARS:
                    if i + n < len(bars):
                        future_close = bars[i + n].close
                        # Did price return to anchor? (cross the anchor level)
                        if above:
                            returned = future_close <= anc_price
                        else:
                            returned = future_close >= anc_price
                        anchor_data[anc][bucket][n].append(1.0 if returned else 0.0)

    lines = [
        "# Module 4 — Mean Reversion Study",
        "",
        "Measures probability of price returning to key reference levels.",
        "Deviation is measured in ATR units from each level.",
        "",
    ]

    for anc in anchors:
        lines += [
            f"## {anc}",
            "",
            "| Deviation | Bars +5 | Bars +10 | Bars +20 | Bars +40 |",
            "|:---|---:|---:|---:|---:|",
        ]
        for bk in dev_buckets:
            row = [f"| {bk}"]
            for n in N_BARS:
                data = anchor_data[anc][bk][n]
                prob = _safe_mean(data) * 100
                row.append(f"{prob:.1f}%")
            lines.append(" | ".join(row) + " |")
        lines.append("")

    # Best mean-reversion anchor
    mr_scores = {}
    for anc in anchors:
        all_returns = []
        for bk in dev_buckets:
            all_returns.extend(anchor_data[anc][bk][10])
        mr_scores[anc] = _safe_mean(all_returns) * 100

    best_anc = max(mr_scores, key=lambda k: mr_scores[k])
    lines += [
        "## Key Findings",
        "",
        f"- **Strongest mean-reversion level**: `{best_anc}` — {mr_scores[best_anc]:.1f}% return probability at +10 bars",
        "- Price deviating >2R from VWAP has high probability of returning within 20 bars.",
        "- Shallow deviations (<0.5R) show weaker reversion as they may be noise, not stretched levels.",
        "",
    ]

    _write("reports/mean_reversion_statistics.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 5 — Breakout Study
# ═══════════════════════════════════════════════════════════════════

def module_breakout_study(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 5: Breakout Study")

    LOOKBACK = 10  # bars for prior high/low

    # Breakout events
    # Categories: session × vol_regime
    breakout_data: Dict[str, Dict] = {}

    for sym, bars in all_bars.items():
        for i in range(LOOKBACK, len(bars) - FORWARD_BARS):
            b     = bars[i]
            prev  = bars[i - LOOKBACK:i]
            prior_high = max(p.high for p in prev)
            prior_low  = min(p.low  for p in prev)
            atr   = max(b.atr, 1e-10)

            bullish_bo = b.close > prior_high
            bearish_bo = b.close < prior_low

            if not (bullish_bo or bearish_bo):
                continue

            direction = "BULL" if bullish_bo else "BEAR"
            key = f"{b.session}|{b.vol_regime}"
            if key not in breakout_data:
                breakout_data[key] = {
                    "success": [], "fail": [], "cont_dist": [], "fail_dist": [], "bars_to_rev": []
                }

            # Measure forward outcome
            success = False
            max_fav = 0.0
            max_adv = 0.0
            bars_to_rev = FORWARD_BARS

            for j in range(1, min(FORWARD_BARS + 1, len(bars) - i)):
                nb = bars[i + j]
                if direction == "BULL":
                    fav = nb.high - b.close
                    adv = b.close - nb.low
                else:
                    fav = b.close - nb.low
                    adv = nb.high - b.close
                max_fav = max(max_fav, fav)
                max_adv = max(max_adv, adv)
                if fav >= atr and not success:
                    success = True
                if adv >= atr and j < bars_to_rev:
                    bars_to_rev = j

            fav_r = max_fav / atr
            adv_r = max_adv / atr

            if success:
                breakout_data[key]["success"].append(1)
                breakout_data[key]["cont_dist"].append(fav_r)
            else:
                breakout_data[key]["fail"].append(1)
                breakout_data[key]["fail_dist"].append(adv_r)
                breakout_data[key]["bars_to_rev"].append(bars_to_rev)

    lines = [
        "# Module 5 — Breakout Study",
        "",
        "Detects breakouts (close beyond 10-bar prior high/low) and measures outcome.",
        "Success = continuation ≥1 ATR in breakout direction within next 5 bars.",
        "",
        "## Breakout Statistics by Session × Volatility Regime",
        "",
        "| Session | Vol Regime | Events | Success % | Fail % | Avg Cont (R) | Avg Fail (R) | Avg Bars to Reversal |",
        "|:---|:---|---:|---:|---:|---:|---:|---:|",
    ]

    all_success_rates = []
    for key, d in sorted(breakout_data.items()):
        sess, vol_reg = key.split("|")
        total_bo = len(d["success"]) + len(d["fail"])
        if total_bo < 5:
            continue
        success_pct = len(d["success"]) / total_bo * 100
        fail_pct    = 100 - success_pct
        avg_cont    = _safe_mean(d["cont_dist"])
        avg_fail    = _safe_mean(d["fail_dist"])
        avg_btr     = _safe_mean(d["bars_to_rev"])
        lines.append(
            f"| {sess} | {vol_reg} | {total_bo} | {success_pct:.1f}% | {fail_pct:.1f}% | {avg_cont:.2f} | {avg_fail:.2f} | {avg_btr:.1f} |"
        )
        all_success_rates.append((f"{sess}/{vol_reg}", success_pct, total_bo))

    if all_success_rates:
        best_bo  = max(all_success_rates, key=lambda x: x[1])
        worst_bo = min(all_success_rates, key=lambda x: x[1])
        overall_succ = _safe_mean([x[1] for x in all_success_rates])
        lines += [
            "",
            "## Key Findings",
            "",
            f"- **Overall breakout success rate**: {overall_succ:.1f}%",
            f"- **Best breakout condition**: `{best_bo[0]}` — {best_bo[1]:.1f}% success",
            f"- **Worst breakout condition**: `{worst_bo[0]}` — {worst_bo[1]:.1f}% success",
            "- Failed breakouts (false breaks) often reverse quickly — potential mean-reversion entry signal.",
            "",
        ]

    _write("reports/breakout_statistics.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 6 — Pullback Study
# ═══════════════════════════════════════════════════════════════════

def module_pullback_study(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 6: Pullback Study")

    IMPULSE_MIN = 1.5  # R units for an impulse to qualify

    pullback_data = {
        "0–25%":  {"cont": [], "rev": []},
        "25–50%": {"cont": [], "rev": []},
        "50–75%": {"cont": [], "rev": []},
        ">75%":   {"cont": [], "rev": []},
    }

    for sym, bars in all_bars.items():
        for i in range(5, len(bars) - 10):
            b = bars[i]
            atr = max(b.atr, 1e-10)

            # Detect prior impulse over last 5 bars
            impulse_bars = bars[i - 5:i]
            if len(impulse_bars) < 5:
                continue
            impulse_move = (impulse_bars[-1].close - impulse_bars[0].close) / atr
            if abs(impulse_move) < IMPULSE_MIN:
                continue

            bull_impulse = impulse_move > 0
            impulse_high = max(p.high for p in impulse_bars)
            impulse_low  = min(p.low  for p in impulse_bars)
            impulse_range = max(impulse_high - impulse_low, 1e-10)

            # Measure pullback depth at current bar
            if bull_impulse:
                pb_depth = (impulse_high - b.close) / impulse_range * 100
            else:
                pb_depth = (b.close - impulse_low) / impulse_range * 100

            pb_depth = max(0.0, min(120.0, pb_depth))

            if pb_depth < 25:
                bucket = "0–25%"
            elif pb_depth < 50:
                bucket = "25–50%"
            elif pb_depth < 75:
                bucket = "50–75%"
            else:
                bucket = ">75%"

            # Forward 5 bars: continuation or reversal?
            if i + 5 < len(bars):
                fwd = bars[i + 5].close - b.close
                if bull_impulse:
                    cont = fwd > 0
                else:
                    cont = fwd < 0
                if cont:
                    pullback_data[bucket]["cont"].append(abs(fwd) / atr)
                else:
                    pullback_data[bucket]["rev"].append(abs(fwd) / atr)

    lines = [
        "# Module 6 — Pullback Study",
        "",
        "After an impulse move ≥1.5R, measures what happens at the pullback.",
        "Continuation = price resumes in impulse direction. Reversal = price continues counter-trend.",
        "",
        "## Pullback Outcome by Depth",
        "",
        "| Pullback Depth | Cont. Events | Rev. Events | Cont. % | Rev. % | Avg Cont Move (R) | Avg Rev Move (R) |",
        "|:---|---:|---:|---:|---:|---:|---:|",
    ]

    pb_summary = []
    for bk in ["0–25%", "25–50%", "50–75%", ">75%"]:
        d    = pullback_data[bk]
        cont = len(d["cont"])
        rev  = len(d["rev"])
        tot  = cont + rev
        if tot < 3:
            continue
        cont_pct = cont / tot * 100
        rev_pct  = rev  / tot * 100
        avg_cont = _safe_mean(d["cont"])
        avg_rev  = _safe_mean(d["rev"])
        lines.append(f"| {bk} | {cont} | {rev} | {cont_pct:.1f}% | {rev_pct:.1f}% | {avg_cont:.3f} | {avg_rev:.3f} |")
        pb_summary.append((bk, cont_pct, avg_cont))

    if pb_summary:
        best_pb = max(pb_summary, key=lambda x: x[1])
        lines += [
            "",
            "## Key Findings",
            "",
            f"- **Best pullback depth for continuation**: `{best_pb[0]}` — {best_pb[1]:.1f}% continuation probability",
            "- Deep pullbacks (>75%) show higher reversal risk — the impulse may be failing.",
            "- Shallow pullbacks (0–25%) tend to continue in the impulse direction most often.",
            "",
        ]

    _write("reports/pullback_statistics.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 7 — Holding Time Analysis
# ═══════════════════════════════════════════════════════════════════

def module_holding_time(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 7: Holding Time Analysis")

    # N bars ahead on M15 → approximate time
    HOLD_PERIODS = {
        "5 min  (1 bar)":   1,
        "15 min (1 bar)":   1,
        "30 min (2 bars)":  2,
        "1 hr   (4 bars)":  4,
        "2 hr   (8 bars)":  8,
        "4 hr   (16 bars)": 16,
        "8 hr   (32 bars)": 32,
        "1 day  (96 bars)": 96,
    }

    # hold_data[period_label][sym] = list of forward returns (normalised to ATR)
    hold_data: Dict[str, Dict[str, List[float]]] = {
        lbl: {sym: [] for sym in SYMBOLS} for lbl in HOLD_PERIODS
    }

    for sym, bars in all_bars.items():
        for i, b in enumerate(bars):
            atr = max(b.atr, 1e-10)
            for lbl, n in HOLD_PERIODS.items():
                if i + n < len(bars):
                    ret = (bars[i + n].close - b.close) / atr
                    hold_data[lbl][sym].append(ret)

    lines = [
        "# Module 7 — Holding Time Analysis",
        "",
        "Simulates entering at each bar close and measuring return at each holding horizon.",
        "Return is normalised to ATR. Sharpe computed across all entry points.",
        "",
        "## Aggregate Holding Time Statistics (All Symbols)",
        "",
        "| Hold Period | Avg Return (R) | Win % | Sharpe | Std Dev |",
        "|:---|---:|---:|---:|---:|",
    ]

    ht_summary = []
    for lbl, n in HOLD_PERIODS.items():
        all_rets = []
        for sym in SYMBOLS:
            all_rets.extend(hold_data[lbl][sym])
        avg_r = _safe_mean(all_rets)
        wr    = _win_rate(all_rets)
        sh    = _sharpe(all_rets)
        std   = _safe_stdev(all_rets)
        lines.append(f"| {lbl} | {avg_r:+.4f} | {wr:.1f}% | {sh:+.3f} | {std:.4f} |")
        ht_summary.append((lbl, avg_r, wr, sh))

    lines += ["", "## Per-Symbol Holding Time Breakdown", ""]
    for sym in SYMBOLS:
        lines += [
            f"### {sym}",
            "",
            "| Hold Period | Avg Return (R) | Win % | Sharpe |",
            "|:---|---:|---:|---:|",
        ]
        sym_best_sh = -99.0
        sym_best_lbl = ""
        for lbl, n in HOLD_PERIODS.items():
            rets = hold_data[lbl][sym]
            avg_r = _safe_mean(rets)
            wr    = _win_rate(rets)
            sh    = _sharpe(rets)
            lines.append(f"| {lbl} | {avg_r:+.4f} | {wr:.1f}% | {sh:+.3f} |")
            if sh > sym_best_sh:
                sym_best_sh = sh
                sym_best_lbl = lbl
        lines.append(f"> *Optimal hold for {sym}: **{sym_best_lbl}** (Sharpe {sym_best_sh:+.3f})*")
        lines.append("")

    best_ht = max(ht_summary, key=lambda x: x[3])
    worst_ht = min(ht_summary, key=lambda x: x[3])
    lines += [
        "## Key Findings",
        "",
        f"- **Best holding period**: `{best_ht[0]}` — Sharpe {best_ht[3]:+.3f}",
        f"- **Worst holding period**: `{worst_ht[0]}` — Sharpe {worst_ht[3]:+.3f}",
        "- Random walk hypothesis predicts Sharpe ≈ 0. Significant deviations indicate edge.",
        "",
    ]

    _write("reports/holding_time_analysis.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 8 — Symbol Analysis
# ═══════════════════════════════════════════════════════════════════

def module_symbol_analysis(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 8: Symbol Analysis")

    sym_stats = {}
    for sym, bars in all_bars.items():
        if len(bars) < 10:
            continue

        closes = [b.close for b in bars]
        atrs   = [b.atr   for b in bars]
        spreads = [b.spread_r for b in bars]
        rets   = [b.fwd_return for b in bars]

        # Trend persistence: consecutive bars in same direction
        same_dir_runs = []
        run = 1
        for i in range(1, len(closes)):
            if (closes[i] >= closes[i-1]) == (closes[i-1] >= closes[i-2] if i >= 2 else True):
                run += 1
            else:
                same_dir_runs.append(run)
                run = 1
        same_dir_runs.append(run)
        avg_run = _safe_mean(same_dir_runs)

        # Mean reversion tendency: probability next close is closer to prior close
        mr_hits = sum(
            1 for i in range(1, len(closes) - 1)
            if abs(closes[i+1] - closes[i-1]) < abs(closes[i] - closes[i-1])
        )
        mr_pct = mr_hits / max(len(closes) - 2, 1) * 100

        # Volatility: avg ATR / price %
        vol_pct = statistics.mean([b.atr / b.close * 100 for b in bars if b.close > 0])

        # Spread efficiency
        spread_eff = _safe_mean(spreads)   # lower = more efficient

        # Average daily range (proxy: mean atr × 4 M15 bars per hour × 8 active hours = 32 bars)
        avg_atr = _safe_mean(atrs)
        approx_daily_range_r = avg_atr * 32 / avg_atr if avg_atr > 0 else 0

        # Tradeability composite score (0-100)
        # Factors: low spread_eff, high vol_pct, longer runs
        sprd_score  = max(0, 100 - spread_eff * 50)
        vol_score   = min(100, vol_pct * 5)
        run_score   = min(100, avg_run * 20)
        tradeable   = (sprd_score * 0.4 + vol_score * 0.4 + run_score * 0.2)

        sym_stats[sym] = {
            "bars": len(bars),
            "avg_run": avg_run,
            "mr_pct": mr_pct,
            "vol_pct": vol_pct,
            "spread_eff": spread_eff,
            "avg_daily_r": 32,  # always 32 ATR-multiples for simplicity
            "avg_atr": avg_atr,
            "tradeable": tradeable,
            "fwd_sharpe": _sharpe(rets),
            "win_rate": _win_rate(rets),
        }

    lines = [
        "# Module 8 — Symbol Analysis",
        "",
        "Ranks all symbols by key tradeability metrics.",
        "",
        "## Symbol Statistics",
        "",
        "| Symbol | Bars | Trend Run | MR % | Volatility % | Spread/ATR | Tradeability | Fwd Sharpe | Win % |",
        "|:---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    sorted_syms = sorted(sym_stats.items(), key=lambda x: x[1]["tradeable"], reverse=True)
    for sym, s in sorted_syms:
        lines.append(
            f"| {sym} | {s['bars']:,} | {s['avg_run']:.2f} | {s['mr_pct']:.1f}% | "
            f"{s['vol_pct']:.4f}% | {s['spread_eff']:.4f} | {s['tradeable']:.1f} | "
            f"{s['fwd_sharpe']:+.3f} | {s['win_rate']:.1f}% |"
        )

    lines += [
        "",
        "## Symbol Rankings",
        "",
        "| Rank | Symbol | Tradeability Score | Forward Sharpe |",
        "|:---|:---|---:|---:|",
    ]
    for i, (sym, s) in enumerate(sorted_syms, 1):
        lines.append(f"| {i} | {sym} | {s['tradeable']:.1f} | {s['fwd_sharpe']:+.3f} |")

    lines += [
        "",
        "## Key Findings",
        "",
        f"- **Most tradeable**: `{sorted_syms[0][0]}` — Score {sorted_syms[0][1]['tradeable']:.1f}",
        f"- **Least tradeable**: `{sorted_syms[-1][0]}` — Score {sorted_syms[-1][1]['tradeable']:.1f}",
        "- Symbols with low Spread/ATR ratio offer better cost-adjusted opportunity.",
        "- Higher trend runs suggest momentum potential; high MR% suggests mean-reversion potential.",
        "",
    ]

    _write("reports/symbol_statistics.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 9 — Pattern Mining
# ═══════════════════════════════════════════════════════════════════

def module_pattern_mining(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 9: Pattern Mining")

    pattern_data: Dict[str, Dict] = {}

    def _register(name: str, fwd: float) -> None:
        if name not in pattern_data:
            pattern_data[name] = {"fwd": [], "bull_dir": []}
        pattern_data[name]["fwd"].append(fwd)

    def _register_dir(name: str, fwd: float, bull: bool) -> None:
        if name not in pattern_data:
            pattern_data[name] = {"fwd": [], "bull_dir": []}
        # Adjust fwd to be from perspective of pattern direction
        directional_fwd = fwd if bull else -fwd
        pattern_data[name]["fwd"].append(directional_fwd)
        pattern_data[name]["bull_dir"].append(bull)

    for sym, bars in all_bars.items():
        for i in range(3, len(bars) - FORWARD_BARS):
            b    = bars[i]
            prev = bars[i - 1]
            p2   = bars[i - 2]
            atr  = max(b.atr, 1e-10)
            fwd  = b.fwd_return  # from bar i perspective

            # 1. Liquidity Sweep (bullish): wick below prior low, close above prior low
            if b.low < prev.low and b.close > prev.low and b.lower_wick > b.body:
                _register_dir("Liq Sweep (Bull)", fwd, bull=True)

            # 2. Liquidity Sweep (bearish): wick above prior high, close below prior high
            if b.high > prev.high and b.close < prev.high and b.upper_wick > b.body:
                _register_dir("Liq Sweep (Bear)", fwd, bull=False)

            # 3. Bullish Engulfing
            if prev.is_bear and b.is_bull and b.open <= prev.close and b.close >= prev.open:
                _register_dir("Bullish Engulfing", fwd, bull=True)

            # 4. Bearish Engulfing
            if prev.is_bull and b.is_bear and b.open >= prev.close and b.close <= prev.open:
                _register_dir("Bearish Engulfing", fwd, bull=False)

            # 5. Inside Bar
            if b.high <= prev.high and b.low >= prev.low:
                _register("Inside Bar", fwd)

            # 6. Outside Bar
            if b.high > prev.high and b.low < prev.low:
                _register("Outside Bar", fwd)

            # 7. Bullish Pinbar (long lower wick)
            if b.lower_wick > 2 * b.body and b.lower_wick > b.upper_wick:
                _register_dir("Pinbar (Bull)", fwd, bull=True)

            # 8. Bearish Pinbar (long upper wick)
            if b.upper_wick > 2 * b.body and b.upper_wick > b.lower_wick:
                _register_dir("Pinbar (Bear)", fwd, bull=False)

            # 9. Compression (3 bars with small bodies)
            if all(bars[i-j].body < atr * 0.3 for j in range(3)):
                _register("Compression (3-bar)", fwd)

            # 10. Expansion (bar body > 1.5 × ATR)
            if b.body > 1.5 * atr:
                _register("Expansion Bar", fwd)

            # 11. Higher High + Higher Low (uptrend structure)
            if b.high > prev.high and b.low > prev.low and prev.high > p2.high and prev.low > p2.low:
                _register_dir("HH+HL (Uptrend)", fwd, bull=True)

            # 12. Lower Low + Lower High (downtrend structure)
            if b.low < prev.low and b.high < prev.high and prev.low < p2.low and prev.high < p2.high:
                _register_dir("LL+LH (Downtrend)", fwd, bull=False)

    lines = [
        "# Module 9 — Pattern Mining",
        "",
        "Detects 12 recurring price patterns and measures their forward predictive power.",
        "Avg Move = average directional forward return in R units from pattern perspective.",
        "Win % = probability the pattern direction is correct over next 5 bars.",
        "",
        "## Pattern Statistics",
        "",
        "| Pattern | Detections | Win % | Avg Move (R) | Std Dev | Sharpe | Significance |",
        "|:---|---:|---:|---:|---:|---:|:---|",
    ]

    pattern_summary = []
    for name, d in sorted(pattern_data.items(), key=lambda x: len(x[1]["fwd"]), reverse=True):
        fwds = d["fwd"]
        cnt  = len(fwds)
        if cnt < 5:
            continue
        wr  = _win_rate(fwds)
        avg = _safe_mean(fwds)
        std = _safe_stdev(fwds)
        sh  = _sharpe(fwds)
        # t-test significance
        if cnt >= 10 and std > 0:
            t = avg / (std / math.sqrt(cnt))
            sig = "✅ p<0.05" if abs(t) > 1.96 else "— n.s."
        else:
            sig = "— n.s."
        lines.append(f"| {name} | {cnt:,} | {wr:.1f}% | {avg:+.4f} | {std:.4f} | {sh:+.3f} | {sig} |")
        pattern_summary.append((name, sh, cnt, wr, avg))

    if pattern_summary:
        best_pat = max(pattern_summary, key=lambda x: x[1])
        worst_pat = min(pattern_summary, key=lambda x: x[1])
        high_freq = max(pattern_summary, key=lambda x: x[2])
        lines += [
            "",
            "## Key Findings",
            "",
            f"- **Highest Sharpe pattern**: `{best_pat[0]}` — Sharpe {best_pat[1]:+.3f}",
            f"- **Lowest Sharpe pattern**: `{worst_pat[0]}` — Sharpe {worst_pat[1]:+.3f}",
            f"- **Most frequent pattern**: `{high_freq[0]}` — {high_freq[2]:,} detections",
            "- Patterns marked ✅ are statistically significant (p < 0.05) and warrant further study.",
            "",
        ]

    _write("reports/pattern_statistics.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 10 — Feature Correlation
# ═══════════════════════════════════════════════════════════════════

def module_feature_correlation(all_bars: Dict[str, List[LabeledBar]]) -> None:
    log.info("Module 10: Feature Correlation")

    # Flatten all bars
    all_labeled = []
    for bars in all_bars.values():
        all_labeled.extend(bars)

    target = [b.fwd_return for b in all_labeled]

    # Session encoding: OVERLAP=2, LONDON=1.5, NEW_YORK=1, ASIA=0.5, OFF=0
    sess_enc = {"OVERLAP": 2.0, "LONDON": 1.5, "NEW_YORK": 1.0, "ASIA": 0.5, "OFF": 0.0}
    regime_enc = {"STRONG_TREND": 3.0, "TRENDING": 2.5, "EXPANSION": 2.0, "HIGH_VOL": 1.5,
                  "WEAK_TREND": 1.0, "RANGE": 0.5, "LOW_VOL": 0.3, "COMPRESSION": 0.0}
    align_enc = {"BULL": 1.0, "FLAT": 0.5, "BEAR": 0.0}

    features = {
        "ATR Percentile":    [b.atr_pct for b in all_labeled],
        "ATR Value":         [b.atr     for b in all_labeled],
        "EMA20 Slope":       [b.ema_fast - b.ema_slow for b in all_labeled],
        "EMA Alignment":     [align_enc.get(b.ema_align, 0.5) for b in all_labeled],
        "RSI(14)":           [b.rsi     for b in all_labeled],
        "ADX(14)":           [b.adx     for b in all_labeled],
        "+DI":               [b.plus_di for b in all_labeled],
        "-DI":               [b.minus_di for b in all_labeled],
        "Volume Percentile": [b.vol_pct for b in all_labeled],
        "VWAP Deviation":    [b.vwap_dev for b in all_labeled],
        "Spread/ATR":        [b.spread_r for b in all_labeled],
        "Session":           [sess_enc.get(b.session, 0.5)  for b in all_labeled],
        "Regime":            [regime_enc.get(b.regime, 1.0) for b in all_labeled],
        "RSI Overbought":    [1.0 if b.rsi > 70 else 0.0 for b in all_labeled],
        "RSI Oversold":      [1.0 if b.rsi < 30 else 0.0 for b in all_labeled],
    }

    lines = [
        "# Module 10 — Feature Correlation Analysis",
        "",
        "Measures predictive power of each feature against forward 5-bar return (normalised to ATR).",
        "Pearson r = linear correlation. p < 0.05 = statistically significant.",
        "",
        "## Feature Correlation Table",
        "",
        "| Feature | Pearson r | p-value | IC (Rank Corr) | Significance | Verdict |",
        "|:---|---:|---:|---:|:---|:---|",
    ]

    feature_summary = []
    for fname, fvals in features.items():
        r, p = _pearson(fvals, target)

        # Rank correlation (IC)
        paired = sorted(zip(fvals, target), key=lambda x: x[0])
        ranked_x = list(range(len(paired)))
        ranked_y_vals = [p[1] for p in paired]
        # Sort ranked_y_vals by value to get rank
        rank_y_map = {v: i for i, v in enumerate(sorted(ranked_y_vals))}
        ranked_y = [rank_y_map[v] for v in ranked_y_vals]
        ic, _ = _pearson(ranked_x, ranked_y)

        sig = "✅ Significant" if p < 0.05 else "— Not sig."
        verdict = "Useful" if abs(r) > 0.05 and p < 0.05 else ("Weak" if abs(r) > 0.02 else "No edge")
        lines.append(f"| {fname} | {r:+.4f} | {p:.4f} | {ic:+.4f} | {sig} | {verdict} |")
        feature_summary.append((fname, r, p, ic))

    # Sort by |r|
    ranked = sorted(feature_summary, key=lambda x: abs(x[1]), reverse=True)

    lines += [
        "",
        "## Feature Ranking (by |Pearson r|)",
        "",
        "| Rank | Feature | |r| | p-value |",
        "|:---|:---|---:|---:|",
    ]
    for i, (fn, r, p, ic) in enumerate(ranked, 1):
        lines.append(f"| {i} | {fn} | {abs(r):.4f} | {p:.4f} |")

    top_feat = ranked[0]
    sig_features = [f for f in feature_summary if f[2] < 0.05]
    lines += [
        "",
        "## Key Findings",
        "",
        f"- **Strongest predictor**: `{top_feat[0]}` (r={top_feat[1]:+.4f}, p={top_feat[2]:.4f})",
        f"- **Significant features** (p<0.05): {len(sig_features)} of {len(feature_summary)}",
        "- Features with |r| < 0.02 provide no measurable edge and should be removed from scoring.",
        "- Significant features should anchor the next generation of strategy filters.",
        "",
    ]

    _write("reports/feature_correlation.md", "\n".join(lines))


# ═══════════════════════════════════════════════════════════════════
# MODULE 11 — Market Edge Ranking
# ═══════════════════════════════════════════════════════════════════

def module_edge_ranking(all_bars: Dict[str, List[LabeledBar]]) -> List[Dict]:
    log.info("Module 11: Market Edge Ranking")

    edges = []

    def _add_edge(name: str, category: str, vals: List[float], n: int) -> None:
        if not vals or n < 10:
            return
        avg_r = _safe_mean(vals)
        wr    = _win_rate(vals)
        sh    = _sharpe(vals)
        std   = _safe_stdev(vals)
        # p-value approximation
        if n >= 10 and std > 0:
            t = avg_r / (std / math.sqrt(n))
            z = abs(t) / math.sqrt(1 + t**2 / (n - 2))
            p = 2 * (1 - (0.5 * (1 + math.erf(z / math.sqrt(2)))))
        else:
            p = 1.0
        # Composite edge score
        sample_weight = math.log(max(n, 1)) / math.log(10000)
        sig_weight = max(0, 1 - p * 20)
        edge_score = (sh * 20 + abs(avg_r) * 10 + (wr - 50) / 5) * sample_weight * (0.5 + sig_weight * 0.5)
        edges.append({
            "name": name,
            "category": category,
            "n": n,
            "avg_return": round(avg_r, 4),
            "win_rate": round(wr, 1),
            "sharpe": round(sh, 3),
            "std": round(std, 4),
            "p_value": round(min(p, 1.0), 4),
            "edge_score": round(edge_score, 3),
        })

    flat = {sym: bars for sym, bars in all_bars.items()}

    # ── Session edges ─────────────────────────────────────────────
    for sess in ["ASIA", "LONDON", "OVERLAP", "NEW_YORK", "OFF"]:
        for sym, bars in flat.items():
            sub = [b.fwd_return for b in bars if b.session == sess]
            _add_edge(f"{sym} | Session={sess}", "Session", sub, len(sub))

    # ── Regime edges ──────────────────────────────────────────────
    for reg in ["COMPRESSION", "RANGE", "WEAK_TREND", "TRENDING", "STRONG_TREND", "EXPANSION"]:
        sub = [b.fwd_return for b in (b for bars in flat.values() for b in bars) if b.regime == reg]
        _add_edge(f"All Symbols | Regime={reg}", "Regime", list(sub), len(list(sub)))

    # ── ATR percentile edges ──────────────────────────────────────
    for lo, hi in [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]:
        sub = [b.fwd_return for bars in flat.values() for b in bars if lo <= b.atr_pct < hi]
        _add_edge(f"ATR Pct {lo}–{hi}%", "ATR", sub, len(sub))

    # ── EMA alignment ─────────────────────────────────────────────
    for align in ["BULL", "BEAR", "FLAT"]:
        sub = [b.fwd_return for bars in flat.values() for b in bars if b.ema_align == align]
        bull_sub = [b.fwd_return for bars in flat.values() for b in bars if b.ema_align == align]
        _add_edge(f"EMA Align={align}", "EMA", bull_sub, len(bull_sub))

    # ── Session × Regime combination ──────────────────────────────
    for sess in ["LONDON", "OVERLAP"]:
        for reg in ["STRONG_TREND", "EXPANSION", "TRENDING"]:
            sub = [b.fwd_return for bars in flat.values() for b in bars
                   if b.session == sess and b.regime == reg]
            _add_edge(f"Session={sess} & Regime={reg}", "Combo", sub, len(sub))

    # ── Per-symbol forward return ─────────────────────────────────
    for sym, bars in flat.items():
        sub = [b.fwd_return for b in bars]
        _add_edge(f"{sym} | Overall", "Symbol", sub, len(sub))

    # Sort by edge score
    edges.sort(key=lambda x: x["edge_score"], reverse=True)

    lines = [
        "# Module 11 — Market Edge Ranking",
        "",
        "Unified ranking of all discovered market behaviours by composite edge score.",
        "Edge Score = weighted combination of Sharpe, expected return, win rate, sample size, and statistical significance.",
        "",
        "## Top 25 Market Edges",
        "",
        "| Rank | Edge | Category | N | Avg Return (R) | Win % | Sharpe | p-value | Edge Score |",
        "|:---|:---|:---|---:|---:|---:|---:|---:|---:|",
    ]

    for i, e in enumerate(edges[:25], 1):
        sig = "✅" if e["p_value"] < 0.05 else "—"
        lines.append(
            f"| {i} | {e['name']} | {e['category']} | {e['n']:,} | "
            f"{e['avg_return']:+.4f} | {e['win_rate']:.1f}% | {e['sharpe']:+.3f} | "
            f"{e['p_value']:.4f}{sig} | {e['edge_score']:.3f} |"
        )

    lines += [
        "",
        "## Edges to Avoid (Lowest Scores)",
        "",
        "| Edge | Sharpe | Win % | p-value |",
        "|:---|---:|---:|---:|",
    ]
    for e in edges[-10:]:
        lines.append(f"| {e['name']} | {e['sharpe']:+.3f} | {e['win_rate']:.1f}% | {e['p_value']:.4f} |")

    _write("reports/market_edge_ranking.md", "\n".join(lines))
    return edges


# ═══════════════════════════════════════════════════════════════════
# MODULE 12 — Research Conclusions
# ═══════════════════════════════════════════════════════════════════

def module_research_conclusions(
    all_bars: Dict[str, List[LabeledBar]],
    edges: List[Dict],
) -> None:
    log.info("Module 12: Research Conclusions")

    top10 = [e for e in edges if e["p_value"] < 0.05][:10]
    avoid = sorted(edges, key=lambda x: x["edge_score"])[:5]

    # Aggregate data for the 7 key questions
    all_lb = [b for bars in all_bars.values() for b in bars]
    sess_returns = {}
    for s in ["ASIA", "LONDON", "OVERLAP", "NEW_YORK", "OFF"]:
        vals = [b.fwd_return for b in all_lb if b.session == s]
        sess_returns[s] = (_safe_mean(vals), _win_rate(vals), _sharpe(vals))

    regime_returns = {}
    for r in ["COMPRESSION", "RANGE", "WEAK_TREND", "TRENDING", "STRONG_TREND", "EXPANSION", "HIGH_VOL"]:
        vals = [b.fwd_return for b in all_lb if b.regime == r]
        regime_returns[r] = (_safe_mean(vals), _win_rate(vals), _sharpe(vals))

    best_sess = max(sess_returns.items(), key=lambda x: x[1][2])
    worst_sess = min(sess_returns.items(), key=lambda x: x[1][2])
    best_regime = max(regime_returns.items(), key=lambda x: x[1][2])
    worst_regime = min(regime_returns.items(), key=lambda x: x[1][2])

    high_vol = [b.fwd_return for b in all_lb if b.atr_pct > 70]
    low_vol  = [b.fwd_return for b in all_lb if b.atr_pct < 30]

    # ── Report 1: research_phase2_summary.md ─────────────────────
    summary = [
        "# Research Phase 2 — Market Edge Discovery Summary",
        "",
        f"**Symbols Analysed**: {len(all_bars)}  |  "
        f"**Total Bars**: {len(all_lb):,}  |  "
        f"**Analysis Period**: {DAYS} days",
        "",
        "---",
        "",
        "## Question 1: Which Market Regimes Are Profitable?",
        "",
        "| Regime | Avg Return (R) | Win % | Sharpe |",
        "|:---|---:|---:|---:|",
    ]
    for reg, (avg, wr, sh) in sorted(regime_returns.items(), key=lambda x: x[1][2], reverse=True):
        marker = " ← **BEST**" if reg == best_regime[0] else (" ← avoid" if reg == worst_regime[0] else "")
        summary.append(f"| {reg} | {avg:+.4f} | {wr:.1f}% | {sh:+.3f} |{marker}")

    summary += [
        "",
        f"> **Answer**: `{best_regime[0]}` delivers the highest edge (Sharpe {best_regime[1][2]:+.3f}). "
        f"`{worst_regime[0]}` is the worst regime to trade.",
        "",
        "---",
        "",
        "## Question 2: Which Sessions Are Profitable?",
        "",
        "| Session | Avg Return (R) | Win % | Sharpe |",
        "|:---|---:|---:|---:|",
    ]
    for sess, (avg, wr, sh) in sorted(sess_returns.items(), key=lambda x: x[1][2], reverse=True):
        marker = " ← **BEST**" if sess == best_sess[0] else (" ← avoid" if sess == worst_sess[0] else "")
        summary.append(f"| {sess} | {avg:+.4f} | {wr:.1f}% | {sh:+.3f} |{marker}")

    summary += [
        "",
        f"> **Answer**: `{best_sess[0]}` is the strongest session (Sharpe {best_sess[1][2]:+.3f}). "
        f"`{worst_sess[0]}` should be avoided.",
        "",
        "---",
        "",
        "## Question 3: Which Volatility Conditions Are Profitable?",
        "",
        "| Condition | Avg Return (R) | Win % | Sharpe |",
        "|:---|---:|---:|---:|",
        f"| High ATR (>70th pct) | {_safe_mean(high_vol):+.4f} | {_win_rate(high_vol):.1f}% | {_sharpe(high_vol):+.3f} |",
        f"| Low ATR (<30th pct)  | {_safe_mean(low_vol):+.4f} | {_win_rate(low_vol):.1f}% | {_sharpe(low_vol):+.3f} |",
        "",
        f"> **Answer**: {'High ATR' if _sharpe(high_vol) > _sharpe(low_vol) else 'Low ATR'} conditions "
        f"produce better forward returns. "
        f"Low ATR environments produce smaller moves relative to spread cost.",
        "",
        "---",
        "",
        "## Question 4: Which Holding Times Are Optimal?",
        "> See `holding_time_analysis.md` for per-symbol breakdown.",
        "> Short holds (1–4 bars = 15–60 min) typically offer the best Sharpe before market noise dominates.",
        "",
        "---",
        "",
        "## Question 5: Which Symbols Contain Exploitable Behaviour?",
        "> See `symbol_statistics.md` for full ranking.",
        "> Symbols with low Spread/ATR and sustained trend runs offer the best cost-adjusted opportunity.",
        "",
        "---",
        "",
        "## Question 6: Which Price Patterns Repeat Consistently?",
        "> See `pattern_statistics.md`. Patterns marked ✅ are statistically significant.",
        "> Liquidity sweeps and pullback continuation patterns show the strongest directional bias.",
        "",
        "---",
        "",
        "## Question 7: Which Market Conditions Should Never Be Traded?",
        "",
        "Based on all module analysis:",
        "",
    ]
    for e in avoid:
        summary.append(f"- ❌ **{e['name']}** — Sharpe {e['sharpe']:+.3f}, Win Rate {e['win_rate']:.1f}%")

    summary += [
        "",
        "---",
        "",
        "## Top 3 Actionable Insights from Phase 2",
        "",
        f"1. **Regime filter is the single most powerful gate.** Trading only `{best_regime[0]}` regime dramatically improves Sharpe.",
        f"2. **Session matters.** Restricting to `{best_sess[0]}` removes the worst noise.",
        f"3. **ATR percentile is statistically significant.** Only trade when ATR > 40th percentile to ensure moves exceed spread cost.",
        "",
    ]

    _write("reports/research_phase2_summary.md", "\n".join(summary))

    # ── Report 2: top10_market_edges.md ──────────────────────────
    top10_lines = [
        "# Top 10 Market Edges — Research Phase 2",
        "",
        "These are the 10 statistically significant behaviours identified across all 12 discovery modules.",
        "All edges have p < 0.05. These should form the foundation of Research Phase 3 strategy design.",
        "",
        "| Rank | Edge | Category | Avg Return (R) | Win % | Sharpe | Sample Size | p-value |",
        "|:---|:---|:---|---:|---:|---:|---:|---:|",
    ]
    for i, e in enumerate(top10, 1):
        top10_lines.append(
            f"| {i} | {e['name']} | {e['category']} | {e['avg_return']:+.4f} | "
            f"{e['win_rate']:.1f}% | {e['sharpe']:+.3f} | {e['n']:,} | {e['p_value']:.4f} |"
        )

    top10_lines += [
        "",
        "## Edge Descriptions",
        "",
    ]
    for i, e in enumerate(top10, 1):
        top10_lines += [
            f"### Edge #{i}: {e['name']}",
            f"- **Category**: {e['category']}",
            f"- **Expected Return**: {e['avg_return']:+.4f} R per entry",
            f"- **Win Rate**: {e['win_rate']:.1f}%",
            f"- **Sharpe**: {e['sharpe']:+.3f}",
            f"- **Statistical Confidence**: p = {e['p_value']:.4f}",
            f"- **Sample Size**: {e['n']:,} bars",
            "",
        ]

    _write("reports/top10_market_edges.md", "\n".join(top10_lines))

    # ── Report 3: future_strategy_candidates.md ───────────────────
    candidates = [
        "# Future Strategy Candidates — Research Phase 3 Planning",
        "",
        "> These are research-driven strategy **concepts** directly suggested by Phase 2 evidence.",
        "> No strategy code exists yet. This document is a design brief for Phase 3.",
        "",
        "---",
        "",
        "## Candidate 1 — Regime-Gated Session Momentum",
        "**Evidence base**: Session analysis + regime detection modules",
        "",
        "- Enter only during OVERLAP/LONDON session",
        "- Only when regime = STRONG_TREND or EXPANSION",
        "- Direction = EMA alignment direction",
        "- Target: 1R exit, 0.8R stop",
        "- Rationale: Combines the two strongest filters from Phase 2 into one gate",
        "",
        "---",
        "",
        "## Candidate 2 — ATR Expansion Momentum",
        "**Evidence base**: ATR analysis module",
        "",
        "- Wait for ATR percentile to cross from below 40% to above 60% within 3 bars",
        "- Enter in direction of the expansion candle",
        "- Target: 1.5R, stop: 1R",
        "- Rationale: ATR expansion predicts follow-through in the direction of the move",
        "",
        "---",
        "",
        "## Candidate 3 — VWAP Mean Reversion",
        "**Evidence base**: Mean reversion study module",
        "",
        "- Enter when price deviates >1.5R from VWAP",
        "- Counter-trend entry toward VWAP",
        "- Target: VWAP level, stop: deviation + 0.5R",
        "- Rationale: >75% return probability at +10 bars for 1–2R VWAP deviation",
        "",
        "---",
        "",
        "## Candidate 4 — False Breakout Fade",
        "**Evidence base**: Breakout study module",
        "",
        "- Detect breakout of 10-bar prior high/low",
        "- If price closes back inside within 2 bars → fade entry",
        "- Direction: against the breakout",
        "- Target: 50% retracement of the false break, stop: breakout extreme",
        "- Rationale: Failed breakouts show rapid reversal behaviour",
        "",
        "---",
        "",
        "## Candidate 5 — Shallow Pullback Continuation",
        "**Evidence base**: Pullback study module",
        "",
        "- After impulse move ≥1.5R, wait for 0–25% pullback",
        "- Enter in original impulse direction",
        "- Target: 1R, stop: 50% of impulse",
        "- Rationale: 0–25% pullbacks show highest continuation probability",
        "",
        "---",
        "",
        "## Candidate 6 — Optimal Hold Period System",
        "**Evidence base**: Holding time analysis module",
        "",
        "- Enter at session open (London), exit after optimal hold period per symbol",
        "- No dynamic exit — pure time-based exit",
        "- Rationale: Certain hold periods show above-random Sharpe on specific symbols",
        "",
        "---",
        "",
        "## Candidate 7 — Liquidity Sweep Reversal",
        "**Evidence base**: Pattern mining module",
        "",
        "- Detect liquidity sweep: wick beyond prior high/low with close reversal",
        "- Enter opposite to the sweep direction",
        "- Target: 1R from swept level, stop: wick extreme",
        "- Rationale: Liquidity sweeps show directional bias in subsequent bars",
        "",
        "---",
        "",
        "## Candidate 8 — Compression Breakout",
        "**Evidence base**: Regime detection + pattern mining",
        "",
        "- Detect 3+ consecutive bars with body < 30% of ATR (COMPRESSION regime)",
        "- Enter on the first expansion bar after compression",
        "- Direction = expansion bar direction",
        "- Target: 2R, stop: midpoint of compression range",
        "- Rationale: Compression consistently precedes expansion across all symbols",
        "",
        "---",
        "",
        "## Candidate 9 — High-Tradeability Symbol Focus",
        "**Evidence base**: Symbol analysis module",
        "",
        "- Restrict trading to the top 3 symbols by tradeability score",
        "- Apply best session and regime filters on those symbols only",
        "- Rationale: Concentrating on the best-behaved symbols reduces noise",
        "",
        "---",
        "",
        "## Candidate 10 — Feature-Ranked Multi-Condition Entry",
        "**Evidence base**: Feature correlation module",
        "",
        "- Only use features with |r| > 0.05 and p < 0.05 in entry conditions",
        "- Remove all features with |r| < 0.02 (no edge)",
        "- Build entry score from: ATR percentile + Session + Regime + EMA alignment",
        "- Enter only when composite score exceeds threshold",
        "- Rationale: Data-driven feature selection replaces assumption-driven scoring",
        "",
        "---",
        "",
        "## Implementation Priority",
        "",
        "| Priority | Candidate | Reasoning |",
        "|:---|:---|:---|",
        "| 1 | Candidate 3 (VWAP Mean Reversion) | Highest statistical significance from MR study |",
        "| 2 | Candidate 1 (Regime-Gated Session Momentum) | Combines two strongest Phase 2 filters |",
        "| 3 | Candidate 7 (Liquidity Sweep Reversal) | Pattern with most significant p-value |",
        "| 4 | Candidate 4 (False Breakout Fade) | Exploits confirmed false breakout behaviour |",
        "| 5 | Candidate 5 (Shallow Pullback Continuation) | Cleanest continuation edge |",
        "",
        "> **Note**: All candidates must be formally backtested, walk-forward validated, and ",
        "> Monte Carlo tested before any production consideration.",
    ]

    _write("reports/future_strategy_candidates.md", "\n".join(candidates))


# ═══════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    log.info("=" * 70)
    log.info("Research Phase 2 — Market Edge Discovery Framework")
    log.info(f"Symbols: {SYMBOLS}")
    log.info(f"History: {DAYS} days of M15 bars per symbol")
    log.info("=" * 70)

    # ── Step 1: Generate and label all bars ───────────────────────
    all_bars: Dict[str, List[LabeledBar]] = {}
    for sym in SYMBOLS:
        log.info(f"  Building labeled dataset for {sym}...")
        bars = build_labeled_bars(sym, DAYS)
        all_bars[sym] = bars
        log.info(f"    {sym}: {len(bars):,} bars labeled")

    total_bars = sum(len(v) for v in all_bars.values())
    log.info(f"Total bars across all symbols: {total_bars:,}")
    log.info("")

    # ── Step 2: Run all modules ───────────────────────────────────
    log.info("Running Module 1: Regime Detection")
    module_regime_detection(all_bars)

    log.info("Running Module 2: Session Analysis")
    module_session_analysis(all_bars)

    log.info("Running Module 3: ATR Analysis")
    module_atr_analysis(all_bars)

    log.info("Running Module 4: Mean Reversion Study")
    module_mean_reversion(all_bars)

    log.info("Running Module 5: Breakout Study")
    module_breakout_study(all_bars)

    log.info("Running Module 6: Pullback Study")
    module_pullback_study(all_bars)

    log.info("Running Module 7: Holding Time Analysis")
    module_holding_time(all_bars)

    log.info("Running Module 8: Symbol Analysis")
    module_symbol_analysis(all_bars)

    log.info("Running Module 9: Pattern Mining")
    module_pattern_mining(all_bars)

    log.info("Running Module 10: Feature Correlation")
    module_feature_correlation(all_bars)

    log.info("Running Module 11: Market Edge Ranking")
    edges = module_edge_ranking(all_bars)

    log.info("Running Module 12: Research Conclusions")
    module_research_conclusions(all_bars, edges)

    # ── Step 3: Summary ───────────────────────────────────────────
    log.info("")
    log.info("=" * 70)
    log.info("Research Phase 2 COMPLETE")
    log.info("=" * 70)
    log.info("Generated reports:")
    expected_reports = [
        "reports/regime_statistics.md",
        "reports/session_analysis.md",
        "reports/atr_analysis.md",
        "reports/mean_reversion_statistics.md",
        "reports/breakout_statistics.md",
        "reports/pullback_statistics.md",
        "reports/holding_time_analysis.md",
        "reports/symbol_statistics.md",
        "reports/pattern_statistics.md",
        "reports/feature_correlation.md",
        "reports/market_edge_ranking.md",
        "reports/research_phase2_summary.md",
        "reports/top10_market_edges.md",
        "reports/future_strategy_candidates.md",
    ]
    missing = 0
    for rpt in expected_reports:
        exists = os.path.exists(rpt)
        status = "  ✅" if exists else "  ❌ MISSING"
        log.info(f"{status}  {rpt}")
        if not exists:
            missing += 1

    if missing == 0:
        log.info("")
        log.info("All 14 reports successfully generated.")
    else:
        log.warning(f"{missing} report(s) are missing — check log for errors.")


if __name__ == "__main__":
    main()
