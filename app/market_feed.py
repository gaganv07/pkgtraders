"""
app/market_feed.py — Live Market Feed & Historical Data Engine

Retrieves real-time ticks and historical bar data directly from MetaTrader 5 terminal
using copy_rates_from_pos(). Computes ATR, EMA, RSI, VWAP, and tick volume indicators,
and formats data into pandas DataFrames for strategy modules.

NO CSV, mock, or synthetic data is used for live mode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


#: Timeframe String to MT5 Constant Mapping
TIMEFRAME_MAP: Dict[str, int] = {}
if MT5_AVAILABLE and mt5 is not None:
    TIMEFRAME_MAP = {
        "M1":  mt5.TIMEFRAME_M1,
        "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,
        "D1":  mt5.TIMEFRAME_D1,
    }


@dataclass
class LiveTick:
    symbol: str
    time: datetime
    bid: float
    ask: float
    spread: float
    spread_pts: int
    volume: int
    flags: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


class MarketFeed:
    """
    Live market data feed & historical bar manager.
    """

    def __init__(self, symbol_resolver: Optional[Any] = None):
        self.symbol_resolver = symbol_resolver

    def _resolve(self, symbol: str) -> str:
        """Resolve canonical symbol to broker symbol if resolver available."""
        if self.symbol_resolver and hasattr(self.symbol_resolver, "resolve_broker_symbol"):
            return self.symbol_resolver.resolve_broker_symbol(symbol)
        return symbol

    def get_live_tick(self, symbol: str) -> Optional[LiveTick]:
        """
        Fetch latest live tick from MT5 terminal for the specified symbol.
        Returns LiveTick object with bid, ask, spread, time, and volume.
        """
        if not MT5_AVAILABLE:
            logger.error("MT5 library unavailable — cannot fetch live tick")
            return None

        broker_sym = self._resolve(symbol)
        tick = mt5.symbol_info_tick(broker_sym)
        if tick is None:
            code, msg = mt5.last_error()
            logger.warning(f"Failed to fetch tick for {symbol} ({broker_sym}): [{code}] {msg}")
            return None

        spread = tick.ask - tick.bid
        info = mt5.symbol_info(broker_sym)
        point = info.point if info else 0.01
        spread_pts = int(round(spread / point)) if point > 0 else 0

        # Convert timestamp to UTC datetime
        dt_time = datetime.fromtimestamp(tick.time, tz=timezone.utc)

        return LiveTick(
            symbol=symbol,
            time=dt_time,
            bid=tick.bid,
            ask=tick.ask,
            spread=spread,
            spread_pts=spread_pts,
            volume=int(tick.volume),
            flags=int(tick.flags),
        )

    def get_historical_rates(
        self,
        symbol: str,
        timeframe: str = "M15",
        count: int = 300,
        start_pos: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Download historical bars directly from MT5 terminal using copy_rates_from_pos().
        Supported timeframes: M1, M5, M15, M30, H1, H4, D1.
        """
        if not MT5_AVAILABLE:
            logger.error("MT5 library unavailable — cannot download historical rates")
            return []

        broker_sym = self._resolve(symbol)
        tf_const = TIMEFRAME_MAP.get(timeframe.upper())
        if tf_const is None:
            logger.error(f"Unsupported timeframe '{timeframe}'. Allowed: {list(TIMEFRAME_MAP.keys())}")
            return []

        rates = mt5.copy_rates_from_pos(broker_sym, tf_const, start_pos, count)
        if rates is None or len(rates) == 0:
            code, msg = mt5.last_error()
            logger.warning(f"copy_rates_from_pos returned no data for {symbol} ({timeframe}): [{code}] {msg}")
            return []

        formatted_rates = []
        for r in rates:
            formatted_rates.append({
                "time": datetime.fromtimestamp(r[0], tz=timezone.utc),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "tick_volume": int(r[5]),
                "spread": float(r[6]),
                "real_volume": int(r[7]),
            })

        return formatted_rates

    def get_historical_dataframe(
        self,
        symbol: str,
        timeframe: str = "M15",
        count: int = 300,
        include_indicators: bool = True,
    ) -> pd.DataFrame:
        """
        Download historical bars from MT5 and return a clean pandas DataFrame
        with calculated technical indicators (ATR, EMA50, EMA200, RSI, VWAP).
        Ready for strategy module consumption.
        """
        raw_rates = self.get_historical_rates(symbol, timeframe, count)
        if not raw_rates:
            return pd.DataFrame()

        df = pd.DataFrame(raw_rates)
        df.set_index("time", inplace=False)

        if include_indicators and not df.empty:
            df = self.calculate_indicators(df)

        return df

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute standard technical indicators on an OHLCV DataFrame:
        - ATR (14)
        - EMA (50, 200)
        - RSI (14)
        - Session VWAP
        """
        df = df.copy()
        high = df["high"]
        low = df["low"]
        close = df["close"]
        volume = df["tick_volume"]

        # 1. ATR (14)
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()

        # 2. EMAs
        df["ema50"] = close.ewm(span=50, adjust=False).mean()
        df["ema200"] = close.ewm(span=200, adjust=False).mean()

        # 3. RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(span=14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(span=14, adjust=False).mean()
        rs = gain / (loss.replace(0, 1e-10))
        df["rsi"] = 100 - (100 / (1 + rs))

        # 4. VWAP (Cumulative per session or window)
        typical_price = (high + low + close) / 3.0
        cum_tp_vol = (typical_price * volume.replace(0, 1)).cumsum()
        cum_vol = volume.replace(0, 1).cumsum()
        df["vwap"] = cum_tp_vol / cum_vol

        return df
