# Reported results

Run `python scripts/reproduce_results.py --output reproduced` to recompute these values from the included measurements.

## Lifecycle interaction modeling

| Configuration | FragBench TP/FP/FN | F1 | DroidBench match/excess/miss | F1 |
|---|---|---:|---|---:|
| Native | 6/1/23 | 0.333 | 103/19/71 | 0.696 |
| HSM | 7/1/22 | 0.378 | 103/19/71 | 0.696 |
| HSM+Tx | 13/1/16 | 0.605 | 103/19/71 | 0.696 |
| HSM+Tx+Alias | 24/1/5 | 0.889 | 103/21/71 | 0.691 |
| Full | 24/0/5 | 0.906 | 103/21/71 | 0.691 |

The FragBench panel contains 36 cases. The DroidBench panel contains 179 labelled cases with trusted outputs in all five configurations. The two additional DroidBench count excesses are explained in `DATA.md`.

Among 12 paired selected applications, ten have identical exact source/sink key sets. Openmaps and SmartTurn account for 17 elements of the raw symmetric difference. Openmaps contributes four generated-receiver renaming pairs; SmartTurn has different write expressions and report multiplicities.

## Parameter reduction

| Panel | Lifecycle | PerArg | PerType | Rules | Total reduction | Mean per APK | Median per APK | Reduced APKs |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Main | Fixed | 29,414 | 8,077 | 29,261 | 0.52% | 1.98% | 0.00% | 23/210 |
| Main | HSM | 37,179 | 7,684 | 36,983 | 0.53% | 2.24% | 0.00% | 25/210 |
| Expanded | Fixed | 219,329 | 50,256 | 217,412 | 0.87% | 14.05% | 13.85% | 63/64 |
| Expanded | HSM | 369,343 | 43,389 | 366,023 | 0.90% | 15.07% | 14.82% | 63/64 |

Total reductions weight applications by their baseline parameter inventory. Means and medians weight positive-baseline APKs equally. Large inventories with low reduction rates limit aggregate savings, even when most fragment-rich applications shrink.

## Analysis cost

The cost data contain 20 applications, five configurations, and five repetitions per configuration. Application-level median wall-time ratios to Fixed/PerArg are 0.996 for Fixed/PerType, 1.005 for Fixed/Rules, 1.013 for HSM/PerArg, and 1.025 for HSM/Rules. All four Holm-adjusted wall-time probabilities are 1.

Eight comparisons are significant after correction over 68 comparisons: 17 metrics × four alternatives. The application-level symbolic-path ratios are 0.793, 0.999, 1.034, and 1.039, respectively. The distinction between absolute configuration medians and medians of paired ratios is preserved in the recomputed output.
