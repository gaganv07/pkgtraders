"""
app/health_api.py — MT5 Infrastructure Health Dashboard API Endpoints

Provides REST / JSON API endpoints for:
- /api/v1/health       -> System overall health status & latency
- /api/v1/broker       -> Broker profile, server, account mode, capabilities
- /api/v1/sync         -> History & tick synchronization status and % progress
- /api/v1/cache        -> Cache integrity status, corrupted files, repair logs
- /api/v1/terminal     -> Terminal process, heartbeat timestamp, reconnect count
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class InfrastructureHealthAPI:
    """
    Exposes structured health & telemetry data for the MT5 infrastructure layer.
    """

    def __init__(
        self,
        broker_adapter: Optional[Any] = None,
        history_sync: Optional[Any] = None,
        cache_repair: Optional[Any] = None,
        terminal_supervisor: Optional[Any] = None,
    ):
        self.broker_adapter = broker_adapter
        self.history_sync = history_sync
        self.cache_repair = cache_repair
        self.terminal_supervisor = terminal_supervisor

    def get_overall_health(self) -> Dict[str, Any]:
        """GET /api/v1/health"""
        supervisor_state = self.terminal_supervisor.state if self.terminal_supervisor else None
        sync_pct = self.history_sync.overall_sync_percentage if self.history_sync else 100.0

        is_healthy = (
            (supervisor_state.is_connected_to_broker if supervisor_state else True)
            and (sync_pct >= 95.0)
        )

        return {
            "status": "HEALTHY" if is_healthy else "UNHEALTHY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latency_ms": supervisor_state.ping_ms if supervisor_state else 0.0,
            "sync_percentage": sync_pct,
            "reconnect_count": supervisor_state.reconnect_count if supervisor_state else 0,
        }

    def get_broker_info(self) -> Dict[str, Any]:
        """GET /api/v1/broker"""
        if not self.broker_adapter:
            return {"status": "UNAVAILABLE", "message": "BrokerAdapter not initialized"}

        profile = self.broker_adapter.profile
        return {
            "status": "OK",
            "profile": profile.to_dict(),
        }

    def get_sync_status(self) -> Dict[str, Any]:
        """GET /api/v1/sync"""
        if not self.history_sync:
            return {"status": "UNAVAILABLE", "overall_sync_pct": 100.0}

        results = self.history_sync.get_sync_results()
        symbols_summary = {}

        for sym, res in results.items():
            symbols_summary[sym] = {
                "broker_symbol": res.broker_symbol,
                "sync_pct": res.sync_percentage,
                "tick_synced": res.tick_synced,
                "timeframes": {
                    tf: {"bars": tr.bars_downloaded, "synced": tr.synced}
                    for tf, tr in res.timeframes.items()
                },
            }

        return {
            "status": "OK",
            "overall_sync_pct": self.history_sync.overall_sync_percentage,
            "is_synced": self.history_sync.is_synced,
            "symbols": symbols_summary,
        }

    def get_cache_status(self) -> Dict[str, Any]:
        """GET /api/v1/cache"""
        if not self.cache_repair:
            return {"status": "OK", "is_healthy": True, "corrupted_files_count": 0}

        is_healthy, corrupted_files = self.cache_repair.audit_cache_integrity()
        return {
            "status": "OK",
            "is_healthy": is_healthy,
            "corrupted_files_count": len(corrupted_files),
            "corrupted_files": [str(p) for p in corrupted_files],
        }

    def get_terminal_status(self) -> Dict[str, Any]:
        """GET /api/v1/terminal"""
        if not self.terminal_supervisor:
            return {"status": "UNAVAILABLE"}

        state = self.terminal_supervisor.state
        return {
            "status": "OK",
            "is_process_running": state.is_process_running,
            "is_api_initialized": state.is_api_initialized,
            "is_connected_to_broker": state.is_connected_to_broker,
            "ping_ms": state.ping_ms,
            "last_heartbeat": state.last_heartbeat.isoformat() if state.last_heartbeat else None,
            "reconnect_count": state.reconnect_count,
            "last_error": state.last_error,
        }
