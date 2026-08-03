"""
app/notifier.py — Telegram Notification Service

Sends rich HTML-formatted alerts for all trading events.
Queued, async, non-blocking with automatic retry.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)

E = {
    "start":   "🚀", "stop":    "🛑",
    "long":    "🟢", "short":   "🔴",
    "win":     "✅", "loss":    "❌",
    "warn":    "⚠️", "crit":    "🚨",
    "daily":   "📊", "weekly":  "📈",
    "mt5_ok":  "🔌", "mt5_err": "⚡",
    "circuit": "⛔", "info":    "ℹ️",
}


class TelegramNotifier:
    def __init__(self):
        self._cfg  = settings.telegram
        self._q:   asyncio.Queue = asyncio.Queue(maxsize=300)
        self._run  = False
        self._sess: Optional[aiohttp.ClientSession] = None

    @property
    def _url(self) -> str:
        return f"https://api.telegram.org/bot{self._cfg.bot_token}/sendMessage"

    async def _raw(self, text: str) -> bool:
        if not self._cfg.enabled:
            return True
        if not self._sess or self._sess.closed:
            self._sess = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        for attempt in range(3):
            try:
                async with self._sess.post(self._url, json={
                    "chat_id": self._cfg.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }) as r:
                    if r.status == 200:
                        return True
                    if r.status == 429:
                        await asyncio.sleep(5 * (attempt + 1))
                    else:
                        return False
            except Exception as e:
                logger.debug(f"Telegram attempt {attempt+1}: {e}")
                await asyncio.sleep(2)
        return False

    async def send(self, text: str) -> None:
        try:
            self._q.put_nowait(text)
        except asyncio.QueueFull:
            logger.debug("Telegram queue full")

    async def _loop(self) -> None:
        while self._run:
            try:
                text = await asyncio.wait_for(self._q.get(), timeout=1.0)
                await self._raw(text)
                self._q.task_done()
                await asyncio.sleep(0.4)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        if not self._cfg.enabled:
            logger.info("Telegram disabled")
            return
        self._run = True
        asyncio.create_task(self._loop(), name="telegram")
        logger.info("Telegram notifier started")

    async def stop(self) -> None:
        self._run = False
        if self._sess and not self._sess.closed:
            await self._sess.close()

    @staticmethod
    def _ts() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── Alert methods ─────────────────────────────────────────────

    async def startup(self, balance: float, symbol: str, dom: bool) -> None:
        await self.send(
            f"{E['start']} <b>XAUUSD Pro Scalper STARTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {self._ts()}\n"
            f"💵 Balance: <b>${balance:,.2f}</b>\n"
            f"📈 Symbol: <b>{symbol}</b>\n"
            f"📖 DOM: <b>{'Active' if dom else 'Fallback (tick-based)'}</b>\n"
            f"System is live."
        )

    async def shutdown(self, reason: str, balance: float) -> None:
        await self.send(
            f"{E['stop']} <b>Scalper STOPPED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {self._ts()}\n"
            f"📋 Reason: {reason}\n"
            f"💵 Balance: ${balance:,.2f}"
        )

    async def trade_opened(self, trade) -> None:
        em = E["long"] if trade.direction == "LONG" else E["short"]
        await self.send(
            f"{em} <b>TRADE OPENED: {trade.direction}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Entry: <b>${trade.entry_price:,.2f}</b>\n"
            f"📐 Volume: {trade.volume} lots\n"
            f"💸 Risk: ${trade.risk_usd:,.2f}\n"
            f"🛑 SL: ${trade.sl:,.2f}\n"
            f"🎯 TP1/2/3: ${trade.tp1:,.0f} / ${trade.tp2:,.0f} / ${trade.tp3:,.0f}\n"
            f"🎲 Quality: <b>{trade.quality_score:.0f}/100</b>\n"
            f"📡 Spread: {trade.spread_entry*100:.0f}pts  "
            f"Lat: {trade.latency_ms:.0f}ms\n"
            f"🆔 <code>{trade.trade_id}</code>"
        )

    async def trade_closed(self, trade) -> None:
        pnl  = trade.realized_pnl
        em   = E["win"] if pnl >= 0 else E["loss"]
        sign = "+" if pnl >= 0 else ""
        dur  = ""
        if trade.entry_time and trade.close_time:
            m = (trade.close_time - trade.entry_time).total_seconds() / 60
            dur = f"⏱ Duration: {m:.0f}m\n"
        await self.send(
            f"{em} <b>TRADE CLOSED: {trade.direction}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Entry: ${trade.entry_price:,.2f}\n"
            f"📍 Exit:  <b>${trade.close_price:,.2f}</b>\n"
            f"💵 P&L: <b>{sign}${pnl:,.2f}</b>\n"
            f"📋 Reason: {trade.close_reason}\n"
            f"{dur}"
            f"🆔 <code>{trade.trade_id}</code>"
        )

    async def mt5_disconnected(self, attempt: int) -> None:
        await self.send(
            f"{E['mt5_err']} <b>MT5 DISCONNECTED</b>\n"
            f"🕐 {self._ts()}\n"
            f"🔁 Reconnect attempt {attempt}"
        )

    async def mt5_reconnected(self) -> None:
        await self.send(
            f"{E['mt5_ok']} <b>MT5 RECONNECTED</b>\n"
            f"🕐 {self._ts()}"
        )

    async def circuit_breaker(self, reason: str) -> None:
        await self.send(
            f"{E['circuit']} <b>CIRCUIT BREAKER</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {self._ts()}\n"
            f"📋 Reason: <b>{reason}</b>\n"
            f"Trading halted. Manual reset required."
        )

    async def drawdown_warning(self, daily: float, acct: float, bal: float) -> None:
        await self.send(
            f"{E['warn']} <b>DRAWDOWN WARNING</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Daily: <b>{daily:.2f}%</b>\n"
            f"📉 Account: <b>{acct:.2f}%</b>\n"
            f"💵 Balance: ${bal:,.2f}"
        )

    async def daily_summary(self, stats: Dict[str, Any]) -> None:
        pnl  = stats.get("net_pnl", 0)
        sign = "+" if pnl >= 0 else ""
        await self.send(
            f"{E['daily']} <b>Daily Summary — {stats.get('date', '')}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Trades: {stats.get('total_trades', 0)}\n"
            f"✅ Wins: {stats.get('winning', 0)}\n"
            f"❌ Losses: {stats.get('losing', 0)}\n"
            f"🎯 Win Rate: {stats.get('win_rate', 0):.1f}%\n"
            f"📐 Profit Factor: {stats.get('profit_factor', 0):.2f}\n"
            f"💵 Net P&L: <b>{sign}${pnl:,.2f}</b>\n"
            f"⚡ Avg Quality: {stats.get('avg_quality', 0):.0f}/100\n"
            f"📡 Avg Latency: {stats.get('avg_latency_ms', 0):.0f}ms\n"
            f"📉 Sharpe: {stats.get('sharpe', 0):.3f}"
        )

    async def weekly_summary(self, stats: Dict[str, Any]) -> None:
        pnl  = stats.get("net_pnl", 0)
        sign = "+" if pnl >= 0 else ""
        await self.send(
            f"{E['weekly']} <b>Weekly Summary</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Trades: {stats.get('total_trades', 0)}\n"
            f"🎯 Win Rate: {stats.get('win_rate', 0):.1f}%\n"
            f"💵 Net P&L: <b>{sign}${pnl:,.2f}</b>\n"
            f"📐 Profit Factor: {stats.get('profit_factor', 0):.2f}"
        )

    async def critical_error(self, msg: str) -> None:
        await self.send(
            f"{E['crit']} <b>CRITICAL ERROR</b>\n"
            f"🕐 {self._ts()}\n{msg}"
        )
