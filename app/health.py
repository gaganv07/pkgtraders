"""
app/health.py — System Health Monitor

Tracks: MT5 connection, data feed freshness, DOM status,
memory/CPU, position reconciliation, circuit-breaker state.
Runs a 30-second background loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

logger = logging.getLogger(__name__)


@dataclass
class HealthReport:
    ts:               datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mt5_connected:    bool = False
    dom_active:       bool = False
    feed_fresh:       bool = False
    feed_age_ms:      float = 0.0
    db_ok:            bool = False
    memory_mb:        float = 0.0
    cpu_pct:          float = 0.0
    uptime_s:         float = 0.0
    positions_mt5:    int = 0
    positions_local:  int = 0
    reconciled:       bool = True
    circuit_broken:   bool = False
    dd_any_hit:       bool = False

    @property
    def healthy(self) -> bool:
        return (
            self.mt5_connected
            and self.feed_fresh
            and self.db_ok
            and self.reconciled
        )

    def to_dict(self) -> Dict:
        return {
            "healthy":        self.healthy,
            "mt5_connected":  self.mt5_connected,
            "dom_active":     self.dom_active,
            "feed_fresh":     self.feed_fresh,
            "feed_age_ms":    round(self.feed_age_ms, 0),
            "memory_mb":      round(self.memory_mb, 1),
            "cpu_pct":        round(self.cpu_pct, 1),
            "uptime_s":       round(self.uptime_s, 0),
            "positions_mt5":  self.positions_mt5,
            "positions_local": self.positions_local,
            "reconciled":     self.reconciled,
            "circuit_broken": self.circuit_broken,
            "dd_any_hit":     self.dd_any_hit,
            "ts":             self.ts.isoformat(),
        }


class HealthMonitor:
    def __init__(self, client, market, risk, db):
        self._client  = client
        self._market  = market
        self._risk    = risk
        self._db      = db
        self._t0      = time.time()
        self._latest: Optional[HealthReport] = None
        self._run     = False

    async def run_loop(self, interval: int = 30) -> None:
        self._run = True
        logger.info("Health monitor started")
        # Run an initial check immediately on startup
        try:
            r = await self._check()
            self._latest = r
        except Exception as e:
            logger.error(f"Initial health check error: {e}")

        while self._run:
            try:
                r = await self._check()
                self._latest = r
                self._db.log_event(
                    "HEALTH",
                    "healthy" if r.healthy else "degraded",
                    severity="INFO" if r.healthy else "WARNING",
                    data=r.to_dict(),
                )
                if not r.mt5_connected:
                    logger.warning("Health: MT5 offline — triggering reconnect")
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self._client.reconnect)

                if not r.reconciled:
                    await self._reconcile()
                self.export_health_json()
            except Exception as e:
                logger.error(f"Health check error: {e}")
            await asyncio.sleep(interval)

    def export_health_json(self, file_path: str = "reports/health_report.json") -> None:
        if self._latest:
            try:
                import json
                p = Path(file_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(self._latest.to_dict(), f, indent=2)
            except Exception as e:
                logger.error(f"Failed to export health JSON: {e}")

    async def _check(self) -> HealthReport:
        r = HealthReport(uptime_s=time.time() - self._t0)

        r.mt5_connected = self._client.connected
        r.dom_active    = self._client.dom_active
        r.feed_fresh    = self._market.is_fresh
        r.feed_age_ms   = self._market.feed_age_ms

        if r.mt5_connected:
            loop = asyncio.get_event_loop()
            positions = await loop.run_in_executor(
                None, self._client.get_positions
            )
            r.positions_mt5 = len(positions)

        r.positions_local = self._risk.open_count
        r.reconciled      = r.positions_mt5 == r.positions_local

        if _PSUTIL:
            proc = psutil.Process(os.getpid())
            r.memory_mb = proc.memory_info().rss / 1024 / 1024
            r.cpu_pct   = proc.cpu_percent(interval=0.1)

        try:
            self._db.get_events(limit=1)
            r.db_ok = True
        except Exception:
            r.db_ok = False

        r.circuit_broken = self._risk.circuit_broken
        r.dd_any_hit     = self._risk.drawdown.any_hit
        return r

    async def _reconcile(self) -> None:
        logger.info("Reconciling positions…")
        loop = asyncio.get_event_loop()
        mt5_pos = await loop.run_in_executor(None, self._client.get_positions)
        self._db.log_event(
            "RECONCILE",
            f"MT5={len(mt5_pos)} local={self._risk.open_count}",
            data={"tickets": [p.ticket for p in mt5_pos]},
        )

    def stop(self) -> None:
        self._run = False

    @property
    def latest(self) -> Optional[HealthReport]:
        return self._latest
