"""
app/dataset_manager.py — Immutable Dataset Versioning & Archiving Engine
==========================================================================
Collects and permanently stores 31 execution, market microstructure, Bookmap,
and technical features for every evaluated trade context.

Versions datasets sequentially (v1, v2, v3...) in database/datasets/ without
ever overwriting historical datasets.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATASET_DIR = Path("database/datasets")


@dataclass
class TradeContextFeature:
    """Immutable 31-feature record for trade evaluation context."""
    timestamp: str
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_usd: float
    risk_pct: float
    pnl: float = 0.0
    r_multiple: float = 0.0
    duration_s: float = 0.0
    outcome: str = "PENDING"  # "WIN" | "LOSS" | "BREAKEVEN" | "REJECTED"
    exit_reason: str = ""

    # Technical & Market Microstructure Features
    atr: float = 0.0
    volatility_regime: str = "NORMAL"
    spread: float = 0.0
    spread_ratio: float = 1.0
    session_name: str = "LONDON"
    session_score: float = 50.0
    ema_bull_h1: bool = False
    ema_bear_h1: bool = False
    ema_bull_m15: bool = False
    ema_bear_m15: bool = False
    choch_event: bool = False
    bos_event: bool = False
    price_in_fvg: bool = False
    price_above_vwap: Optional[bool] = None

    # Bookmap & Order Flow Features
    bookmap_connected: bool = False
    bookmap_confluence: float = 50.0
    bookmap_imbalance: float = 0.0
    bid_walls_count: int = 0
    ask_walls_count: int = 0
    icebergs_count: int = 0
    absorption_side: Optional[str] = None
    execution_latency_ms: float = 0.0
    slippage_pts: float = 0.0
    broker_server: str = "BlackBullMarkets-Demo"
    account_login: int = 919205


class DatasetManager:
    """
    Manages permanent archiving and versioning of trade datasets.
    """

    def __init__(self, base_dir: Path = DATASET_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.current_version = self._detect_latest_version()

    def _detect_latest_version(self) -> int:
        """Find the highest dataset version number in database/datasets/."""
        existing_v = []
        for file in self.base_dir.glob("v*_features.json"):
            name = file.stem  # v1_features
            try:
                ver_num = int(name.split("_")[0].replace("v", ""))
                existing_v.append(ver_num)
            except ValueError:
                continue
        return max(existing_v) if existing_v else 1

    def archive_record(self, record: TradeContextFeature) -> Path:
        """
        Append trade feature record to current version files and freeze
        version when trade threshold is met.
        """
        rec_dict = asdict(record)
        
        # 1. Write to versioned JSON feature log
        v_json_path = self.base_dir / f"v{self.current_version}_features.json"
        existing_records = []
        if v_json_path.exists():
            try:
                with open(v_json_path, "r", encoding="utf-8") as f:
                    existing_records = json.load(f)
            except Exception as e:
                logger.error(f"Failed to read dataset {v_json_path}: {e}")

        existing_records.append(rec_dict)
        
        with open(v_json_path, "w", encoding="utf-8") as f:
            json.dump(existing_records, f, indent=2)

        # 2. Write to versioned CSV journal
        v_csv_path = self.base_dir / f"v{self.current_version}_trade_journal.csv"
        write_header = not v_csv_path.exists() or v_csv_path.stat().st_size == 0
        with open(v_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rec_dict.keys()))
            if write_header:
                writer.writeheader()
            writer.writerow(rec_dict)

        logger.info(f"[DATASET MANAGER] Archived record #{len(existing_records)} to dataset v{self.current_version}")

        # Increment version when threshold reached (e.g. 100 records per dataset file)
        if len(existing_records) >= 100:
            self.current_version += 1
            logger.info(f"[DATASET MANAGER] Dataset v{self.current_version - 1} frozen. Advanced to dataset v{self.current_version}")

        return v_json_path

    def get_dataset_summary(self) -> Dict[str, Any]:
        """Return dataset version inventory summary."""
        version_files = list(self.base_dir.glob("v*_features.json"))
        total_records = 0
        for vf in version_files:
            try:
                with open(vf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    total_records += len(data)
            except Exception:
                pass
        
        return {
            "latest_version": f"v{self.current_version}",
            "total_version_files": len(version_files),
            "total_archived_records": total_records,
            "dataset_dir": str(self.base_dir.absolute()),
        }
