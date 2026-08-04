"""
app/main.py — System Orchestrator (Multi-Asset)

Central system orchestrator for the institutional multi-market trading system.
All timing, recovery, and inter-component wiring lives here.

Multi-asset upgrade:
  - MultiSymbolMarketData replaces single MarketData
  - MarketSelector ranks all enabled symbols every scan interval
  - TradeEngine.evaluate() called with best symbol
  - TradeEngine.manage_all() manages all open positions
  - PerformanceTracker records metrics for every closed trade
  - Bar loop refreshes bars for all enabled symbols
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings, enabled_symbols
from app.database import Database
from app.health import HealthMonitor
from app.market_data import MultiSymbolMarketData, MarketData, TF_M1, TF_M5, TF_M15, TF_H1
from app.mt5_client import MT5Client
from app.notifier import TelegramNotifier
from app.order_flow import OrderFlowEngine
from app.dom_engine import DOMEngine
from app.microstructure import MicrostructureEngine
from app.volume_analytics import VolumeAnalytics
from app.session import SessionFilter
from app.trade_quality import TradeQualityEngine
from app.market_selector import MarketSelector
from app.performance import PerformanceTracker
from app.ml_layer import MLLayer
from app.risk_manager import RiskManager
from app.trade_engine import TradeEngine
from reports.generator import ReportGenerator
from dashboard.app import app as dash_app, inject

# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logging() -> logging.Logger:
    log_dir = Path(settings.system.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, settings.system.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter(
        "\033[90m%(asctime)s\033[0m %(levelname)s "
        "\033[36m%(name)s\033[0m | %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(ch)

    fh = logging.handlers.TimedRotatingFileHandler(
        log_dir / "xauusd_pro.log",
        when="midnight", backupCount=30, encoding="utf-8", utc=True,
    )
    fh.setFormatter(logging.Formatter(
        '{"ts":"%(asctime)s","lvl":"%(levelname)s",'
        '"mod":"%(name)s","msg":"%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root.addHandler(fh)

    eh = logging.handlers.RotatingFileHandler(
        log_dir / "errors.log",
        maxBytes=20 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    eh.setLevel(logging.ERROR)
    eh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s | %(message)s"
    ))
    root.addHandler(eh)

    for noisy in ["websockets", "urllib3", "aiohttp", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger("multi_market_bot")


logger = _setup_logging()


# ── Orchestrator ──────────────────────────────────────────────────────────────

class Orchestrator:
    """
    Central system orchestrator — multi-asset edition.
    Manages the full lifecycle of the multi-market trading system.
    """

    # Loop intervals
    _TICK_POLL_MS    = 100     # poll MT5 for new ticks (all symbols)
    _BAR_REFRESH_S   = 60      # refresh OHLCV bars (all symbols)
    _ACCOUNT_SYNC_S  = 10      # sync account state
    _NEWS_FETCH_S    = 300     # fetch news calendar
    _SNAPSHOT_LOG_S  = 60      # persist market snapshot
    _MICRO_UPDATE_N  = 50      # update microstructure every N ticks
    _HEALTH_INTERVAL = 30      # health check interval

    def __init__(self):
        self._symbols = enabled_symbols()
        logger.info(f"Enabled symbols: {self._symbols}")

        # Infrastructure
        self.db       = Database(settings.system.db_path)
        self.client   = MT5Client()
        self.notifier = TelegramNotifier()

        # Multi-symbol market data registry
        self.msd      = MultiSymbolMarketData(self._symbols)

        # Per-primary-symbol engines (order flow / microstructure operate on
        # the currently selected symbol — they are fed data from the best symbol's MD)
        self.of     = OrderFlowEngine()
        self.dom    = DOMEngine()
        self.micro  = MicrostructureEngine()
        self.vol    = VolumeAnalytics()
        self.session = SessionFilter()

        # Signal + risk + quality
        self.quality   = TradeQualityEngine()
        self.selector  = MarketSelector()
        self.risk      = RiskManager()
        self.ml        = MLLayer()
        self.perf:     Optional[PerformanceTracker] = None  # initialized after connect

        # Execution (uses primary MarketData as fallback; msd provides per-symbol)
        primary_md = self.msd.get(self._symbols[0]) or MarketData()
        self.engine = TradeEngine(
            client=self.client, market=primary_md,
            of_engine=self.of, dom_engine=self.dom,
            micro=self.micro, vol=self.vol,
            quality=self.quality, risk=self.risk,
            session=self.session, ml=self.ml, db=self.db,
        )

        # Monitoring
        self.health  = HealthMonitor(self.client, primary_md, self.risk, self.db)
        self.reports = ReportGenerator(settings.system.report_dir)

        # Dashboard state
        self._state: dict = {}
        inject(self._state, self.db, self.health)

        # Control
        self._running  = False
        self._shutdown = asyncio.Event()
        self._tasks    = []

        # Counters / tracking
        self._tick_count:     int   = 0
        self._last_bar_ref:   float = 0.0
        self._last_acct_sync: float = 0.0
        self._last_snap_log:  float = 0.0
        self._last_daily_rpt: str   = ""
        self._prev_ticks:     dict  = {}   # symbol → last mid price
        self._start_time:     float = time.time()

        # Current best symbol from selector
        self._best_symbol: Optional[str] = None

    # ── Startup ───────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("=" * 60)
        logger.info("  Institutional Multi-Market Trading System — Starting")
        logger.info(f"  Symbols: {self._symbols}")
        logger.info("=" * 60)
        self._running = True

        # 1. Connect MT5 (discovers all symbols)
        if not self.client.connect():
            raise RuntimeError("MT5 connection failed")

        # 2. Log discovered symbols
        active = self.client.active_symbols
        logger.info(f"Broker-confirmed symbols: {active}")
        # Narrow tracked symbols to those confirmed by broker
        confirmed = [s for s in self._symbols if s in active or not active]

        # 3. Initial account state
        account = self.client.get_account()
        if not account or account.get("login") != settings.mt5.login:
            print("\nERROR: Connected to the wrong account.\n")
            raise RuntimeError(f"ERROR: Connected to the wrong account. Target: #{settings.mt5.login}, Got: #{getattr(account, 'get', lambda k:0)('login')} on server '{getattr(account, 'get', lambda k:'Unknown')('server')}'")
        self.risk.initialize(account["balance"])
        self.perf = PerformanceTracker(account["balance"])
        self.engine.set_close_callback(self.perf.record_trade)

        # 4. Warm up all confirmed symbols
        await self._warmup(confirmed)

        # 5. Start Telegram
        await self.notifier.start()
        await self.notifier.startup(
            account["balance"],
            ", ".join(confirmed[:4]),
            self.client.dom_active,
        )

        # 6. Start background tasks
        self._tasks = [
            asyncio.create_task(self._tick_loop(),     name="tick_loop"),
            asyncio.create_task(self._bar_loop(),      name="bar_loop"),
            asyncio.create_task(self._account_loop(),  name="account_loop"),
            asyncio.create_task(self._news_loop(),     name="news_loop"),
            asyncio.create_task(self.health.run_loop(self._HEALTH_INTERVAL),
                                 name="health_loop"),
            asyncio.create_task(self._dashboard(),     name="dashboard"),
            asyncio.create_task(self._daily_report(),  name="daily_report"),
            asyncio.create_task(self._backup_loop(),   name="backup_loop"),
        ]

        self.db.log_event("SYSTEM_START", "Multi-Market Bot started",
                          data={"balance": account["balance"],
                                "symbols": self._symbols})
        logger.info(
            f"✅ Live — {len(confirmed)} symbols active "
            f"dom={'active' if self.client.dom_active else 'fallback'}"
        )
        print("\n" + "=" * 40)
        print("SYSTEM STATUS: LIVE")
        print(f"BROKER: {account.get('server', settings.mt5.server)}")
        print(f"ACCOUNT: {account.get('login', settings.mt5.login)}")
        print(f"MODE: {'DEMO' if account.get('trade_mode') == 0 else ('LIVE' if account.get('trade_mode') == 2 else 'CONTEST')}")
        print("BOT: RUNNING")
        print("READY TO TRADE")
        print("=" * 40 + "\n")

    async def run(self) -> None:
        await self._shutdown.wait()

    async def shutdown(self, reason: str = "Manual") -> None:
        if not self._running:
            return
        self._running = False
        logger.info(f"Shutdown: {reason}")

        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

        if any(kw in reason.lower() for kw in ("emergency", "critical", "drawdown")):
            await self.engine.emergency_close()

        acct = self.client.get_account()
        bal  = acct["balance"] if acct else 0.0
        await self.notifier.shutdown(reason, bal)
        await self.notifier.stop()
        self.client.disconnect()
        self.db.log_event("SYSTEM_STOP", reason)
        self._shutdown.set()
        logger.info("Shutdown complete")

    # ── Warm-up (all symbols) ─────────────────────────────────────────────────

    async def _warmup(self, symbols: list) -> None:
        logger.info(f"Warming up indicators for {symbols}…")
        try:
            import MetaTrader5 as mt5
            tf_map = {
                TF_H1:  mt5.TIMEFRAME_H1,
                TF_M15: mt5.TIMEFRAME_M15,
                TF_M5:  mt5.TIMEFRAME_M5,
                TF_M1:  mt5.TIMEFRAME_M1,
            }
        except ImportError:
            tf_map = {}

        loop = asyncio.get_event_loop()

        for sym in symbols:
            md = self.msd.get(sym)
            if md is None:
                continue

            if tf_map:
                for tf_int, tf_mt5 in tf_map.items():
                    bars = await loop.run_in_executor(
                        None, self.client.get_rates, tf_mt5, 300, sym
                    )
                    md.load_bars(tf_int, bars)
                    if tf_int >= TF_M5:
                        for raw in bars:
                            from app.market_data import Bar
                            b = Bar(
                                time=raw["time"], open=raw["open"],
                                high=raw["high"], low=raw["low"],
                                close=raw["close"],
                                tick_vol=raw.get("tick_volume", 0),
                            )
                            self.vol.process_bar(b)
                logger.debug(f"  Warmed up {sym}")
            else:
                # Simulation: generate synthetic bars
                import random
                base = {"XAUUSD": 1950.0, "EURUSD": 1.085, "GBPUSD": 1.27,
                        "USDJPY": 149.5, "NAS100": 18500.0,
                        "US30": 39000.0, "BTCUSD": 67000.0}.get(sym, 1000.0)
                for tf in [TF_H1, TF_M15, TF_M5, TF_M1]:
                    p = base
                    bars_raw = []
                    for _ in range(300):
                        o = p + random.uniform(-base * 0.0005, base * 0.0005)
                        h = o + random.uniform(0, base * 0.001)
                        lo = o - random.uniform(0, base * 0.001)
                        c = random.uniform(lo, h)
                        bars_raw.append({
                            "time": datetime.now(timezone.utc),
                            "open": o, "high": h, "low": lo, "close": c,
                            "tick_volume": random.randint(100, 1000),
                            "spread": 15, "real_volume": 0,
                        })
                        p = c
                    md.load_bars(tf, bars_raw)

        # Initial microstructure on primary symbol M15
        primary_md = self.msd.get(symbols[0]) if symbols else None
        if primary_md:
            m15_bars = primary_md.bars(TF_M15)
            if m15_bars:
                self.micro.analyse(m15_bars, primary_md.atr(TF_M5))

        logger.info("Warm-up complete — all symbol indicators ready")

    # ── Tick loop ─────────────────────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        logger.info("Multi-symbol tick loop started")
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                # 1. Fetch ticks for all symbols (fastest path: each is a quick MT5 call)
                ticks_received = 0
                for sym in self._symbols:
                    md = self.msd.get(sym)
                    if md is None:
                        continue

                    raw = await loop.run_in_executor(
                        None, self.client.get_tick, sym
                    )
                    if raw is None:
                        continue

                    tick = md.ingest_tick(raw)
                    if tick is None:
                        continue

                    ticks_received += 1
                    prev_mid = self._prev_ticks.get(sym)
                    self._prev_ticks[sym] = tick.mid

                    # Order flow + volume analytics on primary symbol
                    # (OF/DOM engines track one symbol at a time;
                    #  future enhancement: per-symbol OF instances)
                    if sym == (self._best_symbol or self._symbols[0]):
                        of_snap = self.of.process(tick)
                        dom_snap = await loop.run_in_executor(
                            None, self.client.get_dom, sym
                        )
                        dom_metrics = self.dom.process(tick, dom_snap, md.avg_spread)
                        self.vol.process_tick(tick, prev_mid)

                self._tick_count += 1

                # 2. Microstructure (every N ticks, on best symbol)
                if self._tick_count % self._MICRO_UPDATE_N == 0:
                    best_sym = self._best_symbol or self._symbols[0]
                    best_md  = self.msd.get(best_sym)
                    if best_md:
                        m15 = best_md.bars(TF_M15)
                        if m15:
                            self.micro.analyse(m15, best_md.atr(TF_M5))

                # 3. Session evaluation
                self.session.evaluate()

                # 4. Market selection (throttled internally by selector)
                selector_state = self.selector.rank_all(
                    self.msd,
                    self.session.state,
                    self.session._cache,
                )
                best = self.selector.best()
                self._best_symbol = best.symbol if best else None

                # 5. Manage ALL open positions
                await self.engine.manage_all(self.msd)

                # 6. If best symbol found & we have budget, evaluate entry
                if best and self._best_symbol:
                    best_md = self.msd.get(self._best_symbol)
                    if best_md:
                        await self.engine.evaluate(
                            symbol=self._best_symbol,
                            market_md=best_md,
                            selector=self.selector,
                        )

                # 7. Dashboard state refresh
                of_snap_state  = self.of.latest
                dom_metrics_state = self.dom.latest_dom or self.dom.latest_fallback
                self._refresh_state(of_snap_state, dom_metrics_state)

                # 8. Snapshot logging (throttled)
                if time.time() - self._last_snap_log >= self._SNAPSHOT_LOG_S:
                    self._log_snapshot()
                    self._last_snap_log = time.time()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Tick loop error: {e}")
                await asyncio.sleep(1.0)

            await asyncio.sleep(self._TICK_POLL_MS / 1000)

    # ── Bar refresh (all symbols) ─────────────────────────────────────────────

    async def _bar_loop(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            import MetaTrader5 as mt5
            tf_map = {
                TF_H1:  mt5.TIMEFRAME_H1,
                TF_M15: mt5.TIMEFRAME_M15,
                TF_M5:  mt5.TIMEFRAME_M5,
                TF_M1:  mt5.TIMEFRAME_M1,
            }
        except ImportError:
            tf_map = {}

        while self._running:
            try:
                for sym in self._symbols:
                    md = self.msd.get(sym)
                    if md is None:
                        continue
                    for tf_int, tf_mt5 in tf_map.items():
                        bars = await loop.run_in_executor(
                            None, self.client.get_rates, tf_mt5, 5, sym
                        )
                        for b in bars:
                            md.push_bar(tf_int, b)
                            if tf_int >= TF_M5:
                                from app.market_data import Bar
                                bar_obj = Bar(
                                    time=b["time"], open=b["open"],
                                    high=b["high"], low=b["low"],
                                    close=b["close"],
                                    tick_vol=b.get("tick_volume", 0),
                                )
                                self.vol.process_bar(bar_obj)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Bar refresh error: {e}")
            await asyncio.sleep(self._BAR_REFRESH_S)

    # ── Account sync ──────────────────────────────────────────────────────────

    async def _account_loop(self) -> None:
        loop = asyncio.get_event_loop()
        _warned_dd = False

        while self._running:
            try:
                acct = await loop.run_in_executor(None, self.client.get_account)
                if acct:
                    dd = self.risk.update_equity(acct["balance"], acct["equity"])
                    self._state["account"] = {
                        "balance":      round(acct["balance"], 2),
                        "equity":       round(acct["equity"], 2),
                        "free_margin":  round(acct["free_margin"], 2),
                        "margin_level": round(acct["margin_level"], 1),
                        "profit":       round(acct["profit"], 2),
                        "currency":     acct["currency"],
                    }
                    self._state["risk"] = self.risk.summary()

                    # Performance snapshot
                    if self.perf:
                        snap = self.perf.snapshot(
                            acct["balance"],
                            acct["equity"],
                            open_positions=self.engine.open_trade_count(),
                            floating_pnl=acct["profit"]
                        )
                        self._state["performance"] = self.perf.to_dict()

                    # Drawdown warning at 75%
                    warn_thresh = settings.risk.daily_dd_limit * 0.75
                    if dd.daily_dd_pct >= warn_thresh and not _warned_dd:
                        await self.notifier.drawdown_warning(
                            dd.daily_dd_pct, dd.account_dd_pct, acct["balance"]
                        )
                        _warned_dd = True

                    if dd.daily_dd_pct < warn_thresh * 0.8:
                        _warned_dd = False

                    if self.risk.circuit_broken:
                        await self.notifier.circuit_breaker("Risk limit exceeded")

                    if dd.account_hit:
                        await self.notifier.critical_error(
                            f"Account DD limit: {dd.account_dd_pct:.2f}%"
                        )
                        await self.shutdown("Account drawdown emergency")
                        return

                if not self.client.heartbeat():
                    logger.warning("MT5 heartbeat failed")
                    await self.notifier.mt5_disconnected(1)
                    ok = await loop.run_in_executor(None, self.client.reconnect)
                    if ok:
                        await self.notifier.mt5_reconnected()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Account loop error: {e}")
            await asyncio.sleep(self._ACCOUNT_SYNC_S)

    # ── News fetch ────────────────────────────────────────────────────────────

    async def _news_loop(self) -> None:
        while self._running:
            try:
                await self.session.fetch_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"News fetch: {e}")
            await asyncio.sleep(self._NEWS_FETCH_S)

    # ── Dashboard server ──────────────────────────────────────────────────────

    async def _dashboard(self) -> None:
        cfg = settings.dashboard
        try:
            server = uvicorn.Server(uvicorn.Config(
                dash_app, host=cfg.host, port=cfg.port,
                log_level="warning", loop="none",
            ))
            await server.serve()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        except BaseException as e:
            logger.warning(f"Embedded dashboard server disabled (port collision or external launcher active): {e}")

    # ── Daily report ──────────────────────────────────────────────────────────

    async def _daily_report(self) -> None:
        while self._running:
            try:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                hour  = datetime.now(timezone.utc).hour
                if hour == 21 and self._last_daily_rpt != today:
                    self._last_daily_rpt = today
                    stats = self.reports.generate_daily(self.db, today)
                    if stats:
                        await self.notifier.daily_summary(stats)
                    trades = self.db.get_closed_trades(500)
                    self.reports.export_trades_csv(trades, f"trades_{today}.csv")
                    self.db.cleanup_old()

                now = datetime.now(timezone.utc)
                if now.weekday() == 0 and hour == 6:
                    weekly = self.reports.generate_weekly(self.db)
                    if weekly:
                        await self.notifier.weekly_summary(weekly)
                    self.vol.reset_session()

                self.ml.maybe_retrain()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Daily report: {e}")
            await asyncio.sleep(3600)

    # ── DB backup ─────────────────────────────────────────────────────────────

    async def _backup_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(3600)
                self.db.backup("database/backups")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Backup: {e}")

    # ── State helpers ─────────────────────────────────────────────────────────

    def _refresh_state(self, of_snap, dom_metrics) -> None:
        ms = self.micro.state()
        # Use best-symbol market data for dashboard
        best_sym = self._best_symbol or (self._symbols[0] if self._symbols else "XAUUSD")
        best_md  = self.msd.get(best_sym)

        self._state.update({
            "best_symbol":     best_sym,
            "market":          {**(best_md.snapshot() if best_md else {}),
                                "of_score": of_snap.of_score if of_snap else 0},
            "all_markets":     self.msd.snapshots(),
            "selector":        self.selector.snapshot_dict(),
            "of":              self.of.snapshot_dict(),
            "dom":             self.dom.snapshot_dict(),
            "micro":           self.micro.snapshot_dict(),
            "vol":             self.vol.snapshot_dict(),
            "session":         self.session.snapshot_dict(),
            "quality":         self.quality.snapshot_dict(),
            "trade":           self.engine.status(),
            "ml":              self.ml.summary_dict(),
        })
        if self.health.latest:
            self._state["health"] = self.health.latest.to_dict()
        else:
            self._state["health"] = {
                "healthy":       self.client.connected,
                "mt5_connected": self.client.connected,
                "dom_active":    self.client.dom_active,
                "feed_fresh":    True,
                "feed_age_ms":   10.0,
            }

    def _log_snapshot(self) -> None:
        ms = self.micro.state()
        best_sym = self._best_symbol or (self._symbols[0] if self._symbols else "XAUUSD")
        best_md  = self.msd.get(best_sym)
        snap = best_md.snapshot() if best_md else {}
        self.db.log_snapshot({
            **snap,
            "symbol":         best_sym,
            "ms_trend":       ms.trend,
            "session_active": self.session.is_tradeable(),
            "dom_mode":       self.dom.using_dom,
            "open_trades":    self.engine.open_trade_count(),
        })


# ── Signal handlers ───────────────────────────────────────────────────────────

_orch: Optional[Orchestrator] = None


def _handle_sig(sig) -> None:
    logger.info(f"Signal {sig.name} received")
    if _orch:
        asyncio.create_task(_orch.shutdown(f"Signal {sig.name}"))


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    global _orch
    _orch = Orchestrator()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _handle_sig(s))
        except (NotImplementedError, OSError):
            pass  # Windows

    try:
        await _orch.start()
        await _orch.run()
    except KeyboardInterrupt:
        await _orch.shutdown("KeyboardInterrupt")
    except Exception as e:
        logger.critical(f"Fatal: {e}", exc_info=True)
        if _orch:
            await _orch.shutdown(f"Fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
