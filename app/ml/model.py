"""Model training and serving.

Two model families are supported so the accuracy / response-time trade-off is
a real, measurable choice rather than a claim:

* ``logistic`` - standardised logistic regression. Fast, smooth, well calibrated,
  easy to explain per feature.
* ``gbm``      - histogram gradient boosting. Captures interactions (for example
  "new patient booked far ahead") at the cost of slower training and prediction.

Training data is the synthetic baseline plus every reconciled appointment in the
database (up-weighted, because it is real). The model is held in memory and
swapped atomically on retrain; nothing is unpickled from disk.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.config import Settings
from app.db import AppointmentRepository
from app.ml.features import AppointmentFeatures, FEATURE_NAMES, encode, smoothed_rate, training_set_from_rows
from app.ml.synthetic import generate

log = logging.getLogger("meditrack.model")

FALLBACK_VERSION = "heuristic-fallback"
FALLBACK_THRESHOLD = 0.35


@dataclass(frozen=True)
class Prediction:
    risk: float
    level: str  # low | medium | high
    flagged: bool


@dataclass(frozen=True)
class ModelInfo:
    version: str
    kind: str
    trained_at: str
    n_synthetic: int
    n_real: int
    threshold: float
    base_rate: float
    metrics: dict[str, float]
    train_seconds: float
    single_predict_ms: float
    top_features: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TrainedModel:
    pipeline: Pipeline
    info: ModelInfo


def risk_level(risk: float, threshold: float) -> str:
    if risk >= threshold:
        return "high"
    if risk >= threshold / 2:
        return "medium"
    return "low"


def build_pipeline(kind: str, seed: int) -> Pipeline:
    if kind == "logistic":
        return Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, C=1.0)),
        ])
    if kind == "gbm":
        return Pipeline([
            ("clf", HistGradientBoostingClassifier(
                max_depth=4, max_iter=250, learning_rate=0.06, l2_regularization=1.0, random_state=seed,
            )),
        ])
    raise ValueError(f"unknown model kind: {kind!r}")


def _best_threshold(y_true: np.ndarray, p: np.ndarray) -> float:
    """Threshold maximising F1 on validation data (the 0.5 default misses most no-shows at a ~20% base rate)."""
    best_t, best_f1 = 0.3, -1.0
    for t in np.linspace(0.05, 0.80, 76):
        f1 = f1_score(y_true, p >= t, zero_division=0)
        if f1 > best_f1:
            best_t, best_f1 = float(t), f1
    return round(best_t, 2)


def train_model(
    kind: str,
    feats: Sequence[AppointmentFeatures],
    labels: np.ndarray,
    weights: np.ndarray,
    seed: int,
    n_synthetic: int,
    n_real: int,
) -> TrainedModel:
    """Fit on 60% of the data, choose the threshold on 20%, report metrics on the final 20%."""
    started = time.perf_counter()
    X, y = encode(feats), np.asarray(labels)
    idx = np.arange(len(y))
    rest, test = train_test_split(idx, test_size=0.2, stratify=y, random_state=seed)
    train, val = train_test_split(rest, test_size=0.25, stratify=y[rest], random_state=seed)

    pipe = build_pipeline(kind, seed)
    pipe.fit(X[train], y[train], clf__sample_weight=weights[train])

    threshold = _best_threshold(y[val], pipe.predict_proba(X[val])[:, 1])
    p_test = pipe.predict_proba(X[test])[:, 1]
    pred = p_test >= threshold
    metrics = {
        "auc": float(roc_auc_score(y[test], p_test)),
        "brier": float(brier_score_loss(y[test], p_test)),
        "accuracy": float(accuracy_score(y[test], pred)),
        "precision": float(precision_score(y[test], pred, zero_division=0)),
        "recall": float(recall_score(y[test], pred, zero_division=0)),
        "f1": float(f1_score(y[test], pred, zero_division=0)),
        "test_rows": int(len(test)),
    }
    train_seconds = time.perf_counter() - started

    # Median single-row latency, the number that matters when staff add an appointment.
    one = X[:1]
    timings = []
    for _ in range(25):
        t0 = time.perf_counter()
        pipe.predict_proba(one)
        timings.append((time.perf_counter() - t0) * 1000)
    single_ms = float(np.median(timings))

    now = datetime.now(timezone.utc)
    info = ModelInfo(
        version=f"{kind}-{now:%Y%m%d%H%M%S}-n{len(y)}",
        kind=kind,
        trained_at=now.isoformat(timespec="seconds"),
        n_synthetic=n_synthetic,
        n_real=n_real,
        threshold=threshold,
        base_rate=float(y.mean()),
        metrics={k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()},
        train_seconds=round(train_seconds, 3),
        single_predict_ms=round(single_ms, 3),
        top_features=_top_features(pipe, kind),
    )
    return TrainedModel(pipe, info)


def _top_features(pipe: Pipeline, kind: str) -> list[dict]:
    """Human-readable drivers. Only linear models expose signed coefficients directly."""
    if kind != "logistic":
        return []
    coefs = pipe.named_steps["clf"].coef_[0]
    order = np.argsort(-np.abs(coefs))[:6]
    return [{"feature": FEATURE_NAMES[i], "weight": round(float(coefs[i]), 3)} for i in order]


class ModelService:
    """Owns the live model; thread-safe swap on retrain."""

    def __init__(self, settings: Settings, repo: AppointmentRepository):
        self.settings = settings
        self.repo = repo
        self._model: TrainedModel | None = None
        self._lock = threading.Lock()

    @property
    def info(self) -> ModelInfo:
        if self._model is None:
            raise RuntimeError("model has not been trained yet")
        return self._model.info

    def train(self) -> ModelInfo:
        s = self.settings
        syn_feats, syn_labels = generate(s.synthetic_rows, s.random_seed)
        real_feats, real_labels = training_set_from_rows(self.repo.reconciled_for_training())
        feats = list(syn_feats) + list(real_feats)
        labels = np.concatenate([syn_labels, real_labels]) if len(real_labels) else syn_labels
        weights = np.concatenate([np.ones(len(syn_feats)), np.full(len(real_feats), s.real_sample_weight)])
        trained = train_model(s.model_kind, feats, labels, weights, s.random_seed, len(syn_feats), len(real_feats))
        with self._lock:
            self._model = trained
        log.info("trained %s (auc=%.3f, threshold=%.2f, real rows=%d)", trained.info.version,
                 trained.info.metrics["auc"], trained.info.threshold, len(real_feats))
        return trained.info

    def predict(self, feats: Sequence[AppointmentFeatures]) -> tuple[list[Prediction], str]:
        """Score a batch. Never raises: on model failure a transparent heuristic is used instead."""
        if not feats:
            return [], self._model.info.version if self._model else FALLBACK_VERSION
        model = self._model
        try:
            if model is None:
                raise RuntimeError("model not trained")
            risks = model.pipeline.predict_proba(encode(feats))[:, 1]
            threshold, version = model.info.threshold, model.info.version
        except Exception:
            log.exception("model prediction failed; using heuristic fallback")
            risks = np.array([smoothed_rate(f.prior_visits, f.prior_no_shows) for f in feats])
            threshold, version = FALLBACK_THRESHOLD, FALLBACK_VERSION
        out = []
        for r in risks:
            r = float(np.clip(r, 0.0, 1.0))
            out.append(Prediction(round(r, 4), risk_level(r, threshold), r >= threshold))
        return out, version

    def rescore_scheduled(self) -> int:
        """Re-predict appointments that haven't happened yet (after a retrain)."""
        rows = self.repo.scheduled_rows()
        if not rows:
            return 0
        keys = {r["patient_key"] for r in rows}
        history = self.repo.history_for(keys)
        feats = []
        from datetime import date
        from app.ml.features import features_for_new
        for r in rows:
            feats.append(features_for_new(
                appointment_date=date.fromisoformat(r["appointment_date"]),
                hour=int(r["appointment_time"][:2]),
                appointment_type=r["appointment_type"],
                lead_days=r["lead_days"],
                history=history[r["patient_key"]],
            ))
        preds, version = self.predict(feats)
        for r, p in zip(rows, preds):
            self.repo.update_prediction(r["id"], p.risk, p.level, p.flagged, version)
        return len(rows)
