"""Build a disclosed showcase reenactment run with real beta/industry hindsight.

This is the demo path, not the research path: every quarter's profile and
industry tilt is selected from the *realised* next-quarter index and industry
returns, and the run keeps the fixed showcase disclosure.  The deterministic
pipeline (forecast, optimiser, costs, margin) is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_council.schemas import SHOWCASE_DISCLOSURE  # noqa: E402

DEFAULT_DEMO_GROUPS = [
    "conventional_low_vol",
    "quanta_pv_a03",
    "quanta_pv_a01",
    "filing_demand_strength",
    "filing_management_outlook",
    "filing_uncertainty",
    "filing_investment_intensity",
    "filing_margin_pressure",
]
PROFILE_BY_BETA = {
    -0.50: "demo_short",
    -0.40: "demo_short_mid",
    -0.30: "demo_short_small",
    0.0: "demo_neutral",
    0.30: "demo_long_small",
    0.40: "demo_long_mid",
    0.50: "demo_long",
}


def _quarter_ends(start: date, end: date) -> list[date]:
    result = []
    year, month = start.year, ((start.month - 1) // 3) * 3 + 1
    while True:
        end_month = month + 3
        end_year = year
        if end_month > 12:
            end_month -= 12
            end_year += 1
        quarter_end = date(end_year, end_month, 1) - timedelta(days=1)
        if quarter_end > end:
            break
        if quarter_end >= start:
            result.append(quarter_end)
        month += 3
        if month > 12:
            month -= 12
            year += 1
    return result


def _segments(start: date, end: date) -> list[tuple[date, date]]:
    ends = _quarter_ends(start, end)
    segments = []
    previous = start
    for quarter_end in ends:
        segments.append((previous, quarter_end))
        previous = quarter_end + timedelta(days=1)
    if previous <= end:
        segments.append((previous, end))
    return segments


def _showcase_groups() -> list[str]:
    packets = sorted(
        (PROJECT_ROOT / "data/council/showcase_runs").glob("*/packet.json"),
        key=lambda path: path.stat().st_mtime,
    )
    for path in reversed(packets):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        directive = payload.get("showcase_directive") or {}
        groups = directive.get("target_selected_groups")
        if groups:
            return list(groups)
    return DEFAULT_DEMO_GROUPS


def _industry_returns(
    stocks: pd.DataFrame, mapping: dict[str, str], start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, float]:
    window = stocks.loc[stocks["date"].between(start, end)].copy()
    window["industry_name"] = window["instrument"].map(mapping)
    returns: dict[str, float] = {}
    for industry, frame in window.dropna(subset=["industry_name"]).groupby("industry_name"):
        panel = frame.pivot(index="date", columns="instrument", values="close").sort_index()
        if panel.shape[0] >= 2 and panel.shape[1] >= 5:
            returns[str(industry)] = float(panel.iloc[-1].div(panel.iloc[0]).sub(1.0).mean())
    return returns


def build_schedules(
    *, start: str, end: str, output_root: Path, beta: float, active_tilt: float
) -> tuple[Path, Path, list[dict]]:
    market = pd.read_parquet(
        PROJECT_ROOT / "data/curated/market/daily.parquet",
        columns=["date", "instrument", "close", "csi500_member"],
    )
    market["date"] = pd.to_datetime(market["date"]).dt.normalize()
    index = (
        market.loc[market["instrument"] == "SH000905", ["date", "close"]]
        .drop_duplicates("date", keep="last")
        .set_index("date")["close"]
        .sort_index()
    )
    stocks = market.loc[
        (market["instrument"] != "SH000905") & market["csi500_member"].astype(bool)
    ]
    snapshot = pd.read_parquet(PROJECT_ROOT / "data/curated/industry_snapshot/latest.parquet")
    mapping = dict(zip(snapshot["instrument"], snapshot["industry_name"]))
    groups = _showcase_groups()

    segments = _segments(date.fromisoformat(start), date.fromisoformat(end))
    factor_entries, portfolio_entries, plan = [], [], []
    for segment_start, segment_end in segments:
        start_ts = pd.Timestamp(segment_start)
        end_ts = pd.Timestamp(segment_end)
        window = index.loc[index.index.to_series().between(start_ts, end_ts)]
        if len(window) < 2:
            continue
        future_return = float(window.iloc[-1] / window.iloc[0] - 1.0)
        beta_target = beta if future_return >= 0.03 else -beta if future_return <= -0.03 else 0.0
        if beta_target not in PROFILE_BY_BETA:
            raise ValueError(f"no demo profile for beta={beta_target}; use 0.30 or 0.50")
        profile_id = PROFILE_BY_BETA[beta_target]
        industry = _industry_returns(stocks, mapping, start_ts, end_ts)
        ranked = sorted(industry, key=industry.get)
        overweights = ranked[-2:] if len(ranked) >= 4 else []
        underweights = ranked[:2] if len(ranked) >= 4 else []
        effective = {
            "effective_from": segment_start.isoformat(),
            "effective_to": segment_end.isoformat(),
            "input_cutoff": (segment_start - timedelta(days=1)).isoformat(),
            "mode": "showcase_reenactment",
            "uses_hindsight": True,
            "disclosure": SHOWCASE_DISCLOSURE,
        }
        factor_entries.append({**effective, "node_id": f"demo-{segment_end.isoformat()}", "round_id": "round-1", "selected_groups": groups})
        portfolio_entries.append({
            **effective,
            "node_id": f"demo-{segment_end.isoformat()}",
            "round_id": "round-1",
            "factor_round_id": "round-1",
            "selected_profile_id": profile_id,
            "industry_overweights": overweights,
            "industry_underweights": underweights,
            "industry_active_tilt": active_tilt if overweights and underweights else 0.0,
        })
        plan.append({
            "effective_from": segment_start.isoformat(),
            "effective_to": segment_end.isoformat(),
            "index_return": round(future_return, 4),
            "profile": profile_id,
            "target_beta": beta_target,
            "overweights": overweights,
            "underweights": underweights,
        })

    output_root.mkdir(parents=True, exist_ok=True)
    factor_path = output_root / "factor_schedule.json"
    portfolio_path = output_root / "portfolio_schedule.json"
    factor_path.write_text(json.dumps({
        "schema": "aster-factor-schedule-v1",
        "session_id": "demo-showcase",
        "created_at": date.today().isoformat(),
        "entries": factor_entries,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    portfolio_path.write_text(json.dumps({
        "schema": "aster-portfolio-schedule-v1",
        "session_id": "demo-showcase",
        "created_at": date.today().isoformat(),
        "entries": portfolio_entries,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "director_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return factor_path, portfolio_path, plan


def run_pipeline(*, output_root: Path, factor_schedule: Path, portfolio_schedule: Path) -> None:
    python = sys.executable
    command = [
        python,
        str(PROJECT_ROOT / "scripts/run_real_pipeline.py"),
        "--market", str(PROJECT_ROOT / "data/curated/market/daily.parquet"),
        "--ic-futures", str(PROJECT_ROOT / "data/curated/ic_futures/continuous.parquet"),
        "--output-root", str(output_root / "run"),
        "--start", "2019-01-01",
        "--end", "2026-11-23",
        "--factor-schedule", str(factor_schedule),
        "--portfolio-schedule", str(portfolio_schedule),
        "--factor-catalog", str(PROJECT_ROOT / "data/curated/factor_library/catalog.json"),
        "--industry-snapshot", str(PROJECT_ROOT / "data/curated/industry_snapshot/latest.parquet"),
        "--industry-benchmark", str(PROJECT_ROOT / "data/curated/industry_snapshot/benchmark_weights.parquet"),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    env.setdefault("OMP_NUM_THREADS", "1")
    completed = subprocess.run(
        command, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("demo pipeline failed:\n" + (completed.stderr or completed.stdout)[-4000:])


def summarise(
    run_root: Path, *, plan: list[dict], beta: float, tilt: float, window_start: str = "2021-03-04"
) -> dict:
    daily = pd.read_csv(run_root / "daily.csv", parse_dates=["date"]).set_index("date")
    active = daily.loc[daily["stock_weight"] > 0]
    window = active.loc[active.index >= pd.Timestamp(window_start)]
    nav = window["nav"]
    normalised = nav / nav.iloc[0]
    drawdown = normalised / normalised.cummax() - 1.0
    years = len(window) / 252.0
    annual_return = float(normalised.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else 0.0
    volatility = float(window["return"].std(ddof=1) * (252 ** 0.5))
    summary = {
        "schema": "aster-demo-showcase-run-v1",
        "disclosure": SHOWCASE_DISCLOSURE,
        "target_beta": beta,
        "industry_active_tilt": tilt,
        "window_start": str(window.index.min().date()),
        "window_end": str(window.index.max().date()),
        "nav_end": round(float(normalised.iloc[-1]), 4),
        "annual_return": round(annual_return, 4),
        "annual_volatility": round(volatility, 4),
        "sharpe": round(annual_return / volatility, 3) if volatility else 0.0,
        "max_drawdown": round(float(drawdown.min()), 4),
        "reported_full_period_metrics": json.loads((run_root / "metrics.json").read_text(encoding="utf-8")),
        "yearly_returns": {
            str(year): round(float((1 + group["return"]).prod() - 1), 4)
            for year, group in window.groupby(window.index.year)
        },
        "mean_net_beta": round(float(window["estimated_net_beta"].mean()), 4),
        "mean_gross_exposure": round(float(window["gross_exposure"].mean()), 4),
        "quarters": plan,
    }
    (run_root.parent / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def plot(run_root: Path, summary: dict, output_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    daily = pd.read_csv(run_root / "daily.csv", parse_dates=["date"]).set_index("date")
    active = daily.loc[daily["stock_weight"] > 0]
    window = active.loc[active.index >= pd.Timestamp(summary["window_start"])]
    nav = window["nav"] / window["nav"].iloc[0]
    drawdown = nav / nav.cummax() - 1.0
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(11, 6.2), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax.plot(nav.index, nav.values, color="#31d7c7", linewidth=2.2, label="Showcase NAV")
    ax.set_title(
        "Aster showcase reenactment - hindsight beta & industry selection",
        fontsize=13, loc="left",
    )
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", frameon=False)
    ax2.fill_between(drawdown.index, drawdown.values, 0, color="#ff6b6b", alpha=0.6)
    ax2.set_ylabel("Drawdown")
    ax2.grid(alpha=0.25)
    fig.text(
        0.01, 0.005,
        "Retrospective course-demo reenactment: hindsight selected the showcased scenario; not a live or point-in-time prediction.",
        fontsize=7, color="#888888",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the disclosed showcase beta/industry demo run")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-11-23")
    parser.add_argument("--beta", type=float, default=0.50)
    parser.add_argument("--active-tilt", type=float, default=0.20)
    parser.add_argument("--run-id", default="demo_showcase_v1")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data/portfolio/demo_showcase")
    parser.add_argument("--window-start", default="2022-01-01")
    parser.add_argument("--reuse-schedules", action="store_true")
    parser.add_argument("--replot-only", action="store_true")
    args = parser.parse_args()

    run_root = (args.output_root / args.run_id).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    if args.replot_only:
        plan = json.loads((run_root / "director_plan.json").read_text(encoding="utf-8"))
        summary = summarise(
            run_root / "run", plan=plan, beta=args.beta, tilt=args.active_tilt,
            window_start=args.window_start,
        )
        plot(run_root / "run", summary, run_root / "nav.png")
        print(json.dumps({
            "run_root": str(run_root), "window_start": summary["window_start"],
            "nav_end": summary["nav_end"], "annual_return": summary["annual_return"],
            "sharpe": summary["sharpe"], "max_drawdown": summary["max_drawdown"],
            "yearly_returns": summary["yearly_returns"], "chart": str(run_root / "nav.png"),
        }, ensure_ascii=False, indent=2))
        return
    if args.reuse_schedules:
        factor_schedule = run_root / "factor_schedule.json"
        portfolio_schedule = run_root / "portfolio_schedule.json"
        plan = json.loads((run_root / "director_plan.json").read_text(encoding="utf-8"))
    else:
        factor_schedule, portfolio_schedule, plan = build_schedules(
            start=args.start, end=args.end, output_root=run_root,
            beta=args.beta, active_tilt=args.active_tilt,
        )
    run_pipeline(
        output_root=run_root, factor_schedule=factor_schedule, portfolio_schedule=portfolio_schedule
    )
    summary = summarise(run_root / "run", plan=plan, beta=args.beta, tilt=args.active_tilt, window_start=args.window_start)
    plot(run_root / "run", summary, run_root / "nav.png")
    print(json.dumps({
        "run_root": str(run_root),
        "nav_end": summary["nav_end"],
        "max_drawdown": summary["max_drawdown"],
        "yearly_returns": summary["yearly_returns"],
        "chart": str(run_root / "nav.png"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
