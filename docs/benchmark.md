| Training rows | Model | AUC | Brier | F1 | Recall | Train (s) | 1-row predict (ms) | 200-row predict (ms) |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2,000 | logistic | 0.660 | 0.150 | 0.413 | 0.457 | 0.10 | 0.22 | 0.23 |
| 2,000 | gbm | 0.602 | 0.168 | 0.359 | 0.518 | 0.27 | 1.85 | 3.09 |
| 6,000 | logistic | 0.656 | 0.160 | 0.401 | 0.589 | 0.11 | 0.22 | 0.23 |
| 6,000 | gbm | 0.646 | 0.162 | 0.399 | 0.585 | 0.37 | 1.99 | 3.40 |
| 20,000 | logistic | 0.666 | 0.158 | 0.410 | 0.561 | 0.17 | 0.24 | 0.31 |
| 20,000 | gbm | 0.665 | 0.159 | 0.413 | 0.571 | 0.29 | 0.50 | 0.88 |

AUC / Brier / F1 / Recall are measured on a held-out 20% test split of the synthetic data. F1 and Recall use the threshold chosen on a separate validation split.

Reference only (not reachable by any model): scoring with the simulator's true probabilities, which depend on each patient's hidden propensity, gives AUC 0.785 at 2,000 rows, 0.782 at 6,000 rows, 0.776 at 20,000 rows.
