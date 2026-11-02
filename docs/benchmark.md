| Training rows | Model | AUC | Brier | F1 | Recall | Train (s) | 1-row predict (ms) | 200-row predict (ms) |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2,000 | logistic | 0.660 | 0.150 | 0.413 | 0.457 | 0.19 | 0.28 | 0.32 |
| 2,000 | gbm | 0.602 | 0.168 | 0.366 | 0.605 | 0.35 | 1.94 | 3.36 |
| 6,000 | logistic | 0.656 | 0.160 | 0.416 | 0.672 | 0.20 | 0.26 | 0.24 |
| 6,000 | gbm | 0.646 | 0.162 | 0.394 | 0.743 | 0.38 | 1.92 | 2.96 |
| 20,000 | logistic | 0.666 | 0.158 | 0.405 | 0.703 | 0.20 | 0.27 | 0.29 |
| 20,000 | gbm | 0.665 | 0.159 | 0.414 | 0.684 | 0.32 | 0.71 | 1.02 |

AUC / Brier / F1 / Recall are measured on a held-out 20% test split of the synthetic data. F1 and Recall use the threshold chosen on a separate validation split.

Reference only (not reachable by any model): scoring with the simulator's true probabilities, which depend on each patient's hidden propensity, gives AUC 0.785 at 2,000 rows, 0.782 at 6,000 rows, 0.776 at 20,000 rows.
