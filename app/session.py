"""
app/session.py — Session Intelligence & News Filter

Detects: Asian / London / London-NY overlap / New York sessions.
Trades only during London and London/NY overlap.

Integrates:
  - Forex Factory calendar (free JSON feed)
  - Trading Economics (if API key provided)
  - NewsAPI headlines for sentiment
  - MarketAux financial news

All external APIs are optional — the bot runs safely without them.
News blackout: 30 min before + 15 min after high-impact events.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class NewsEvent:
    time:     datetime
    currency: str
    title:    str
    impact:   str      # "HIGH" | "MEDIUM" | "LOW"
    forecast: str = ""
    previous: str = ""
    actual:   str = ""


@dataclass
class SessionState:
    # Session flags
    is_asian:   bool = False
    is_london:  bool = False
    is_ny:      bool = False
    is_overlap: bool = False
    is_active:  bool = False   # London or overlap
    is_weekend: bool = False

    # Quality score 0-100
    session_quality: float = 0.0

    # News state
    news_blackout:      bool  = False
    next_event:         Optional[NewsEvent] = None
    minutes_to_event:   Optional[float] = None
    news_sentiment:     str   = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL
    news_score:         float = 50.0       # 0=very bearish, 100=very bullish


class SessionFilter:
    """
    Session + news intelligence filter.
    evaluate() is fast and synchronous.
    fetch_news() is async and called periodically in background.
    """

    def __init__(self):
        self._cfg_s = settings.session
        self._cfg_n = settings.news
        self._cache: List[NewsEvent] = []
        self._last_fetch: float = 0.0
        self._news_sentiment: str = "NEUTRAL"
        self._news_score: float = 50.0
        self._state = SessionState()

    # ── Synchronous evaluation ────────────────────────────────────

    def evaluate(self) -> SessionState:
        now  = datetime.now(timezone.utc)
        hour = now.hour + now.minute / 60.0

        cfg = self._cfg_s
        s   = self._state

        # Session flags
        s.is_weekend = now.weekday() >= 5
        s.is_london  = cfg.london_start <= hour < cfg.london_end
        s.is_ny      = cfg.ny_start <= hour < cfg.ny_end
        s.is_overlap = cfg.overlap_start <= hour < cfg.overlap_end
        s.is_asian   = (hour < cfg.london_start or hour >= 22.0) and not s.is_weekend
        s.is_active  = (s.is_london or s.is_overlap) and not s.is_weekend

        # Quality score
        if s.is_overlap:        s.session_quality = 95.0
        elif s.is_london:       s.session_quality = 80.0
        elif s.is_ny:           s.session_quality = 55.0
        elif s.is_asian:        s.session_quality = 20.0
        else:                   s.session_quality = 10.0

        if s.is_weekend:
            s.session_quality = 0.0

        # News blackout
        self._check_blackout(now)

        # Apply news sentiment
        s.news_sentiment = self._news_sentiment
        s.news_score     = self._news_score

        return s

    def _check_blackout(self, now: datetime) -> None:
        s = self._state
        s.news_blackout     = False
        s.next_event        = None
        s.minutes_to_event  = None

        if not self._cache:
            return

        pre  = self._cfg_s.news_pre_m
        post = self._cfg_s.news_post_m

        for event in self._cache:
            if event.impact != "HIGH":
                continue
            diff_m = (event.time - now).total_seconds() / 60.0

            if -post <= diff_m <= pre:
                s.news_blackout    = True
                s.next_event       = event
                s.minutes_to_event = diff_m
                return

            if 0 < diff_m <= pre * 2:
                if s.next_event is None:
                    s.next_event       = event
                    s.minutes_to_event = diff_m

    # ── Async news fetching ───────────────────────────────────────

    async def fetch_all(self) -> None:
        """Fetch all news sources. Called periodically (every 5 min)."""
        if not self._cfg_n.enabled:
            return
        if time.time() - self._last_fetch < self._cfg_n.fetch_interval_s:
            return

        events: List[NewsEvent] = []
        events = await self._fetch_forex_factory(events)
        events = await self._fetch_trading_economics(events)

        # Sentiment from headline feeds
        sentiment, score = await self._fetch_sentiment()
        self._news_sentiment = sentiment
        self._news_score     = score

        # Deduplicate + sort
        seen = set()
        unique = []
        for e in events:
            key = (e.time, e.currency, e.title[:20])
            if key not in seen:
                seen.add(key)
                unique.append(e)

        self._cache = sorted(unique, key=lambda x: x.time)
        self._last_fetch = time.time()
        hi = sum(1 for e in self._cache if e.impact == "HIGH")
        logger.info(f"News updated: {len(self._cache)} events ({hi} HIGH)")

    async def _fetch_forex_factory(
        self, events: List[NewsEvent]
    ) -> List[NewsEvent]:
        try:
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as sess:
                async with sess.get(url) as resp:
                    if resp.status != 200:
                        return events
                    data = await resp.json(content_type=None)

            currencies = {"USD", "XAU", "GBP", "EUR"}
            for item in data:
                if item.get("impact", "").upper() != "HIGH":
                    continue
                if item.get("currency", "") not in currencies:
                    continue
                try:
                    dt_str = item["date"].replace("Z", "+00:00")
                    dt = datetime.fromisoformat(dt_str)
                    events.append(NewsEvent(
                        time=dt,
                        currency=item.get("currency", ""),
                        title=item.get("title", ""),
                        impact="HIGH",
                        forecast=str(item.get("forecast", "")),
                        previous=str(item.get("previous", "")),
                    ))
                except (KeyError, ValueError):
                    continue
        except Exception as e:
            logger.debug(f"Forex Factory fetch skipped: {e}")
        return events

    async def _fetch_trading_economics(
        self, events: List[NewsEvent]
    ) -> List[NewsEvent]:
        key = self._cfg_n.trading_economics_key
        if not key:
            return events
        try:
            url = f"https://api.tradingeconomics.com/calendar/country/united states?c={key}&f=json"
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as sess:
                async with sess.get(url) as resp:
                    if resp.status != 200:
                        return events
                    data = await resp.json()

            for item in data:
                importance = str(item.get("importance", "0"))
                if importance not in ("3",):   # 3 = high impact
                    continue
                try:
                    dt = datetime.fromisoformat(
                        item["date"].replace("Z", "+00:00")
                    )
                    events.append(NewsEvent(
                        time=dt,
                        currency="USD",
                        title=item.get("event", ""),
                        impact="HIGH",
                        forecast=str(item.get("forecast", "")),
                        previous=str(item.get("previous", "")),
                    ))
                except (KeyError, ValueError):
                    continue
        except Exception as e:
            logger.debug(f"Trading Economics fetch skipped: {e}")
        return events

    async def _fetch_sentiment(self) -> tuple[str, float]:
        """
        Lightweight XAU sentiment from NewsAPI or MarketAux.
        Returns (sentiment_label, score_0_to_100).
        """
        headlines: List[str] = []

        # Try NewsAPI
        nk = self._cfg_n.news_api_key
        if nk:
            try:
                url = (
                    f"https://newsapi.org/v2/everything"
                    f"?q=gold+XAU&sortBy=publishedAt&pageSize=10"
                    f"&apiKey={nk}"
                )
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as sess:
                    async with sess.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for a in data.get("articles", []):
                                t = a.get("title") or ""
                                if t:
                                    headlines.append(t.lower())
            except Exception:
                pass

        # Try MarketAux
        mk = self._cfg_n.marketaux_key
        if mk and not headlines:
            try:
                url = (
                    f"https://api.marketaux.com/v1/news/all"
                    f"?symbols=XAUUSD&filter_entities=true"
                    f"&published_after={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M')}"
                    f"&api_token={mk}"
                )
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as sess:
                    async with sess.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for a in data.get("data", []):
                                t = a.get("title") or ""
                                if t:
                                    headlines.append(t.lower())
            except Exception:
                pass

        if not headlines:
            return "NEUTRAL", 50.0

        # Simple keyword sentiment
        bull_kw = [
            "rally", "surge", "gain", "rise", "jump", "record",
            "demand", "safe haven", "inflation", "bullish", "buy",
        ]
        bear_kw = [
            "fall", "drop", "decline", "plunge", "sell", "pressure",
            "rate hike", "dollar", "yields", "bearish", "loss",
        ]
        bull_hits = sum(1 for h in headlines for kw in bull_kw if kw in h)
        bear_hits = sum(1 for h in headlines for kw in bear_kw if kw in h)
        total = bull_hits + bear_hits or 1

        score = 50.0 + (bull_hits - bear_hits) / total * 30.0
        score = round(max(0.0, min(100.0, score)), 1)

        if score >= 65:   label = "BULLISH"
        elif score <= 35: label = "BEARISH"
        else:             label = "NEUTRAL"

        logger.debug(
            f"Sentiment: {label} ({score}) "
            f"bull={bull_hits} bear={bear_hits} from {len(headlines)} headlines"
        )
        return label, score

    # ── Quick checks ──────────────────────────────────────────────

    def is_tradeable(self) -> bool:
        s = self._state
        return s.is_active and not s.news_blackout and not s.is_weekend

    @property
    def state(self) -> SessionState:
        return self._state

    def snapshot_dict(self) -> Dict:
        s = self._state
        return {
            "is_london":     s.is_london,
            "is_ny":         s.is_ny,
            "is_overlap":    s.is_overlap,
            "is_active":     s.is_active,
            "session_quality": s.session_quality,
            "news_blackout": s.news_blackout,
            "news_sentiment": s.news_sentiment,
            "news_score":    s.news_score,
            "min_to_event":  round(s.minutes_to_event, 1) if s.minutes_to_event else None,
            "next_event":    s.next_event.title if s.next_event else None,
            "weekend":       s.is_weekend,
        }
