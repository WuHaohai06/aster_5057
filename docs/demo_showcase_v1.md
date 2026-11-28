# Showcase demo run v1 (beta + industry hindsight)

This is the pitch/demo path, not the research path.  Every quarter's beta
profile and industry tilt is chosen from the **realised** next-quarter CSI 500
and industry returns, and the run keeps the fixed showcase disclosure.  The
deterministic pipeline (walk-forward Ridge forecast, optimiser, margin, costs)
is unchanged.

## What it produces

`data/portfolio/demo_showcase/demo_showcase_v1/`

```text
factor_schedule.json      8 showcase factor groups per quarter
portfolio_schedule.json   demo profile + 2 overweights / 2 underweights
director_plan.json        per-quarter hindsight: index return, profile, industries
run/                      the pipeline outputs (daily.csv, metrics.json, ...)
summary.json              demo-window statistics
nav.png                   NAV + drawdown chart with disclosure footnote
```

Demo window 2022-01-04 → 2026-11-23:

| Metric | Demo showcase | Research baseline (0800) | CSI 500 |
|---|---:|---:|---:|
| NAV | **2.523** | 0.917 | 0.833 |
| Annualised return | **+21.8%** | -1.8% | -3.8% |
| Volatility | 12.9% | 8.6% | — |
| Sharpe | **1.69** | -0.21 | — |
| Max drawdown | **-13.8%** | -27.1% | -39.5% |

Yearly: 2022 +33.3%, 2023 +20.6%, 2024 +24.9%, 2025 +15.0%, 2026 +9.1%.

## How to rerun

```powershell
python scripts/build_demo_showcase_run.py `
  --run-id demo_showcase_v1 `
  --beta 0.50 --active-tilt 0.10 --window-start 2022-01-01
```

`--replot-only` regenerates `summary.json` and `nav.png` from an existing run.

## Engine changes behind it

- `PortfolioProfile.target_beta` range widened from ±0.20 to ±0.90.
- New showcase-only profiles `demo_short` (-0.50), `demo_neutral` (0), and
  `demo_long` (+0.50), returned by `demo_profiles()` / `approved_profiles()` and
  excluded from research Council packets.
- Industry active tilt approved levels extended to 0.15/0.20; the optimiser cap
  raised to 20%.  The first demo run uses 0.10 because 20% is infeasible for
  narrow industries (a benchmark weight below the tilt cannot be underweighted
  in a long-only stock book).
- Showcase portfolio deliberation is now deterministic: the replay applies the
  director's profile and industries directly instead of asking an LLM, so a
  failed call can no longer silently degrade the quarter to a neutral policy.

## Caveat

The run is a **retrospective course-demo reenactment**: hindsight picks the
profile and industries after seeing the quarter's outcome.  The `nav.png`
footnote and `summary.json` carry the disclosure; any slide or page that shows
this curve must keep it.  It is not evidence of live strategy performance.
