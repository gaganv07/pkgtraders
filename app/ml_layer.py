"""
app/ml_layer.py — Adaptive Trade Quality Model

An explainable, logistic-regression-style model that learns from
historical trade outcomes to adjust quality scoring weights.

Design principles:
  - No black-box neural networks
  - Fully explainable: feature importances are readable
  - Stores context + outcome for every closed trade
  - Retrains on every N new trades
  - Falls back gracefully if insufficient data

Features used:
  of_score, liq_score, ms_score, vol_score, session_score,
  news_score, spread_ratio, atr_pct, time_of_day (UTC hour),
  dom_mode (1=DOM, 0=fallback), vol_expansion, bos_event,
  choch_event, liq_grab_event

Outcome: binary (1=win, 0=loss) based on realized PnL > 0
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

_FEATURES = [
    "of_score", "liq_score", "ms_score", "vol_score",
    "session_score", "news_score", "spread_ratio",
    "atr_pct", "hour_sin", "hour_cos",
    "dom_mode", "vol_expansion", "bos_event",
    "choch_event", "liq_grab_event",
]


@dataclass
class TradeContext:
    """Snapshot of conditions at trade entry."""
    trade_id:     str
    direction:    str
    entry_time:   str

    # Quality scores
    of_score:     float = 50.0
    liq_score:    float = 50.0
    ms_score:     float = 50.0
    vol_score:    float = 50.0
    session_score: float = 50.0
    news_score:   float = 50.0

    # Market context
    spread_ratio:  float = 1.0    # current / avg
    atr_pct:       float = 0.1    # ATR / price %
    hour_of_day:   int   = 12     # UTC hour

    # Binary flags
    dom_mode:      bool  = False
    vol_expansion: bool  = False
    bos_event:     bool  = False
    choch_event:   bool  = False
    liq_grab_event: bool = False

    # Outcome (set after trade closes)
    realized_pnl:  float = 0.0
    win:           Optional[bool] = None

    def to_features(self) -> List[float]:
        h = self.hour_of_day
        return [
            self.of_score / 100.0,
            self.liq_score / 100.0,
            self.ms_score  / 100.0,
            self.vol_score / 100.0,
            self.session_score / 100.0,
            self.news_score / 100.0,
            min(self.spread_ratio, 5.0) / 5.0,
            min(self.atr_pct, 1.0),
            math.sin(2 * math.pi * h / 24),   # cyclical hour encoding
            math.cos(2 * math.pi * h / 24),
            float(self.dom_mode),
            float(self.vol_expansion),
            float(self.bos_event),
            float(self.choch_event),
            float(self.liq_grab_event),
        ]


class LogisticModel:
    """
    Lightweight logistic regression trained on binary outcomes.
    Uses gradient descent (mini-batch style) over the trade history.
    Weights are initialised to uniform (no bias) so the model starts neutral.
    """

    def __init__(self, n_features: int):
        self.w: List[float] = [0.0] * n_features
        self.b: float = 0.0
        self.lr: float = 0.05
        self._trained = False

    def _sigmoid(self, z: float) -> float:
        z = max(-500.0, min(500.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def predict_proba(self, features: List[float]) -> float:
        z = self.b + sum(w * x for w, x in zip(self.w, features))
        return self._sigmoid(z)

    def train(self, samples: List[Tuple[List[float], int]], epochs: int = 50) -> None:
        if not samples:
            return
        n = len(samples)
        for _ in range(epochs):
            for feats, label in samples:
                pred = self.predict_proba(feats)
                err  = pred - label
                for i, x in enumerate(feats):
                    self.w[i] -= self.lr * err * x
                self.b -= self.lr * err
        self._trained = True

    def feature_importances(self) -> Dict[str, float]:
        total = sum(abs(w) for w in self.w) or 1.0
        return {
            name: round(abs(w) / total * 100, 2)
            for name, w in zip(_FEATURES, self.w)
        }

    def to_dict(self) -> Dict:
        return {"weights": self.w, "bias": self.b}

    def from_dict(self, d: Dict) -> None:
        self.w = d.get("weights", self.w)
        self.b = d.get("bias", self.b)
        self._trained = True


class MLLayer:
    """
    Adaptive quality adjustment layer.

    Usage:
      1. On trade open:  ml.record_context(context)
      2. On trade close: ml.record_outcome(trade_id, pnl)
      3. On evaluation:  adjustment = ml.quality_adjustment(features)
      4. Periodically:   ml.maybe_retrain()
    """

    def __init__(self):
        cfg = settings.ml
        self._enabled      = cfg.enabled
        self._min_samples  = cfg.min_samples
        self._retrain_n    = cfg.retrain_every_n_trades
        self._model_path   = Path(cfg.model_path)
        self._model        = LogisticModel(len(_FEATURES))
        self._history:     List[TradeContext] = []
        self._pending:     Dict[str, TradeContext] = {}   # trade_id → context
        self._trades_since_train: int = 0
        self._load()

    def record_context(self, ctx: TradeContext) -> None:
        """Store entry context, awaiting outcome."""
        self._pending[ctx.trade_id] = ctx

    def record_outcome(self, trade_id: str, realized_pnl: float) -> None:
        """Attach outcome to pending context, move to history, and retrain."""
        ctx = self._pending.pop(trade_id, None)
        if ctx is None:
            # Create synthetic context if not pending
            ctx = TradeContext(
                trade_id=trade_id,
                direction="UNKNOWN",
                entry_time=datetime.now(timezone.utc).isoformat(),
            )
        ctx.realized_pnl = realized_pnl
        ctx.win = realized_pnl > 0
        self._history.append(ctx)
        self._trades_since_train += 1

        # Keep history bounded
        if len(self._history) > 1000:
            self._history = self._history[-800:]

        logger.info(
            f"[ML LEARNING] Trade {trade_id} outcome recorded: PnL=${realized_pnl:.2f} "
            f"({'WIN' if ctx.win else 'LOSS'}). Total historical trades={len(self._history)}"
        )
        
        # Trigger immediate online training on every trade outcome if history >= 5
        if len(self._history) >= 5:
            self._retrain()

    def maybe_retrain(self) -> bool:
        """Retrain if new trades have accumulated. Returns True if retrained."""
        if not self._enabled:
            return False
        if len(self._history) < 5:
            return False

        self._retrain()
        self._trades_since_train = 0
        return True

    def _retrain(self) -> None:
        closed = [c for c in self._history if c.win is not None]
        if len(closed) < 5:
            return

        samples = [(c.to_features(), int(c.win)) for c in closed]
        self._model.train(samples, epochs=100)
        self._save()

        imp = self._model.feature_importances()
        top5 = sorted(imp.items(), key=lambda x: -x[1])[:5]
        logger.info(
            f"[ML RETRAINED] Trained on {len(samples)} trade outcomes (Win Rate: {self.win_rate():.1f}%). "
            f"Top learned feature weights: {top5}"
        )

    def quality_adjustment(self, features: List[float]) -> float:
        """
        Return a score adjustment (-10 to +10) based on ML prediction.
        Returns 0.0 if model is not yet trained.
        """
        if not self._enabled or not self._model._trained:
            return 0.0
        prob = self._model.predict_proba(features)
        # prob > 0.5 → boost; prob < 0.5 → penalise
        adj = (prob - 0.5) * 20.0   # range -10 to +10
        return round(adj, 2)

    def win_rate(self) -> float:
        wins = sum(1 for c in self._history if c.win)
        n    = len(self._history)
        return wins / n * 100 if n > 0 else 0.0

    def feature_importances(self) -> Dict[str, float]:
        if not self._model._trained:
            return {}
        return self._model.feature_importances()

    def _save(self) -> None:
        self._model_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model": self._model.to_dict(),
            "win_rate": self.win_rate(),
            "n_trades": len(self._history),
            "importances": self.feature_importances(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        self._model_path.write_text(json.dumps(data, indent=2))
        logger.debug(f"ML model saved: {self._model_path}")

    def _load(self) -> None:
        # 1. Load saved model weights if available
        if self._model_path.exists():
            try:
                data = json.loads(self._model_path.read_text())
                self._model.from_dict(data.get("model", {}))
                logger.info(
                    f"ML model loaded: n_trades={data.get('n_trades', 0)} "
                    f"win_rate={data.get('win_rate', 0):.1f}%"
                )
            except Exception as e:
                logger.warning(f"ML model load failed: {e}")

        # 2. Load all historical trades from live_trade_journal.csv to build continuous memory
        self._load_journal_history()

    def _load_journal_history(self) -> None:
        """Parse live_trade_journal.csv and train on all historic trade outcomes (wins & losses)."""
        journal_path = Path("reports/live_trade_journal.csv")
        if not journal_path.exists():
            return

        import csv
        loaded_contexts: List[TradeContext] = []
        try:
            with open(journal_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        pnl = float(row.get("pnl", 0.0))
                        breakdown_str = row.get("score_breakdown", "")
                        
                        # Parse breakdown string (e.g. "of:69.8;liq:75.0;ms:62.5;vol:32.0;session:80.0;news:50.0")
                        bdict = {}
                        if breakdown_str:
                            for item in breakdown_str.split(";"):
                                if ":" in item:
                                    k, v = item.split(":", 1)
                                    try:
                                        bdict[k.strip()] = float(v.strip())
                                    except ValueError:
                                        pass

                        ts_str = row.get("timestamp", "")
                        hour = 12
                        if ts_str:
                            try:
                                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                hour = dt.hour
                            except Exception:
                                pass

                        ctx = TradeContext(
                            trade_id=row.get("symbol", "trade") + "_" + ts_str[:19],
                            direction=row.get("direction", "LONG"),
                            entry_time=ts_str,
                            of_score=bdict.get("of", 50.0),
                            liq_score=bdict.get("liq", 50.0),
                            ms_score=bdict.get("ms", 50.0),
                            vol_score=bdict.get("vol", 50.0),
                            session_score=bdict.get("session", 50.0),
                            news_score=bdict.get("news", 50.0),
                            spread_ratio=min(5.0, float(row.get("spread_pts", 1.0))),
                            atr_pct=min(1.0, float(row.get("atr", 0.1))),
                            hour_of_day=hour,
                            realized_pnl=pnl,
                            win=pnl > 0,
                        )
                        loaded_contexts.append(ctx)
                    except Exception:
                        continue

            if loaded_contexts:
                self._history = loaded_contexts
                if len(self._history) >= 5:
                    self._retrain()
                logger.info(
                    f"[ML MEMORY] Loaded {len(self._history)} historical trade journals "
                    f"(Win Rate: {self.win_rate():.1f}%). Model continuously updated!"
                )
        except Exception as e:
            logger.warning(f"Failed to load journal history into ML layer: {e}")

    def summary_dict(self) -> Dict:
        return {
            "enabled":    self._enabled,
            "trained":    self._model._trained,
            "n_history":  len(self._history),
            "win_rate":   round(self.win_rate(), 1),
            "importances": self.feature_importances(),
            "min_samples": self._min_samples,
        }
