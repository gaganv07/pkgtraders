"""
app/trade_journal.py — Live Trade Journal Exporter

Automatically logs every completed trade to reports/live_trade_journal.csv
with detailed operational, technical, and execution metrics.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_JOURNAL_PATH = Path("reports") / "live_trade_journal.csv"


@dataclass
class TradeJournalEntry:
    timestamp: str             # Entry ISO timestamp
    exit_timestamp: str        # Exit ISO timestamp
    symbol: str
    direction: str             # LONG | SHORT
    entry_price: float
    exit_price: float
    sl: float
    tp: float
    lot_size: float
    balance: float
    equity: float
    risk_pct: float
    spread_pts: float
    atr: float
    ema50: float
    rsi: float
    ai_score: float
    score_breakdown: str
    entry_reason: str
    exit_reason: str
    holding_time_s: float
    pnl: float
    pnl_pct: float
    r_multiple: float
    broker_retcode: int
    execution_latency_ms: float


class TradeJournal:
    """
    Manages structured trade logging to CSV and database.
    """

    def __init__(self, file_path: Path = DEFAULT_JOURNAL_PATH):
        self.file_path = Path(file_path)
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create directory and header if CSV file doesn't exist."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            fieldnames = list(TradeJournalEntry.__dataclass_fields__.keys())
            try:
                with open(self.file_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                logger.info(f"Initialized Trade Journal CSV at {self.file_path}")
            except Exception as e:
                logger.error(f"Failed to initialize trade journal CSV: {e}")

    def log_trade(self, entry: TradeJournalEntry) -> bool:
        """Append a TradeJournalEntry to the CSV file."""
        try:
            fieldnames = list(TradeJournalEntry.__dataclass_fields__.keys())
            row = asdict(entry)
            with open(self.file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(row)
            logger.info(
                f"[JOURNAL] Logged trade #{entry.symbol} {entry.direction} "
                f"PnL=${entry.pnl:.2f} ({entry.r_multiple:.2f}R) to {self.file_path}"
            )
            self.export_equity_curve_point(entry.exit_timestamp, entry.balance, entry.equity)
            return True
        except Exception as e:
            logger.error(f"Failed to write trade journal entry: {e}")
            return False

    def export_equity_curve_point(self, timestamp: str, balance: float, equity: float, file_path: Path = Path("reports") / "equity_curve.csv") -> None:
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not file_path.exists() or file_path.stat().st_size == 0
            with open(file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(["timestamp", "balance", "equity"])
                writer.writerow([timestamp, round(balance, 2), round(equity, 2)])
        except Exception as e:
            logger.error(f"Failed to write equity curve point: {e}")
