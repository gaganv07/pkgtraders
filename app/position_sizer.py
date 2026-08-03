"""
app/position_sizer.py — Universal Position Sizing Engine

The single canonical implementation for ALL position sizing across:
  - Live trading (TradeEngine)
  - Backtesting (strategy_validation, btc_strategy_validation)
  - Research (btc_strategy_research, strategy_research)
  - Paper trading

Architecture
------------
BrokerSpec       : Immutable snapshot of MT5 symbol properties per trade.
SizingResult     : Full record of one sizing decision (21 fields).
PositionSizer    : Stateless sizer — call size() before every order.

Formula
-------
    risk_amount  = balance × (risk_pct / 100)
    sl_points    = round(abs(entry - stop_loss) / tick_size)
    raw_lot      = risk_amount / (sl_points × tick_value)
    final_lot    = floor(raw_lot / vol_step) × vol_step
    final_lot    = clamp(final_lot, vol_min, vol_max)

SizingResult is automatically appended to reports/position_size_history.csv
on every call so reports can be generated without any extra instrumentation.

Usage
-----
    from app.position_sizer import PositionSizer, BrokerSpec

    spec = BrokerSpec.from_spec_dict(client.get_symbol_spec("BTCUSD"))
    result = PositionSizer.size(
        balance=account_balance,
        entry=entry_price,
        stop_loss=sl_price,
        tp_price=tp1_price,
        risk_pct=1.0,
        spec=spec,
        strategy="BTC_P3_OrderFlow",
        symbol="BTCUSD",
    )
    if result.final_lot > 0:
        place_order(result.final_lot)
"""

from __future__ import annotations

import csv
import logging
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Path for the auto-written CSV that feeds all 8 reports
_REPORT_DIR = Path(__file__).parent.parent / "reports"
_HISTORY_CSV = _REPORT_DIR / "position_size_history.csv"

# ── CSV field order (21 fields) ────────────────────────────────────────────────
_CSV_FIELDS = [
    "timestamp", "strategy", "symbol",
    "balance", "equity", "free_margin",
    "risk_pct", "risk_amount",
    "entry_price", "stop_loss", "tp_price",
    "sl_distance", "sl_points", "tp_distance", "tp_points",
    "tick_size", "tick_value", "contract_size",
    "raw_lot", "final_lot", "executed_lot",
    "expected_loss", "expected_reward", "risk_reward_ratio",
    "vol_min", "vol_max", "vol_step",
    "margin_used",
    "trade_id",
]


# ══════════════════════════════════════════════════════════════════════════════
# Broker spec snapshot
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BrokerSpec:
    """
    Immutable snapshot of the MT5 symbol properties required for sizing.
    Call BrokerSpec.from_spec_dict(client.get_symbol_spec(symbol)) to build.
    """
    symbol:        str   = "UNKNOWN"
    vol_min:       float = 0.01
    vol_max:       float = 50.0
    vol_step:      float = 0.01
    tick_size:     float = 0.01
    tick_value:    float = 0.01   # USD per tick per 1.0 lot
    contract_size: float = 100.0
    digits:        int   = 2
    point:         float = 0.01

    @classmethod
    def from_spec_dict(cls, d: Dict, symbol: str = "UNKNOWN") -> "BrokerSpec":
        """Build from the dict returned by MT5Client.get_symbol_spec()."""
        if not d:
            logger.warning(f"[BrokerSpec] Empty spec for {symbol} — using defaults")
            return cls(symbol=symbol)
        return cls(
            symbol        = symbol,
            vol_min       = float(d.get("vol_min",       0.01)),
            vol_max       = float(d.get("vol_max",       50.0)),
            vol_step      = float(d.get("vol_step",      0.01)),
            tick_size     = float(d.get("tick_size",     d.get("point", 0.01))),
            tick_value    = float(d.get("tick_value",    d.get("point", 0.01))),
            contract_size = float(d.get("contract_size", 100.0)),
            digits        = int(d.get("digits",          2)),
            point         = float(d.get("point",         0.01)),
        )

    @classmethod
    def fallback(cls, symbol: str) -> "BrokerSpec":
        """Return a conservative offline fallback spec for known symbols."""
        _defaults: Dict[str, Dict] = {
            "XAUUSD": dict(vol_min=0.01, vol_max=50.0,  vol_step=0.01, tick_size=0.01,  tick_value=1.0,   contract_size=100.0,  digits=2),
            "ETHUSD": dict(vol_min=0.01, vol_max=50.0,  vol_step=0.01, tick_size=0.01,  tick_value=0.01,  contract_size=1.0,    digits=2),
            "BTCUSD": dict(vol_min=0.01, vol_max=50.0,  vol_step=0.01, tick_size=0.01,  tick_value=0.01,  contract_size=1.0,    digits=2),
            "EURUSD": dict(vol_min=0.01, vol_max=150.0, vol_step=0.01, tick_size=0.0001,tick_value=1.0,   contract_size=100_000.0, digits=5),
            "GBPUSD": dict(vol_min=0.01, vol_max=150.0, vol_step=0.01, tick_size=0.0001,tick_value=1.0,   contract_size=100_000.0, digits=5),
            "USDJPY": dict(vol_min=0.01, vol_max=150.0, vol_step=0.01, tick_size=0.001, tick_value=0.009, contract_size=100_000.0, digits=3),
            "NAS100": dict(vol_min=0.01, vol_max=50.0,  vol_step=0.01, tick_size=0.01,  tick_value=0.01,  contract_size=1.0,    digits=2),
            "US30":   dict(vol_min=0.01, vol_max=50.0,  vol_step=0.01, tick_size=0.01,  tick_value=0.01,  contract_size=1.0,    digits=2),
        }
        spec = _defaults.get(symbol, {})
        return cls(symbol=symbol, **spec) if spec else cls(symbol=symbol)


# ══════════════════════════════════════════════════════════════════════════════
# Sizing result (21 fields)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SizingResult:
    """Full record of one position-sizing decision. 21 fields."""
    timestamp:       str   = ""
    strategy:        str   = "unknown"
    symbol:          str   = "UNKNOWN"

    # Account state at time of sizing
    balance:         float = 0.0
    equity:          float = 0.0
    free_margin:     float = 0.0

    # Risk inputs
    risk_pct:        float = 1.0
    risk_amount:     float = 0.0

    # Price levels
    entry_price:     float = 0.0
    stop_loss:       float = 0.0
    tp_price:        float = 0.0

    # Distances
    sl_distance:     float = 0.0
    sl_points:       int   = 0
    tp_distance:     float = 0.0
    tp_points:       int   = 0

    # Broker spec used
    tick_size:       float = 0.01
    tick_value:      float = 0.01
    contract_size:   float = 100.0

    # Lot calculations
    raw_lot:         float = 0.0
    final_lot:       float = 0.0
    executed_lot:    float = 0.0   # Updated after fill

    # Financials
    expected_loss:   float = 0.0
    expected_reward: float = 0.0
    risk_reward_ratio: float = 0.0

    # Broker limits
    vol_min:         float = 0.01
    vol_max:         float = 50.0
    vol_step:        float = 0.01

    # Margin (estimate — requires live equity)
    margin_used:     float = 0.0

    # Trade reference
    trade_id:        str   = ""

    @property
    def is_valid(self) -> bool:
        return self.final_lot > 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Universal Position Sizer
# ══════════════════════════════════════════════════════════════════════════════

class PositionSizer:
    """
    Stateless universal position sizer.

    All strategies and all symbols use this single class.
    Call PositionSizer.size() — no instantiation required.
    """

    @staticmethod
    def size(
        balance:    float,
        entry:      float,
        stop_loss:  float,
        spec:       BrokerSpec,
        risk_pct:   float       = 1.0,
        tp_price:   Optional[float] = None,
        equity:     float       = 0.0,
        free_margin: float      = 0.0,
        strategy:   str         = "unknown",
        symbol:     str         = "UNKNOWN",
        trade_id:   str         = "",
        write_csv:  bool        = True,
    ) -> SizingResult:
        """
        Compute lot size for one trade and return a full SizingResult.

        Parameters
        ----------
        balance      : Current account balance (USD).
        entry        : Expected entry price.
        stop_loss    : Stop-loss price.
        spec         : BrokerSpec (from MT5 or fallback).
        risk_pct     : Risk percentage (default 1.0 = 1%).
        tp_price     : Take-profit price (optional; 2R estimated if None).
        equity       : Current account equity (for logging).
        free_margin  : Free margin available (for logging).
        strategy     : Strategy name for attribution in CSV reports.
        symbol       : Symbol name.
        trade_id     : Optional trade UUID for cross-referencing.
        write_csv    : If True, append result to position_size_history.csv.
        """
        ts = datetime.now(timezone.utc).isoformat()
        result = SizingResult(
            timestamp=ts, strategy=strategy, symbol=symbol,
            balance=balance, equity=equity or balance,
            free_margin=free_margin or balance,
            risk_pct=risk_pct,
            entry_price=entry, stop_loss=stop_loss,
            tp_price=tp_price or 0.0,
            tick_size=spec.tick_size, tick_value=spec.tick_value,
            contract_size=spec.contract_size,
            vol_min=spec.vol_min, vol_max=spec.vol_max, vol_step=spec.vol_step,
            trade_id=trade_id,
        )

        # ── Pre-validation ────────────────────────────────────────────────────
        if balance <= 0:
            logger.warning(f"[SIZER][{symbol}] Balance <= 0 — cannot size")
            _write_csv(result, write_csv)
            return result

        sl_distance = abs(entry - stop_loss)
        if sl_distance < 1e-8:
            logger.warning(f"[SIZER][{symbol}] SL distance ~0 — skipping")
            _write_csv(result, write_csv)
            return result

        if spec.tick_size <= 0 or spec.tick_value <= 0 or spec.vol_step <= 0:
            logger.warning(f"[SIZER][{symbol}] Invalid broker spec — skipping")
            _write_csv(result, write_csv)
            return result

        # ── Core formula ──────────────────────────────────────────────────────
        risk_amount = balance * (risk_pct / 100.0)
        sl_points   = max(1, int(round(sl_distance / spec.tick_size)))
        denominator = sl_points * spec.tick_value

        raw_lot = risk_amount / denominator if denominator > 0 else 0.0

        # ── Broker compliance: floor to step, clamp to [min, max] ─────────────
        step_count  = math.floor(raw_lot / spec.vol_step) if spec.vol_step > 0 else 0
        stepped_lot = step_count * spec.vol_step
        final_lot   = max(spec.vol_min, min(spec.vol_max, stepped_lot))

        step_decimals = (
            max(0, -int(math.floor(math.log10(spec.vol_step))))
            if spec.vol_step < 1 else 0
        )
        final_lot = round(final_lot, step_decimals)

        # ── TP metrics ────────────────────────────────────────────────────────
        tp_distance = 0.0
        tp_points   = 0
        if tp_price and tp_price != 0.0:
            tp_distance = abs(entry - tp_price)
            tp_points   = max(1, int(round(tp_distance / spec.tick_size)))
        else:
            tp_points   = sl_points * 2   # assume 2R if not provided
            tp_distance = tp_points * spec.tick_size

        expected_loss   = round(final_lot * sl_points * spec.tick_value, 4)
        expected_reward = round(final_lot * tp_points * spec.tick_value, 4)
        rr = round(expected_reward / expected_loss, 3) if expected_loss > 0 else 0.0

        # ── Margin estimate (naive: lot × contract × entry × leverage-free) ───
        margin_est = round(final_lot * spec.contract_size * entry * 0.01, 2)

        # ── Populate result ───────────────────────────────────────────────────
        result.risk_amount     = round(risk_amount, 4)
        result.sl_distance     = round(sl_distance, 6)
        result.sl_points       = sl_points
        result.tp_distance     = round(tp_distance, 6)
        result.tp_points       = tp_points
        result.raw_lot         = round(raw_lot, 6)
        result.final_lot       = final_lot
        result.executed_lot    = final_lot   # caller may update after fill
        result.expected_loss   = expected_loss
        result.expected_reward = expected_reward
        result.risk_reward_ratio = rr
        result.margin_used     = margin_est

        # ── Structured log (14 fields) ────────────────────────────────────────
        logger.info(
            f"[SIZING][{strategy}][{symbol}] "
            f"Balance=${balance:,.2f} | Risk={risk_pct:.1f}% | "
            f"RiskAmt=${risk_amount:.2f} | "
            f"SL={sl_points}pts | TP={tp_points}pts | "
            f"RawLot={raw_lot:.5f} | FinalLot={final_lot:.{step_decimals}f} | "
            f"MinLot={spec.vol_min} | MaxLot={spec.vol_max} | Step={spec.vol_step} | "
            f"ExpLoss=${expected_loss:.2f} | ExpReward=${expected_reward:.2f} | "
            f"RR={rr:.2f} | TradeID={trade_id or 'N/A'}"
        )

        _write_csv(result, write_csv)
        return result

    @staticmethod
    def normalize_lot(raw_lot: float, spec: BrokerSpec) -> float:
        """
        Apply broker vol constraints to any raw lot value.
        Utility function for callers that compute their own raw lot.
        """
        if spec.vol_step <= 0:
            return spec.vol_min
        step_count  = math.floor(raw_lot / spec.vol_step)
        stepped_lot = step_count * spec.vol_step
        final_lot   = max(spec.vol_min, min(spec.vol_max, stepped_lot))
        step_dec = max(0, -int(math.floor(math.log10(spec.vol_step)))) if spec.vol_step < 1 else 0
        return round(final_lot, step_dec)


# ══════════════════════════════════════════════════════════════════════════════
# CSV auto-writer
# ══════════════════════════════════════════════════════════════════════════════

def _write_csv(result: SizingResult, enabled: bool) -> None:
    """Append one SizingResult row to position_size_history.csv."""
    if not enabled:
        return
    try:
        _REPORT_DIR.mkdir(exist_ok=True)
        exists = _HISTORY_CSV.exists()
        with open(_HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            row = asdict(result)
            # Ensure numeric precision
            for k in row:
                if isinstance(row[k], float):
                    row[k] = round(row[k], 6)
            writer.writerow(row)
    except Exception as exc:
        logger.debug(f"[SIZER] CSV write failed: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# Backward-compatibility shim
# ══════════════════════════════════════════════════════════════════════════════

def calculate_lot_size_universal(
    balance:       float,
    entry_price:   float,
    stop_loss:     float,
    risk_pct:      float,
    symbol:        str   = "UNKNOWN",
    contract_size: float = 100.0,
    vol_min:       float = 0.01,
    vol_max:       float = 50.0,
    vol_step:      float = 0.01,
    tick_size:     float = 0.01,
    tick_value:    float = 0.01,
    tp_price:      Optional[float] = None,
    strategy:      str   = "unknown",
    write_csv:     bool  = True,
) -> tuple:
    """
    Drop-in replacement for the old calculate_lot_size() signature.
    Returns (final_lot, expected_loss) — same as the original function.
    """
    spec = BrokerSpec(
        symbol=symbol, vol_min=vol_min, vol_max=vol_max, vol_step=vol_step,
        tick_size=tick_size, tick_value=tick_value, contract_size=contract_size,
    )
    r = PositionSizer.size(
        balance=balance, entry=entry_price, stop_loss=stop_loss,
        spec=spec, risk_pct=risk_pct, tp_price=tp_price,
        strategy=strategy, symbol=symbol, write_csv=write_csv,
    )
    return r.final_lot, r.expected_loss
