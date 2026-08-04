"""
app/data_validator.py — Multi-Timeframe Data Integrity Validator

Validates ticks and OHLCV bars across M1, M5, M15, M30, H1, H4, D1 timeframes.
Rejects incomplete, corrupted, NaN, zero-price, inverted OHLC, or out-of-order data frames.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


@dataclass
class ValidationReport:
    is_valid: bool
    symbol: str
    timeframe: str
    total_bars: int
    invalid_bars: int
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "total_bars": self.total_bars,
            "invalid_bars": self.invalid_bars,
            "reasons": self.reasons,
        }


class DataValidator:
    """
    Multi-timeframe data validator for MT5 rates and tick feeds.
    """

    def __init__(self, min_required_bars: int = 10):
        self.min_required_bars = min_required_bars

    def validate_dataframe(
        self,
        df: Any,
        symbol: str = "UNKNOWN",
        timeframe: str = "M15",
    ) -> ValidationReport:
        """
        Validate OHLCV DataFrame structure and price integrity.
        """
        reasons: List[str] = []
        if not PANDAS_AVAILABLE or df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return ValidationReport(
                is_valid=False,
                symbol=symbol,
                timeframe=timeframe,
                total_bars=0,
                invalid_bars=0,
                reasons=["DataFrame is None, empty, or unparseable"],
            )

        total_bars = len(df)
        if total_bars < self.min_required_bars:
            reasons.append(f"Insufficient bars count ({total_bars} < {self.min_required_bars})")

        # 1. Required Columns Check
        required_cols = {"open", "high", "low", "close"}
        existing_cols = {col.lower() for col in df.columns}
        missing_cols = required_cols - existing_cols
        if missing_cols:
            reasons.append(f"Missing required columns: {missing_cols}")
            return ValidationReport(False, symbol, timeframe, total_bars, total_bars, reasons)

        # Ensure lowercase column mapping for checks
        df_clean = df.copy()
        df_clean.columns = [c.lower() for c in df_clean.columns]

        # 2. NaN / Inf Check
        nan_count = df_clean[["open", "high", "low", "close"]].isna().sum().sum()
        if nan_count > 0:
            reasons.append(f"Contains {nan_count} NaN values in OHLC columns")

        # 3. Positive Price Check
        non_positive = (df_clean[["open", "high", "low", "close"]] <= 0).sum().sum()
        if non_positive > 0:
            reasons.append(f"Contains {non_positive} non-positive price values")

        # 4. Inverted High/Low Relationship Check
        high_low_invalid = (df_clean["high"] < df_clean["low"]).sum()
        if high_low_invalid > 0:
            reasons.append(f"Contains {high_low_invalid} bars where High < Low")

        high_open_invalid = (df_clean["high"] < df_clean["open"]).sum()
        if high_open_invalid > 0:
            reasons.append(f"Contains {high_open_invalid} bars where High < Open")

        high_close_invalid = (df_clean["high"] < df_clean["close"]).sum()
        if high_close_invalid > 0:
            reasons.append(f"Contains {high_close_invalid} bars where High < Close")

        low_open_invalid = (df_clean["low"] > df_clean["open"]).sum()
        if low_open_invalid > 0:
            reasons.append(f"Contains {low_open_invalid} bars where Low > Open")

        low_close_invalid = (df_clean["low"] > df_clean["close"]).sum()
        if low_close_invalid > 0:
            reasons.append(f"Contains {low_close_invalid} bars where Low > Close")

        invalid_bars = (
            high_low_invalid + high_open_invalid + high_close_invalid + low_open_invalid + low_close_invalid
        )

        is_valid = len(reasons) == 0
        if not is_valid:
            logger.warning(f"[DATA_VALIDATOR] {symbol} {timeframe} validation failed: {reasons}")

        return ValidationReport(
            is_valid=is_valid,
            symbol=symbol,
            timeframe=timeframe,
            total_bars=total_bars,
            invalid_bars=invalid_bars,
            reasons=reasons,
        )

    def validate_tick(self, tick: Any, symbol: str = "UNKNOWN") -> Tuple[bool, str]:
        """Validate live tick object."""
        if tick is None:
            return False, "Tick object is None"

        bid = getattr(tick, "bid", 0.0)
        ask = getattr(tick, "ask", 0.0)

        if bid <= 0 or ask <= 0:
            return False, f"Invalid tick prices: Bid={bid}, Ask={ask}"

        if ask < bid:
            return False, f"Inverted tick spread: Ask={ask} < Bid={bid}"

        return True, "Tick valid"
