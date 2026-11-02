"""Measure the accuracy vs response-time trade-off between the two model kinds.

Usage:
    python scripts/benchmark_models.py              # print a markdown table
    python scripts/benchmark_models.py --out docs/benchmark.md

For each training-set size, both models are trained on identical synthetic data
with an identical split, so the metrics are directly comparable.
Latency is measured on the fitted pipeline: single-row (what happens when staff
add one appointment) and a 200-row batch (a bulk daily upload).
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ml.features import encode  # noqa: E402
from app.ml.model import train_model  # noqa: E402
from app.ml.synthetic import simulate  # noqa: E402

SIZES = (2_000, 6_000, 20_000)
KINDS = ("logistic", "gbm")
SEED = 42


def median_ms(fn, repeats: int) -> float:
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def run() -> str:
    rows = []
    oracle = {}
    for n in SIZES:
        feats, labels, prob = simulate(n, SEED)
        weights = np.ones(len(labels))
        X = encode(feats)
        oracle[n] = roc_auc_score(labels, prob)
        for kind in KINDS:
            trained = train_model(kind, feats, labels, weights, SEED, n, 0)
            pipe = trained.pipeline
            single = median_ms(lambda: pipe.predict_proba(X[:1]), 60)
            batch = median_ms(lambda: pipe.predict_proba(X[:200]), 30)
            m = trained.info.metrics
            rows.append((n, kind, m["auc"], m["brier"], m["f1"], m["recall"], trained.info.train_seconds, single, batch))

    lines = [
        "| Training rows | Model | AUC | Brier | F1 | Recall | Train (s) | 1-row predict (ms) | 200-row predict (ms) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for n, kind, auc, brier, f1, rec, train_s, single, batch in rows:
        lines.append(f"| {n:,} | {kind} | {auc:.3f} | {brier:.3f} | {f1:.3f} | {rec:.3f} | {train_s:.2f} | {single:.2f} | {batch:.2f} |")
    lines += [
        "",
        "AUC / Brier / F1 / Recall are measured on a held-out 20% test split of the synthetic data. "
        "F1 and Recall use the threshold chosen on a separate validation split.",
        "",
        "Reference only (not reachable by any model): scoring with the simulator's true probabilities, which depend on "
        "each patient's hidden propensity, gives AUC "
        + ", ".join(f"{oracle[n]:.3f} at {n:,} rows" for n in SIZES) + ".",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="write the markdown table to this file")
    args = ap.parse_args()
    table = run()
    print(table)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(table + "\n", encoding="utf-8")
