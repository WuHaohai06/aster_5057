# Backtest performance optimisation v1

The optimisation keeps the research model and portfolio constraints unchanged.
It removes repeated dataframe construction from the walk-forward forecaster and
vectorises pairwise market-beta estimation in the risk model.

## Changes

- Standardised feature panels are materialised as aligned NumPy arrays once per run.
- Each walk-forward window now uses array slices instead of rebuilding pandas
  `MultiIndex` objects with `stack` and `concat` on every signal date.
- Active feature schedules still select a different feature subset by signal date.
- Pairwise stock/benchmark covariance is calculated for every stock in one vectorised pass.
- Shrunk covariance matrices are symmetrised with a tiny diagonal floor instead of
  repeating a full 505-by-505 eigen decomposition at every rebalance.
- Clarabel remains the primary portfolio solver. OSQP was benchmarked but rejected
  because it was slower and introduced a larger numerical difference.

## Local benchmark

| Workload | Before | After | Result difference |
| --- | ---: | ---: | ---: |
| 700 sessions, 300 stocks, 8 factors, 28 Ridge forecasts | 19.49 s | 1.39 s | same model and windows |
| Real-data pipeline, 2019-01-01 to 2022-02-28, 45 forecasts/optimisations | about 80 s | 37.99 s | annual return delta 1.52e-10 |

The wall-clock figures are machine-specific. The relevant acceptance condition is
that replay metrics remain equal up to floating-point tail noise while the same
PIT inputs, training windows, constraints and solver are used.

