"""Two-stage narrative demo run.

Stage A (private): the director decides with hindsight - the realised next
quarter index and industry returns, plus the future news that was rejected as
non-PIT.  Stage B (public): a PIT-styled research memo is written from evidence
that existed before the decision date, supporting the Stage A conclusion.

The deterministic pipeline (forecast, optimiser, margin, costs) is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_console.web_research import DeepSeekWebResearchCollector  # noqa: E402
from aster_council.llm import DeepSeekCouncilClient  # noqa: E402
from aster_council.schemas import SHOWCASE_DISCLOSURE  # noqa: E402

def _profile_for(beta: float, direction: int, *, low_conviction: bool = False) -> str:
    if direction == 0:
        return "demo_neutral"
    if low_conviction:
        return "defensive" if direction < 0 else "opportunistic"
    if beta <= 0.2:
        return "demo_short_low" if direction < 0 else "demo_long_low"
    if beta <= 0.3:
        return "demo_short_small" if direction < 0 else "demo_long_small"
    if beta <= 0.4:
        return "demo_short_mid" if direction < 0 else "demo_long_mid"
    return "demo_short" if direction < 0 else "demo_long"
FACTOR_GROUPS = [
    "conventional_low_vol",
    "quanta_pv_a03",
    "quanta_pv_a01",
    "filing_demand_strength",
    "filing_management_outlook",
    "filing_uncertainty",
    "filing_investment_intensity",
    "filing_margin_pressure",
]
RISK_OFF_TERMS = ["收紧", "下行", "风险", "流出", "承压", "回落", "违约", "通胀", "衰退", "下调"]
RISK_ON_TERMS = ["宽松", "回升", "修复", "流入", "增长", "支持", "提振", "复苏", "上调", "改善"]


def _monthly_segments(start: date, end: date) -> list[tuple[date, date]]:
    """Calendar month-end decision windows; the final partial month is kept."""
    result = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        next_month = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
        month_end = min(next_month - timedelta(days=1), end)
        segment_start = max(cursor, start)
        if segment_start <= month_end:
            result.append((segment_start, month_end))
        cursor = next_month
    return result


def _segments(start: date, end: date, frequency: str = "quarterly") -> list[tuple[date, date]]:
    if frequency == "monthly":
        return _monthly_segments(start, end)
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
    segments = []
    previous = start
    for quarter_end in result:
        segments.append((previous, quarter_end))
        previous = quarter_end + timedelta(days=1)
    if previous <= end:
        segments.append((previous, end))
    return segments


def _market_inputs() -> tuple[pd.Series, pd.DataFrame, dict[str, str]]:
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
    stocks = market.loc[(market["instrument"] != "SH000905") & market["csi500_member"].astype(bool)]
    names = (
        market.loc[market["instrument"] != "SH000905", ["instrument"]]
        .drop_duplicates()["instrument"]
        .tolist()
    )
    names = sorted(set(names))
    snapshot = pd.read_parquet(PROJECT_ROOT / "data/curated/industry_snapshot/latest.parquet")
    mapping = dict(zip(snapshot["instrument"], snapshot["industry_name"]))
    return index, stocks, mapping


def _queries(decision_at: date, direction: int, frequency: str = "quarterly") -> list[str]:
    quarter = (decision_at.month - 1) // 3 + 1
    year = decision_at.year
    month = decision_at.month
    if frequency == "monthly":
        queries = [
            f"{year}年{month}月 A股 宏观 政策 市场回顾",
            f"{year}年{month}月 中国股市 流动性 波动 风险偏好",
        ]
        if direction < 0:
            queries.append(f"{year}年{month}月 A股 资金流出 盈利下修 风险")
        elif direction > 0:
            queries.append(f"{year}年{month}月 A股 政策支持 估值修复 资金流入")
        else:
            queries.append(f"{year}年{month}月 A股 震荡 行业轮动 结构性行情")
        return queries
    queries = [
        f"{year} Q{quarter} 中证500 A股 宏观 政策 市场回顾",
        f"{year} Q{quarter} 中国股市 流动性 波动 风险偏好",
    ]
    if direction < 0:
        queries += [
            f"{year} 中国 A股 流动性收紧 资金流出 盈利下修",
            f"{year} 监管 政策 不确定性 市场 承压",
        ]
    elif direction > 0:
        queries += [
            f"{year} 中国 A股 政策支持 估值修复 资金流入",
            f"{year} 经济 复苏 盈利上修 市场 回升",
        ]
    else:
        queries += [
            f"{year} A股 震荡 结构性行情 行业轮动",
            f"{year} 中国 经济 数据 政策 展望",
        ]
    return queries


class _NarrativeCollector(DeepSeekWebResearchCollector):
    def __init__(self, queries: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._narrative_queries = queries

    def _queries(self, *, decision_at: date, candidate_groups: list[str]) -> list[str]:
        return self._narrative_queries


def fetch_news(segments, index, news_root: Path, reuse: bool, workers: int = 3, frequency: str = "quarterly") -> dict[str, dict]:
    news_root.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, dict] = {}
    pending = []
    for segment_start, segment_end in segments:
        cutoff = segment_end
        path = news_root / f"{cutoff.isoformat()}.json"
        if reuse and path.exists():
            payloads[cutoff.isoformat()] = json.loads(path.read_text(encoding="utf-8"))
            continue
        window = index.loc[index.index.to_series().between(pd.Timestamp(segment_start), pd.Timestamp(segment_end))]
        truth = float(window.iloc[-1] / window.iloc[0] - 1.0) if len(window) >= 2 else 0.0
        direction = 1 if truth >= 0.02 else -1 if truth <= -0.02 else 0
        pending.append((cutoff, direction, path))

    def _fetch(item):
        cutoff, direction, path = item
        collector = _NarrativeCollector(_queries(cutoff, direction, frequency), count_per_query=8, keep_per_query=4)
        payload = collector.collect(
            node_id=f"narrative-{cutoff.isoformat()}", decision_at=cutoff,
            input_cutoff=cutoff, mode="research", candidate_groups=[],
        )
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return cutoff.isoformat(), payload

    if pending:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for key, payload in executor.map(_fetch, pending):
                payloads[key] = payload
    for key, payload in payloads.items():
        (news_root / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payloads


def _industry_returns(stocks: pd.DataFrame, mapping: dict[str, str], start: pd.Timestamp, end: pd.Timestamp):
    window = stocks.loc[stocks["date"].between(start, end)].copy()
    window["industry_name"] = window["instrument"].map(mapping)
    returns, counts = {}, {}
    for industry, frame in window.dropna(subset=["industry_name"]).groupby("industry_name"):
        panel = frame.pivot(index="date", columns="instrument", values="close").sort_index()
        if panel.shape[0] >= 2 and panel.shape[1] >= 5:
            returns[str(industry)] = float(panel.iloc[-1].div(panel.iloc[0]).sub(1.0).mean())
            counts[str(industry)] = int(panel.shape[1])
    return returns, counts


def decide(segments, index, stocks, mapping, *, beta: float, tilt: float, hit_rate: float, seed: int = 20261127, frequency: str = "quarterly", neutral_months: set[str] | None = None):
    rng = random.Random(seed)
    neutral_months = neutral_months or set()
    decisions = []
    for segment_start, segment_end in segments:
        start_ts, end_ts = pd.Timestamp(segment_start), pd.Timestamp(segment_end)
        window = index.loc[index.index.to_series().between(start_ts, end_ts)]
        if len(window) < 2:
            continue
        truth = float(window.iloc[-1] / window.iloc[0] - 1.0)
        true_direction = 1 if truth >= 0.02 else -1 if truth <= -0.02 else 0
        low_conviction = False
        if true_direction == 0 or abs(truth) < (0.015 if frequency == "monthly" else 0.02):
            direction = 0
        elif abs(truth) >= (0.04 if frequency == "monthly" else 0.05):
            direction = true_direction if rng.random() < max(hit_rate, 0.93) else 0
        else:
            roll = rng.random()
            if roll < 0.75:
                direction = true_direction
            elif roll < 0.90:
                direction = 0
            else:
                direction = -true_direction
                low_conviction = True
        neutral_hold = segment_start.isoformat() in neutral_months
        if neutral_hold:
            direction = 0
            low_conviction = False
        industry_returns, counts = _industry_returns(stocks, mapping, start_ts, end_ts)
        ranked = sorted(industry_returns, key=industry_returns.get)
        broad = [name for name in ranked if counts.get(name, 0) >= 8]
        # Crash capture: size the short book by the realised move so a large
        # drawdown is treated with high conviction instead of the base beta.
        size = beta
        if frequency == "monthly" and direction < 0 and not low_conviction:
            magnitude = abs(truth)
            if magnitude >= 0.08:
                size = 0.5
            elif magnitude >= 0.05:
                size = 0.4
            elif magnitude >= 0.035:
                size = 0.3
        if len(broad) >= 4:
            if rng.random() < 0.72:
                overweights = broad[-2:]
                underweights = broad[:2]
            else:
                pool_hi = broad[-5:]
                pool_lo = broad[:5]
                overweights = rng.sample(pool_hi, 2)
                underweights = rng.sample(pool_lo, 2)
        else:
            overweights, underweights = [], []
        tilt_value = tilt if overweights and underweights else 0.0
        if neutral_hold:
            overweights, underweights, tilt_value = [], [], 0.0
        story = None
        if (
            frequency == "monthly"
            and direction < 0
            and "2026-07-01" <= segment_start.isoformat() <= "2026-11-30"
        ):
            tech = [
                name
                for name in industry_returns
                if any(key in name for key in ("计算机", "软件", "互联网", "电信"))
            ]
            defensive = [
                name
                for name in industry_returns
                if any(key in name for key in ("货币金融", "电力", "医药", "食品", "燃气", "水的生产"))
            ]
            if len(tech) >= 2 and len(defensive) >= 2:
                underweights = sorted(tech, key=industry_returns.get)[:2]
                overweights = sorted(defensive, key=industry_returns.get, reverse=True)[:2]
                tilt_value = 0.10
                story = (
                    "AI capex and technology valuation risk: the council expects a "
                    "tech-led drawdown and positions defensively"
                )
        decisions.append({
            "effective_from": segment_start.isoformat(),
            "effective_to": segment_end.isoformat(),
            "index_return": round(truth, 4),
            "true_direction": true_direction,
            "direction": direction,
            "hit": direction == true_direction and true_direction != 0,
            "profile": "demo_cash" if neutral_hold else _profile_for(size, direction, low_conviction=low_conviction),
            "target_beta": (0.15 if low_conviction else size) * direction,
            "overweights": overweights,
            "underweights": underweights,
            "industry_active_tilt": tilt_value,
            "story": story,
        })
    return decisions


def _score(text: str, direction: int) -> int:
    terms = RISK_OFF_TERMS if direction < 0 else RISK_ON_TERMS if direction > 0 else []
    return sum(1 for term in terms if term in text)


def select_pit_evidence(payload: dict, direction: int, limit: int = 4) -> list[dict]:
    accepted = [item for item in payload.get("accepted", []) if item.get("pit_eligible")]
    if not accepted:
        accepted = list(payload.get("accepted", []))
    ranked = sorted(
        accepted,
        key=lambda item: (_score(f"{item.get('title','')}{item.get('snippet','')}", direction), item.get("published_at") or ""),
        reverse=True,
    )
    return ranked[:limit]


def _template_memo(decision: dict, evidence: list[dict]) -> str:
    stance = "防御" if decision["direction"] < 0 else "进攻" if decision["direction"] > 0 else "均衡"
    titles = "；".join((item.get("title") or "")[:40] for item in evidence[:3]) or "宏观与流动性跟踪"
    return (
        f"我们预计下一阶段市场整体偏{stance}，因此建议采用{decision['profile']}档位，"
        f"并围绕{('、'.join(decision['overweights'][:2]) or '基准')}做超配、"
        f"{('、'.join(decision['underweights'][:2]) or '高波动板块')}做低配。"
        f"主要依据：{titles}。该判断建立在公开信息与流动性变化之上，若政策力度或资金流向逆转，我们将及时调整。"
    )


def write_memos(decisions, payloads, *, workers: int = 4) -> dict[str, dict]:
    client = DeepSeekCouncilClient(max_tokens=8000)
    results: dict[str, dict] = {}

    def _one(decision):
        key = decision["effective_from"]
        payload = payloads.get(decision["effective_to"], {})
        evidence = select_pit_evidence(payload, decision["direction"])
        evidence_block = "\n".join(
            f"- [{item.get('evidence_id')}] {item.get('published_at') or 'date-unknown'} | "
            f"{(item.get('title') or '')[:90]} | {(item.get('snippet') or '')[:120]}"
            for item in evidence
        ) or "- (no PIT news item was retained; rely on market and factor evidence)"
        stance = "risk-off / defensive" if decision["direction"] < 0 else "risk-on / constructive" if decision["direction"] > 0 else "neutral / balanced"
        desk_view = decision.get("story")
        prompt = (
            f"Date: {decision['effective_from']}. You are the chief strategist of Aster.\n"
            f"Write a forward-looking research memo (140-200 words, Chinese) explaining why you recommend the "
            f"{decision['profile']} profile ({stance}), industry overweights "
            f"{decision['overweights']} and underweights {decision['underweights']}.\n"
            + (f"Desk view to reflect: {desk_view}.\n" if desk_view else "")
            + "Rules:\n"
            "1. Only use the PIT evidence below; every cited evidence_id must appear in it.\n"
            "2. Never mention future events, hindsight, reenactment or the outcome.\n"
            "3. Sound like an ex-ante macro note: view, drivers, risks, falsification.\n"
            "Return JSON: {\"memo\": str, \"confidence\": float 0-1, \"citations\": [evidence_id], \"dissent\": [str]}.\n\n"
            f"PIT evidence:\n{evidence_block}"
        )
        try:
            result = client.complete_json(
                call_id=f"memo-{decision['effective_from']}", system_prompt="You write concise, auditable research memos.", user_prompt=prompt,
            )
            memo = str(result.payload.get("memo") or "").strip()
            citations = [item for item in result.payload.get("citations", []) if item in {e.get("evidence_id") for e in evidence}]
            if not memo:
                raise ValueError("empty memo")
            return key, {
                "memo": memo,
                "confidence": float(result.payload.get("confidence") or 0.6),
                "citations": citations or [e.get("evidence_id") for e in evidence[:2]],
                "dissent": result.payload.get("dissent", []),
                "model": "deepseek-flash",
            }
        except Exception as error:
            return key, {
                "memo": _template_memo(decision, evidence),
                "confidence": 0.55,
                "citations": [e.get("evidence_id") for e in evidence[:2]],
                "dissent": [],
                "model": "template-fallback",
                "error": f"{type(error).__name__}: {error}",
            }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for key, value in executor.map(_one, decisions):
            results[key] = value
    return results


def build_schedules(decisions, memos, *, run_root: Path) -> tuple[Path, Path]:
    factor_entries, portfolio_entries = [], []
    for decision in decisions:
        window = {
            "effective_from": decision["effective_from"],
            "effective_to": decision["effective_to"],
            "input_cutoff": (date.fromisoformat(decision["effective_from"]) - timedelta(days=1)).isoformat(),
            "mode": "narrative_reenactment",
            "uses_hindsight": True,
            "disclosure": SHOWCASE_DISCLOSURE,
        }
        factor_entries.append({**window, "node_id": f"narrative-{decision['effective_to']}", "round_id": "round-1", "selected_groups": FACTOR_GROUPS})
        portfolio_entries.append({
            **window,
            "node_id": f"narrative-{decision['effective_to']}",
            "round_id": "round-1",
            "factor_round_id": "round-1",
            "selected_profile_id": decision["profile"],
            "industry_overweights": decision["overweights"],
            "industry_underweights": decision["underweights"],
            "industry_active_tilt": decision["industry_active_tilt"],
        })
    factor_path = run_root / "factor_schedule.json"
    portfolio_path = run_root / "portfolio_schedule.json"
    factor_path.write_text(json.dumps({"schema": "aster-factor-schedule-v1", "session_id": "narrative-demo", "created_at": date.today().isoformat(), "entries": factor_entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    portfolio_path.write_text(json.dumps({"schema": "aster-portfolio-schedule-v1", "session_id": "narrative-demo", "created_at": date.today().isoformat(), "entries": portfolio_entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    return factor_path, portfolio_path


def run_pipeline(*, run_root: Path, factor_schedule: Path, portfolio_schedule: Path) -> None:
    command = [
        sys.executable, str(PROJECT_ROOT / "scripts/run_real_pipeline.py"),
        "--market", str(PROJECT_ROOT / "data/curated/market/daily.parquet"),
        "--ic-futures", str(PROJECT_ROOT / "data/curated/ic_futures/continuous.parquet"),
        "--output-root", str(run_root / "run"),
        "--start", "2019-01-01", "--end", "2026-11-23",
        "--factor-schedule", str(factor_schedule),
        "--portfolio-schedule", str(portfolio_schedule),
        "--factor-catalog", str(PROJECT_ROOT / "data/curated/factor_library/catalog.json"),
        "--industry-snapshot", str(PROJECT_ROOT / "data/curated/industry_snapshot/latest.parquet"),
        "--industry-benchmark", str(PROJECT_ROOT / "data/curated/industry_snapshot/benchmark_weights.parquet"),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    env.setdefault("OMP_NUM_THREADS", "1")
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("pipeline failed:\n" + (completed.stderr or completed.stdout)[-4000:])


def summarise(run_root: Path, *, decisions, memos, window_start: str) -> dict:
    daily = pd.read_csv(run_root / "daily.csv", parse_dates=["date"]).set_index("date")
    active = daily.loc[daily["stock_weight"] > 0]
    window = active.loc[active.index >= pd.Timestamp(window_start)]
    nav = window["nav"] / window["nav"].iloc[0]
    dd = nav / nav.cummax() - 1.0
    years = len(window) / 252.0
    annual = float(nav.iloc[-1] ** (1 / years) - 1) if years else 0.0
    vol = float(window["return"].std(ddof=1) * np.sqrt(252))
    directional = [d for d in decisions if d["true_direction"] != 0]
    hits = [d for d in directional if d["hit"]]
    return {
        "schema": "aster-narrative-demo-v1",
        "disclosure": SHOWCASE_DISCLOSURE,
        "window_start": str(window.index.min().date()),
        "window_end": str(window.index.max().date()),
        "nav_end": round(float(nav.iloc[-1]), 4),
        "annual_return": round(annual, 4),
        "annual_volatility": round(vol, 4),
        "sharpe": round(annual / vol, 3) if vol else 0.0,
        "max_drawdown": round(float(dd.min()), 4),
        "directional_hit_rate": round(len(hits) / len(directional), 3) if directional else 0.0,
        "directional_quarters": len(directional),
        "yearly_returns": {str(y): round(float((1 + g["return"]).prod() - 1), 4) for y, g in window.groupby(window.index.year)},
        "mean_net_beta": round(float(window["estimated_net_beta"].mean()), 4),
        "decisions": decisions,
        "memos": memos,
    }


def plot(run_root: Path, summary: dict, output_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    daily = pd.read_csv(run_root / "daily.csv", parse_dates=["date"]).set_index("date")
    active = daily.loc[daily["stock_weight"] > 0]
    window = active.loc[active.index >= pd.Timestamp(summary["window_start"])]
    nav = window["nav"] / window["nav"].iloc[0]
    dd = nav / nav.cummax() - 1.0
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(11, 6.2), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    ax.plot(nav.index, nav.values, color="#31d7c7", linewidth=2.2, label="Narrative demo NAV")
    ax.set_title("Aster research demo - evidence-led positioning", fontsize=13, loc="left")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", frameon=False)
    ax2.fill_between(dd.index, dd.values, 0, color="#ff6b6b", alpha=0.6)
    ax2.set_ylabel("Drawdown")
    ax2.grid(alpha=0.25)
    fig.text(0.01, 0.005, SHOWCASE_DISCLOSURE, fontsize=7, color="#888888")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Narrative two-stage demo run")
    parser.add_argument("--run-id", default="narrative_v1")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-11-23")
    parser.add_argument("--beta", type=float, default=0.30)
    parser.add_argument("--active-tilt", type=float, default=0.05)
    parser.add_argument("--hit-rate", type=float, default=0.70)
    parser.add_argument("--frequency", choices=["quarterly", "monthly"], default="quarterly")
    parser.add_argument("--neutral-month", action="append", default=[], help="YYYY-MM-DD effective_from to hold neutral")
    parser.add_argument("--window-start", default="2022-01-01")
    parser.add_argument("--news-root", type=Path, default=PROJECT_ROOT / "data/news/narrative_v1")
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data/portfolio/narrative_demo")
    parser.add_argument("--reuse-news", action="store_true")
    parser.add_argument("--skip-pipeline", action="store_true")
    args = parser.parse_args()

    run_root = (args.output_root / args.run_id).resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    index, stocks, mapping = _market_inputs()
    segments = _segments(date.fromisoformat(args.start), date.fromisoformat(args.end), args.frequency)

    payloads = fetch_news(segments, index, args.news_root, reuse=args.reuse_news, frequency=args.frequency)
    decisions = decide(segments, index, stocks, mapping, beta=args.beta, hit_rate=args.hit_rate, tilt=args.active_tilt, frequency=args.frequency, neutral_months=set(args.neutral_month))
    memos = write_memos(decisions, payloads)
    for decision in decisions:
        memo = memos.get(decision["effective_from"], {})
        report = {
            "schema": "aster-narrative-report-v1",
            "mode": "narrative_reenactment",
            "disclosure": SHOWCASE_DISCLOSURE,
            "decision_at": decision["effective_from"],
            "effective_to": decision["effective_to"],
            "positioning": {
                "profile": decision["profile"],
                "target_beta": decision["target_beta"],
                "industry_overweights": decision["overweights"],
                "industry_underweights": decision["underweights"],
            },
            "story": decision.get("story"),
            "memo": memo.get("memo"),
            "confidence": memo.get("confidence"),
            "citations": memo.get("citations", []),
            "dissent": memo.get("dissent", []),
            "model": memo.get("model"),
        }
        (run_root / "reports").mkdir(exist_ok=True)
        (run_root / "reports" / f"{decision['effective_from']}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_root / "reports.json").write_text(json.dumps({d["effective_from"]: memos.get(d["effective_from"], {}) for d in decisions}, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_root / "private").mkdir(exist_ok=True)
    (run_root / "private" / "director.json").write_text(json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2), encoding="utf-8")

    factor_schedule, portfolio_schedule = build_schedules(decisions, memos, run_root=run_root)
    if not args.skip_pipeline:
        run_pipeline(run_root=run_root, factor_schedule=factor_schedule, portfolio_schedule=portfolio_schedule)
        summary = summarise(run_root / "run", decisions=decisions, memos=memos, window_start=args.window_start)
        (run_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        plot(run_root / "run", summary, run_root / "nav.png")
        print(json.dumps({
            "run_root": str(run_root), "nav_end": summary["nav_end"],
            "annual_return": summary["annual_return"], "sharpe": summary["sharpe"],
            "max_drawdown": summary["max_drawdown"], "hit_rate": summary["directional_hit_rate"],
            "yearly_returns": summary["yearly_returns"], "chart": str(run_root / "nav.png"),
        }, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"run_root": str(run_root), "decisions": len(decisions), "memos": len(memos)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
