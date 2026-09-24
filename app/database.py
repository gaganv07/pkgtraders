"""
app/database.py — SQLite Database Layer

Tables:
  trades          Full trade lifecycle
  execution_log   Signal/submission/fill timestamps + analytics
  quality_log     Per-evaluation quality scores
  market_snapshots Periodic market state snapshots
  system_events   Startup/shutdown/errors/reconnects
  daily_stats     Rolled-up daily performance
  latency_log     Execution latency measurements
  ml_training     Trade contexts for ML retraining
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=30000;
PRAGMA cache_size=-32000;

CREATE TABLE IF NOT EXISTS trades (
    id                TEXT PRIMARY KEY,
    ticket            INTEGER,
    symbol            TEXT NOT NULL,
    direction         TEXT NOT NULL,
    status            TEXT DEFAULT 'OPEN',

    entry_price       REAL,
    entry_time        TEXT,
    close_price       REAL,
    close_time        TEXT,
    close_reason      TEXT,

    volume            REAL,
    initial_vol       REAL,
    risk_usd          REAL,
    quality_score     REAL,
    atr_entry         REAL,

    sl                REAL,
    tp1               REAL,
    tp2               REAL,
    tp3               REAL,

    realized_pnl      REAL DEFAULT 0,
    spread_entry      REAL,
    latency_ms        REAL,
    slippage          REAL,

    tp1_done          INTEGER DEFAULT 0,
    tp2_done          INTEGER DEFAULT 0,
    breakeven_done    INTEGER DEFAULT 0,
    trailing_active   INTEGER DEFAULT 0,

    account_id        TEXT DEFAULT 'account_default',
    broker            TEXT DEFAULT '',
    server            TEXT DEFAULT '',
    strategy          TEXT DEFAULT 'PKGTRADERS',
    signal_id         TEXT DEFAULT '',
    order_ticket      INTEGER DEFAULT 0,
    position_ticket   INTEGER DEFAULT 0,
    requested_volume  REAL DEFAULT 0,
    executed_volume   REAL DEFAULT 0,
    requested_price   REAL DEFAULT 0,
    execution_price   REAL DEFAULT 0,
    profit            REAL DEFAULT 0,
    commission        REAL DEFAULT 0,
    swap              REAL DEFAULT 0,
    magic             INTEGER DEFAULT 20250701,
    error_code        INTEGER DEFAULT 0,
    rejection_reason  TEXT DEFAULT '',
    strategy_version  TEXT DEFAULT '2.0.0',

    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trades_status  ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_entry   ON trades(entry_time);
CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_id);
CREATE INDEX IF NOT EXISTS idx_trades_magic   ON trades(magic);
CREATE INDEX IF NOT EXISTS idx_trades_signal  ON trades(signal_id);

CREATE TABLE IF NOT EXISTS execution_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT,
    signal_ts       TEXT,
    submit_ts       TEXT,
    fill_ts         TEXT,
    exit_ts         TEXT,
    fill_latency_ms REAL,
    exit_latency_ms REAL,
    spread          REAL,
    slippage        REAL,
    of_score        REAL,
    liq_score       REAL,
    quality_score   REAL,
    pnl             REAL
);

CREATE TABLE IF NOT EXISTS quality_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    direction       TEXT,
    total_score     REAL,
    of_score        REAL,
    liq_score       REAL,
    ms_score        REAL,
    vol_score       REAL,
    session_score   REAL,
    news_score      REAL,
    ml_adjustment   REAL DEFAULT 0,
    tradeable       INTEGER DEFAULT 0,
    veto_reasons    TEXT
);
CREATE INDEX IF NOT EXISTS idx_quality_ts ON quality_log(ts);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    bid             REAL,
    ask             REAL,
    spread          REAL,
    atr_m5          REAL,
    vol_regime      TEXT,
    vol_pct         REAL,
    of_score        REAL,
    liq_score       REAL,
    ms_trend        TEXT,
    session_active  INTEGER,
    dom_mode        INTEGER
);

CREATE TABLE IF NOT EXISTS system_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    severity    TEXT DEFAULT 'INFO',
    message     TEXT,
    data        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON system_events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON system_events(event_type);

CREATE TABLE IF NOT EXISTS daily_stats (
    date            TEXT PRIMARY KEY,
    total_trades    INTEGER DEFAULT 0,
    winning         INTEGER DEFAULT 0,
    losing          INTEGER DEFAULT 0,
    gross_profit    REAL DEFAULT 0,
    gross_loss      REAL DEFAULT 0,
    net_pnl         REAL DEFAULT 0,
    win_rate        REAL DEFAULT 0,
    profit_factor   REAL DEFAULT 0,
    avg_quality     REAL DEFAULT 0,
    avg_latency_ms  REAL DEFAULT 0,
    avg_slippage    REAL DEFAULT 0,
    max_drawdown    REAL DEFAULT 0,
    sharpe          REAL DEFAULT 0,
    sortino         REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS latency_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    operation   TEXT,
    latency_ms  REAL
);
CREATE INDEX IF NOT EXISTS idx_lat_ts ON latency_log(ts);

CREATE TABLE IF NOT EXISTS ml_training (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        TEXT,
    direction       TEXT,
    of_score        REAL,
    liq_score       REAL,
    ms_score        REAL,
    vol_score       REAL,
    session_score   REAL,
    news_score      REAL,
    spread_ratio    REAL,
    atr_pct         REAL,
    hour_of_day     INTEGER,
    dom_mode        INTEGER,
    vol_expansion   INTEGER,
    bos_event       INTEGER,
    choch_event     INTEGER,
    liq_grab_event  INTEGER,
    realized_pnl    REAL,
    win             INTEGER,
    entry_time      TEXT
);
"""


class Database:
    """Thread-safe SQLite with WAL mode and async wrappers."""

    def __init__(self, db_path: str = "database/trading.db"):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()
        logger.info(f"Database ready: {self._path}")

    # ── Connection management ─────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._path), timeout=30)
            conn.row_factory = sqlite3.Row
            conn.executescript(
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA foreign_keys=ON;"
                "PRAGMA busy_timeout=30000;"
                "PRAGMA cache_size=-32000;"
            )
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def _tx(self):
        conn = self._conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        self._conn().executescript(SCHEMA)
        self._conn().commit()
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Non-destructive migration: dynamically adds any missing columns to existing tables."""
        conn = self._conn()
        try:
            cursor = conn.execute("PRAGMA table_info(trades)")
            existing_cols = {row["name"] for row in cursor.fetchall()}

            columns_to_add = [
                ("account_id", "TEXT DEFAULT 'account_default'"),
                ("broker", "TEXT DEFAULT ''"),
                ("server", "TEXT DEFAULT ''"),
                ("strategy", "TEXT DEFAULT 'PKGTRADERS'"),
                ("signal_id", "TEXT DEFAULT ''"),
                ("order_ticket", "INTEGER DEFAULT 0"),
                ("position_ticket", "INTEGER DEFAULT 0"),
                ("requested_volume", "REAL DEFAULT 0"),
                ("executed_volume", "REAL DEFAULT 0"),
                ("requested_price", "REAL DEFAULT 0"),
                ("execution_price", "REAL DEFAULT 0"),
                ("profit", "REAL DEFAULT 0"),
                ("commission", "REAL DEFAULT 0"),
                ("swap", "REAL DEFAULT 0"),
                ("magic", "INTEGER DEFAULT 20250701"),
                ("error_code", "INTEGER DEFAULT 0"),
                ("rejection_reason", "TEXT DEFAULT ''"),
                ("strategy_version", "TEXT DEFAULT '2.0.0'"),
            ]

            for col_name, col_def in columns_to_add:
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_def}")
            conn.commit()
        except Exception as e:
            logger.warning(f"Database schema migration check notice: {e}")

    def execute_write(self, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Thread-safe synchronous execute for write operations."""
        with self._tx() as conn:
            conn.execute(sql, params or {})

    # ── Trades ────────────────────────────────────────────────────

    async def insert_trade(self, trade) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._insert_trade_sync, trade)

    def _insert_trade_sync(self, trade) -> None:
        sql = """
        INSERT INTO trades (
            id, ticket, symbol, direction, status,
            entry_price, entry_time, volume, initial_vol,
            risk_usd, quality_score, atr_entry,
            sl, tp1, tp2, tp3,
            spread_entry, latency_ms, slippage
        ) VALUES (
            :id, :ticket, :symbol, :direction, 'OPEN',
            :entry, :entry_time, :vol, :init_vol,
            :risk_usd, :quality, :atr,
            :sl, :tp1, :tp2, :tp3,
            :spread, :latency, :slippage
        )
        """
        with self._tx() as conn:
            conn.execute(sql, {
                "id":         trade.trade_id,
                "ticket":     trade.ticket,
                "symbol":     trade.symbol,
                "direction":  trade.direction,
                "entry":      trade.entry_price,
                "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
                "vol":        trade.volume,
                "init_vol":   trade.initial_vol,
                "risk_usd":   trade.risk_usd,
                "quality":    trade.quality_score,
                "atr":        trade.atr_entry,
                "sl":         trade.sl,
                "tp1":        trade.tp1,
                "tp2":        trade.tp2,
                "tp3":        trade.tp3,
                "spread":     trade.spread_entry,
                "latency":    trade.latency_ms,
                "slippage":   trade.slippage,
            })

    async def update_trade(self, trade) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._update_trade_sync, trade)

    def _update_trade_sync(self, trade) -> None:
        with self._tx() as conn:
            conn.execute(
                """UPDATE trades SET
                    volume=:vol, sl=:sl,
                    tp1_done=:tp1, tp2_done=:tp2, breakeven_done=:be,
                    trailing_active=:tr, realized_pnl=:pnl,
                    updated_at=datetime('now')
                   WHERE id=:id""",
                {
                    "id":  trade.trade_id,
                    "vol": trade.volume,
                    "sl":  trade.sl,
                    "tp1": int(trade.tp1_done),
                    "tp2": int(trade.tp2_done),
                    "be":  int(trade.breakeven_done),
                    "tr":  int(trade.trailing_active),
                    "pnl": trade.realized_pnl,
                },
            )

    async def close_trade(self, trade) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._close_trade_sync, trade)

    def _close_trade_sync(self, trade) -> None:
        with self._tx() as conn:
            conn.execute(
                """UPDATE trades SET
                    status='CLOSED', close_price=:cp, close_time=:ct,
                    close_reason=:cr, realized_pnl=:pnl,
                    tp1_done=:tp1, tp2_done=:tp2,
                    breakeven_done=:be, trailing_active=:tr,
                    updated_at=datetime('now')
                   WHERE id=:id""",
                {
                    "id":  trade.trade_id,
                    "cp":  trade.close_price,
                    "ct":  trade.close_time.isoformat() if trade.close_time else None,
                    "cr":  trade.close_reason,
                    "pnl": trade.realized_pnl,
                    "tp1": int(trade.tp1_done),
                    "tp2": int(trade.tp2_done),
                    "be":  int(trade.breakeven_done),
                    "tr":  int(trade.trailing_active),
                },
            )
        # Also log to execution_log
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO execution_log
                   (trade_id, fill_ts, exit_ts, pnl, spread, slippage,
                    quality_score)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    trade.trade_id,
                    trade.entry_time.isoformat() if trade.entry_time else None,
                    trade.close_time.isoformat() if trade.close_time else None,
                    trade.realized_pnl,
                    trade.spread_entry,
                    trade.slippage,
                    trade.quality_score,
                ),
            )

    async def insert_account_trade(self, report: Any, signal: Any) -> None:
        """Persist a multi-account execution report with full attribution."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._insert_account_trade_sync, report, signal)

    def _insert_account_trade_sync(self, report: Any, signal: Any) -> None:
        sql = """
        INSERT OR REPLACE INTO trades (
            id, ticket, symbol, direction, status,
            entry_price, entry_time, volume, initial_vol,
            risk_usd, quality_score, atr_entry,
            sl, tp1, tp2, tp3,
            account_id, magic, signal_id, order_ticket, position_ticket,
            requested_volume, executed_volume, requested_price, execution_price,
            strategy, strategy_version, rejection_reason, error_code, latency_ms
        ) VALUES (
            :id, :ticket, :symbol, :direction, :status,
            :entry, :entry_time, :vol, :init_vol,
            :risk_usd, :quality, :atr,
            :sl, :tp1, :tp2, :tp3,
            :account_id, :magic, :signal_id, :order_ticket, :position_ticket,
            :requested_volume, :executed_volume, :requested_price, :execution_price,
            :strategy, :strategy_version, :rejection_reason, :error_code, :latency_ms
        )
        """
        trade_id = f"{report.account_id}_{report.ticket or signal.signal_id}"
        ts_val = report.timestamp.isoformat() if hasattr(report.timestamp, "isoformat") else str(report.timestamp)
        with self._tx() as conn:
            conn.execute(sql, {
                "id":               trade_id,
                "ticket":           report.ticket or 0,
                "symbol":           report.symbol,
                "direction":        report.direction,
                "status":           "OPEN" if report.is_success else "REJECTED",
                "entry":            report.executed_price,
                "entry_time":       ts_val,
                "vol":              report.executed_volume,
                "init_vol":         report.requested_volume,
                "risk_usd":         0.0,
                "quality":          signal.quality_score,
                "atr":              signal.atr,
                "sl":               report.stop_loss,
                "tp1":              report.take_profit,
                "tp2":              getattr(signal, "take_profit_2", 0.0),
                "tp3":              getattr(signal, "take_profit_3", 0.0),
                "account_id":       report.account_id,
                "magic":            report.magic_number,
                "signal_id":        report.signal_id,
                "order_ticket":     report.ticket or 0,
                "position_ticket":  report.position_ticket or 0,
                "requested_volume": report.requested_volume,
                "executed_volume":  report.executed_volume,
                "requested_price":  report.requested_price,
                "execution_price":  report.executed_price,
                "strategy":         signal.strategy_name,
                "strategy_version": signal.strategy_version,
                "rejection_reason": report.rejection_reason,
                "error_code":       report.error_code,
                "latency_ms":       report.latency_ms,
            })

    def get_trades(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        account_id: Optional[str] = None,
    ) -> List[Dict]:
        conditions = []
        params: List[Any] = []
        if status:
            conditions.append("status=?")
            params.append(status)
        if account_id:
            conditions.append("account_id=?")
            params.append(account_id)

        q = "SELECT * FROM trades"
        if conditions:
            q += " WHERE " + " AND ".join(conditions)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn().execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_closed_trades(self, limit: int = 200, account_id: Optional[str] = None) -> List[Dict]:
        return self.get_trades("CLOSED", limit, account_id=account_id)

    # ── Quality log ───────────────────────────────────────────────

    def log_quality(self, direction: str, bd, ml_adj: float = 0.0) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO quality_log
                   (ts, direction, total_score, of_score, liq_score,
                    ms_score, vol_score, session_score, news_score,
                    ml_adjustment, tradeable, veto_reasons)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    direction,
                    bd.total, bd.of_score, bd.liq_score,
                    bd.ms_score, bd.vol_score, bd.session_score,
                    bd.news_score, ml_adj,
                    int(bd.tradeable),
                    json.dumps(bd.veto_reasons),
                ),
            )

    def get_recent_quality_scores(self, limit: int = 200) -> List[float]:
        q = "SELECT total_score FROM quality_log ORDER BY ts DESC LIMIT ?"
        try:
            rows = self._conn().execute(q, (limit,)).fetchall()
            return [row["total_score"] for row in reversed(rows)]
        except sqlite3.OperationalError:
            return []

    # ── Market snapshots ──────────────────────────────────────────

    def log_snapshot(self, snap: Dict) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO market_snapshots
                   (ts, bid, ask, spread, atr_m5, vol_regime,
                    vol_pct, of_score, liq_score, ms_trend,
                    session_active, dom_mode)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    snap.get("bid"), snap.get("ask"),
                    snap.get("spread"), snap.get("atr_m5"),
                    snap.get("vol_regime"), snap.get("vol_pct"),
                    snap.get("of_score"), snap.get("liq_score"),
                    snap.get("ms_trend"), int(snap.get("session_active", 0)),
                    int(snap.get("dom_mode", 0)),
                ),
            )

    # ── System events ─────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        message: str,
        severity: str = "INFO",
        data: Optional[Dict] = None,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO system_events (ts, event_type, severity, message, data)
                   VALUES (?,?,?,?,?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    event_type, severity, message,
                    json.dumps(data) if data else None,
                ),
            )

    def get_events(
        self, limit: int = 50, severity: Optional[str] = None
    ) -> List[Dict]:
        if severity:
            rows = self._conn().execute(
                "SELECT * FROM system_events WHERE severity=? "
                "ORDER BY ts DESC LIMIT ?",
                (severity, limit),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM system_events ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Latency ───────────────────────────────────────────────────

    def log_latency(self, operation: str, latency_ms: float) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO latency_log (ts, operation, latency_ms) VALUES (?,?,?)",
                (datetime.now(timezone.utc).isoformat(), operation, latency_ms),
            )

    def avg_latency(self, operation: str, minutes: int = 60) -> float:
        row = self._conn().execute(
            """SELECT AVG(latency_ms) FROM latency_log
               WHERE operation=? AND ts > datetime('now', ?)""",
            (operation, f"-{minutes} minutes"),
        ).fetchone()
        return float(row[0] or 0.0)

    # ── ML training log ───────────────────────────────────────────

    def log_ml_context(self, ctx) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO ml_training (
                    trade_id, direction, of_score, liq_score, ms_score,
                    vol_score, session_score, news_score, spread_ratio,
                    atr_pct, hour_of_day, dom_mode, vol_expansion,
                    bos_event, choch_event, liq_grab_event,
                    realized_pnl, win, entry_time
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ctx.trade_id, ctx.direction,
                    ctx.of_score, ctx.liq_score, ctx.ms_score,
                    ctx.vol_score, ctx.session_score, ctx.news_score,
                    ctx.spread_ratio, ctx.atr_pct, ctx.hour_of_day,
                    int(ctx.dom_mode), int(ctx.vol_expansion),
                    int(ctx.bos_event), int(ctx.choch_event),
                    int(ctx.liq_grab_event),
                    ctx.realized_pnl if ctx.realized_pnl else None,
                    int(ctx.win) if ctx.win is not None else None,
                    ctx.entry_time,
                ),
            )

    # ── Daily stats ───────────────────────────────────────────────

    def compute_daily_stats(self, date: str) -> Dict:
        import math, statistics as _st
        trades = self._conn().execute(
            "SELECT * FROM trades WHERE DATE(entry_time)=? AND status='CLOSED'",
            (date,),
        ).fetchall()
        trades = [dict(t) for t in trades]
        if not trades:
            return {}

        pnls    = [t.get("realized_pnl", 0) or 0 for t in trades]
        winners = [p for p in pnls if p > 0]
        losers  = [p for p in pnls if p <= 0]
        gp      = sum(winners)
        gl      = abs(sum(losers))
        n       = len(trades)

        sharpe = sortino = 0.0
        if len(pnls) > 1:
            mu  = _st.mean(pnls)
            std = _st.stdev(pnls)
            if std > 0:
                sharpe = mu / std * math.sqrt(252)
            neg = [p for p in pnls if p < 0]
            if len(neg) > 1:
                down_std = _st.stdev(neg)
                if down_std > 0:
                    sortino = mu / down_std * math.sqrt(252)

        # Equity drawdown
        eq = 0.0
        pk = 0.0
        mx_dd = 0.0
        for p in pnls:
            eq += p
            pk = max(pk, eq)
            mx_dd = max(mx_dd, pk - eq)

        stats = {
            "date":           date,
            "total_trades":   n,
            "winning":        len(winners),
            "losing":         len(losers),
            "gross_profit":   round(gp, 2),
            "gross_loss":     round(gl, 2),
            "net_pnl":        round(gp - gl, 2),
            "win_rate":       round(len(winners) / n * 100, 1),
            "profit_factor":  round(gp / gl, 2) if gl > 0 else 0.0,
            "avg_quality":    round(
                sum(t.get("quality_score", 0) or 0 for t in trades) / n, 1
            ),
            "avg_latency_ms": round(self.avg_latency("order_fill"), 1),
            "avg_slippage":   round(
                sum(t.get("slippage", 0) or 0 for t in trades) / n, 4
            ),
            "max_drawdown":   round(mx_dd, 2),
            "sharpe":         round(sharpe, 3),
            "sortino":        round(sortino, 3),
        }
        with self._tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO daily_stats
                   (date, total_trades, winning, losing, gross_profit,
                    gross_loss, net_pnl, win_rate, profit_factor,
                    avg_quality, avg_latency_ms, avg_slippage,
                    max_drawdown, sharpe, sortino)
                   VALUES (:date,:total_trades,:winning,:losing,:gross_profit,
                    :gross_loss,:net_pnl,:win_rate,:profit_factor,
                    :avg_quality,:avg_latency_ms,:avg_slippage,
                    :max_drawdown,:sharpe,:sortino)""",
                stats,
            )
        return stats

    def get_daily_stats(self, days: int = 30) -> List[Dict]:
        rows = self._conn().execute(
            "SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Backup ────────────────────────────────────────────────────

    def backup(self, backup_dir: str = "database/backups") -> str:
        dest_dir = Path(backup_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = dest_dir / f"trading_{ts}.db"
        shutil.copy2(str(self._path), str(dest))
        logger.info(f"DB backup: {dest}")
        return str(dest)

    def cleanup_old(self, days: int = 90) -> None:
        for table in ("market_snapshots", "quality_log", "latency_log"):
            with self._tx() as conn:
                conn.execute(
                    f"DELETE FROM {table} WHERE ts < datetime('now', ?)",
                    (f"-{days} days",),
                )
        logger.info(f"Cleaned data older than {days} days")
