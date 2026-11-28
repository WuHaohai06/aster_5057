import { useEffect, useMemo, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";
import {
  Activity,
  Archive,
  BarChart3,
  BookOpenText,
  Bot,
  Boxes,
  BrainCircuit,
  Check,
  ChevronRight,
  CircleAlert,
  Database,
  FileSearch,
  Filter,
  FlaskConical,
  Gauge,
  GitBranch,
  Layers3,
  Menu,
  Network,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";
import { loadSnapshot, subscribeToSnapshotEvents } from "./data";
import type { Factor, Snapshot, ViewId } from "./types";
import { actionLabel, factorCount, getLang, localized, localizedList, setLang, tr, type Lang } from "./i18n";
import InteractiveReplay from "./InteractiveReplay";

const navigation: Array<{ id: ViewId; label: string; icon: typeof Activity }> = [
  { id: "overview", label: "Command Center", icon: Gauge },
  { id: "factors", label: "Factor Library", icon: FlaskConical },
  { id: "council", label: "AI Council", icon: BrainCircuit },
  { id: "filings", label: "Filing Intelligence", icon: FileSearch },
  { id: "portfolio", label: "Portfolio Replay", icon: TrendingUp },
];

const roleNames: Record<string, string> = {
  market_regime_reviewer: "Market Regime",
  factor_evidence_reviewer: "Factor Evidence",
  risk_data_reviewer: "Risk & Data",
};

function percent(value: number | null | undefined, digits = 1) {
  return value == null || Number.isNaN(value) ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function decimal(value: number | null | undefined, digits = 3) {
  return value == null || Number.isNaN(value) ? "—" : value.toFixed(digits);
}

function compact(value: number | null | undefined) {
  if (value == null) return "—";
  return Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function humanDate(value: string | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function StatusPill({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`status-pill status-${tone}`}>{children}</span>;
}

function Panel({ title, kicker, action, children, className = "" }: {
  title: string;
  kicker?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header">
        <div>
          {kicker && <span className="eyebrow">{kicker}</span>}
          <h2>{title}</h2>
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

function MetricCard({ label, value, detail, tone = "cyan" }: {
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <div className={`metric-card metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function Pipeline({ snapshot, navigate }: { snapshot: Snapshot; navigate: (view: ViewId) => void }) {
  return (
    <div className="pipeline-grid">
      {snapshot.pipeline.map((stage, index) => (
        <button className={`pipeline-stage state-${stage.state}`} key={stage.id} onClick={() => navigate(stage.view)}>
          <span className="pipeline-index">{String(index + 1).padStart(2, "0")}</span>
          <span className="pipeline-copy">
            <strong>{tr(stage.label)}</strong>
            <small>{stage.detail}</small>
          </span>
          <ChevronRight size={17} />
        </button>
      ))}
    </div>
  );
}

function jobProgress(job: Record<string, unknown>) {
  const pairs = [
    ["completed_artifacts", "total_artifacts"],
    ["score_completed", "score_total"],
    ["completed", "total"],
    ["instrument_index", "instruments"],
  ];
  for (const [doneKey, totalKey] of pairs) {
    const done = Number(job[doneKey]);
    const total = Number(job[totalKey]);
    if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
      return { done, total, ratio: Math.min(1, Math.max(0, done / total)) };
    }
  }
  return null;
}

function JobMonitor({ jobs }: { jobs: Snapshot["jobs"] }) {
  return (
    <div className="job-grid">
      {jobs.map((job) => {
        const progress = jobProgress(job);
        const state = String(job.state ?? "pending");
        const updated = typeof job.updated_at === "string" ? job.updated_at : undefined;
        const stage = typeof job.stage === "string" ? job.stage : undefined;
        return <article className={`job-card job-${state}`} key={job.name}>
          <div><span className="job-state-dot" /><StatusPill tone={state === "complete" ? "good" : state === "running" ? "live" : state === "pending" ? "neutral" : "warn"}>{state}</StatusPill></div>
          <strong>{job.name}</strong>
          {progress ? <><div className="job-progress"><i style={{ width: `${progress.ratio * 100}%` }} /></div><small>{progress.done.toLocaleString()} / {progress.total.toLocaleString()}{stage ? ` · ${stage}` : ""}</small></> : <small>{stage ?? "No numeric progress reported"}</small>}
          <time>{updated ? humanDate(updated) : "Not started"}</time>
        </article>;
      })}
    </div>
  );
}

function Overview({ snapshot, navigate, openFactor }: {
  snapshot: Snapshot;
  navigate: (view: ViewId) => void;
  openFactor: (factor: Factor) => void;
}) {
  const validated = snapshot.factors.filter((factor) => factor.status !== "candidate").length;
  const quanta = snapshot.factors.filter((factor) => factor.origin === "quantaalpha");
  const topFactors = [...snapshot.factors]
    .filter((factor) => factor.metrics.rankIc != null)
    .sort((a, b) => (b.metrics.rankIc ?? -99) - (a.metrics.rankIc ?? -99))
    .slice(0, 5);
  const filingDone = snapshot.filings.score_completed ?? 0;
  const filingTotal = snapshot.filings.score_total ?? 0;
  const portfolio = snapshot.portfolio.runs[0];

  return (
    <div className="view-stack">
      <section className="hero-grid">
        <div className="hero-copy">
          <div className="hero-kicker"><Sparkles size={15} /> AI-NATIVE RESEARCH OPERATING SYSTEM</div>
          <h1>{tr("From raw evidence")}<br />{tr("to bounded decisions.")}</h1>
          <p>
            {tr("CSI500 data, AI factor mining, mechanism review, portfolio optimisation and backtesting, in one auditable research surface.")}
          </p>
          <div className="hero-actions">
            <button className="primary-button" onClick={() => navigate("council")}>{tr("Open Council")}</button>
            <button className="ghost-button" onClick={() => navigate("factors")}>{tr("Explore factors")}</button>
          </div>
        </div>
        <div className="signal-orbit" aria-label={tr("Research system summary")}>
          <div className="orbit-ring ring-one" />
          <div className="orbit-ring ring-two" />
          <div className="orbit-center"><BrainCircuit size={34} /><strong>ASTER</strong><span>RESEARCH CORE</span></div>
          <span className="orbit-node node-data"><Database size={16} /> DATA</span>
          <span className="orbit-node node-alpha"><FlaskConical size={16} /> ALPHA</span>
          <span className="orbit-node node-council"><Bot size={16} /> COUNCIL</span>
          <span className="orbit-node node-portfolio"><BarChart3 size={16} /> REPLAY</span>
        </div>
      </section>

      <div className="metric-grid">
        <MetricCard label={tr("FACTOR CATALOG")} value={String(snapshot.factors.length)} detail={`${validated} ${tr("passed lifecycle validation")}`} />
        <MetricCard label={tr("AI-MINED")} value={String(quanta.length)} detail={tr("QuantaAlpha candidates")} tone="violet" />
        <MetricCard label={tr("FILING INTELLIGENCE")} value={filingTotal ? percent(filingDone / filingTotal) : "—"} detail={`${filingDone} / ${filingTotal} ${tr("reports scored")}`} tone="green" />
        <MetricCard label={tr("LATEST REPLAY")} value={portfolio ? percent(portfolio.metrics.annual_return) : "—"} detail={tr("annualised return · disclosed run")} tone="amber" />
      </div>

      <Panel title={tr("Research pipeline")} kicker={tr("Live system map")} action={<StatusPill tone="live">{tr("WORKSPACE LIVE")}</StatusPill>}>
        <Pipeline snapshot={snapshot} navigate={navigate} />
      </Panel>

      <Panel title={tr("Background jobs")} kicker={tr("Live sanitised status")} action={<StatusPill tone="live">{tr("AUTO REFRESH")}</StatusPill>}>
        <JobMonitor jobs={snapshot.jobs} />
      </Panel>

      <div className="two-column">
        <Panel title={tr("Signal leaderboard")} kicker={tr("Canonical diagnostics")} action={<button className="text-button" onClick={() => navigate("factors")}>{tr("View library")}</button>}>
          <div className="leaderboard">
            {topFactors.map((factor, index) => (
              <button key={factor.id} onClick={() => openFactor(factor)}>
                <span className="rank">{index + 1}</span>
                <span className="factor-ident"><strong>{factor.name}</strong><small>{factor.group}</small></span>
                <span className="metric-pair"><small>{tr("RANK IC")}</small><strong>{decimal(factor.metrics.rankIc, 4)}</strong></span>
                <span className="metric-pair"><small>{tr("ICIR")}</small><strong>{decimal(factor.metrics.rankIcIr)}</strong></span>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title={tr("Latest Council state")} kicker={tr("Historical accepted artifact")} action={<StatusPill tone={snapshot.factorCouncil.decision.fallbackUsed ? "warn" : "good"}>{snapshot.factorCouncil.decision.status.toUpperCase()}</StatusPill>}>
          <div className="council-summary">
            <div className="selected-strip">
              {snapshot.factorCouncil.decision.selectedGroups.map((group) => <span key={group}><Check size={14} />{group}</span>)}
            </div>
            <p>{snapshot.factorCouncil.decision.rationale}</p>
            <button className="text-button" onClick={() => navigate("council")}>{tr("Inspect ballots and evidence")}</button>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function FactorLibrary({ snapshot, openFactor }: { snapshot: Snapshot; openFactor: (factor: Factor) => void }) {
  const [query, setQuery] = useState("");
  const [origin, setOrigin] = useState("all");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState<"name" | "rankIc" | "coverage">("rankIc");
  const origins = [...new Set(snapshot.factors.map((factor) => factor.origin))];
  const filtered = useMemo(() => {
    const lowered = query.toLowerCase();
    return [...snapshot.factors]
      .filter((factor) => !lowered || `${factor.name} ${factor.id} ${factor.group} ${factor.hypothesis} ${factor.hypothesisZh ?? ""} ${factor.descriptionZh ?? ""}`.toLowerCase().includes(lowered))
      .filter((factor) => origin === "all" || factor.origin === origin)
      .filter((factor) => status === "all" || factor.status === status)
      .sort((a, b) => {
        if (sort === "name") return a.name.localeCompare(b.name);
        if (sort === "coverage") return (b.metrics.coverage ?? -1) - (a.metrics.coverage ?? -1);
        return (b.metrics.rankIc ?? -99) - (a.metrics.rankIc ?? -99);
      });
  }, [snapshot.factors, query, origin, status, sort]);

  return (
    <div className="view-stack">
      <div className="page-heading">
        <div><span className="eyebrow">{tr("UNIFIED FACTOR CATALOG")}</span><h1>{tr("Factor Library")}</h1><p>{tr("One research object, from economic hypothesis and canonical diagnostics to the Council lifecycle.")}</p></div>
        <div className="heading-stats"><strong>{filtered.length}</strong><span>{tr("visible")} / {snapshot.factors.length} {tr("total")}</span></div>
      </div>
      <Panel title={tr("Catalog explorer")} kicker={tr("Search · filter · inspect")}>
        <div className="filter-bar">
          <label className="search-field"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tr("Search factor, group or hypothesis")} /></label>
          <label className="select-field"><Filter size={15} /><select value={origin} onChange={(event) => setOrigin(event.target.value)}><option value="all">{tr("All origins")}</option>{origins.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label className="select-field"><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">{tr("All lifecycle states")}</option><option value="candidate">{tr("Candidate")}</option><option value="validated">{tr("Validated")}</option><option value="demo_selected">{tr("Demo selected")}</option></select></label>
          <label className="select-field"><select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="rankIc">{tr("Sort: Rank IC")}</option><option value="coverage">{tr("Sort: Coverage")}</option><option value="name">{tr("Sort: Name")}</option></select></label>
        </div>
        <div className="factor-table-wrap">
          <table className="factor-table">
            <thead><tr><th>{tr("Factor")}</th><th>{tr("Origin")}</th><th>{tr("Lifecycle")}</th><th>{tr("Rank IC")}</th><th>{tr("ICIR")}</th><th>{tr("Coverage")}</th><th>{tr("Turnover")}</th><th>{tr("Redundancy")}</th><th /></tr></thead>
            <tbody>{filtered.map((factor) => (
              <tr key={factor.id} onClick={() => openFactor(factor)}>
                <td><strong>{factor.name}</strong><small>{factor.id} · {factor.group}</small></td>
                <td><span className="origin-tag">{factor.origin}</span></td>
                <td><StatusPill tone={factor.status === "candidate" ? "neutral" : factor.status === "demo_selected" ? "violet" : "good"}>{tr(factor.status.replace("_", " "))}</StatusPill></td>
                <td className={(factor.metrics.rankIc ?? 0) >= 0 ? "positive" : "negative"}>{decimal(factor.metrics.rankIc, 4)}</td>
                <td>{decimal(factor.metrics.rankIcIr)}</td>
                <td>{percent(factor.metrics.coverage)}</td>
                <td>{percent(factor.metrics.turnover)}</td>
                <td>{percent(factor.metrics.correlation)}</td>
                <td><ChevronRight size={16} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function FactorDrawer({ factor, close }: { factor: Factor; close: () => void }) {
  const yearly = Object.entries(factor.yearlyRankIc);
  const maxAbs = Math.max(0.01, ...yearly.map(([, value]) => Math.abs(value)));
  return (
    <div className="drawer-backdrop" onMouseDown={close}>
      <aside className="factor-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <button className="icon-button drawer-close" onClick={close} aria-label={tr("Close factor details")}><X size={20} /></button>
        <span className="eyebrow">FACTOR DOSSIER · {factor.origin}</span>
        <h2>{factor.name}</h2>
        <p className="drawer-description">{localized(factor.description, factor.descriptionZh)}</p>
        <div className="drawer-tags"><StatusPill tone={factor.status === "candidate" ? "neutral" : "good"}>{factor.status}</StatusPill>{factor.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
        <div className="drawer-metrics">
          <div><small>{tr("RANK IC")}</small><strong>{decimal(factor.metrics.rankIc, 4)}</strong></div>
          <div><small>{tr("ICIR")}</small><strong>{decimal(factor.metrics.rankIcIr)}</strong></div>
          <div><small>{tr("COVERAGE")}</small><strong>{percent(factor.metrics.coverage)}</strong></div>
          <div><small>{tr("TURNOVER")}</small><strong>{percent(factor.metrics.turnover)}</strong></div>
        </div>
        <section className="dossier-section"><h3><BookOpenText size={17} />{tr("Economic hypothesis")}</h3><p>{localized(factor.hypothesis, factor.hypothesisZh) || "No structured hypothesis has been registered."}</p></section>
        <section className="dossier-section"><h3><GitBranch size={17} />{tr("Mechanism")}</h3><p>{localized(factor.mechanism, factor.mechanismZh) || "Mechanism review is pending."}</p><div className="direction-callout"><span>{tr("EXPECTED DIRECTION")}</span>{localized(factor.expectedDirection, factor.expectedDirectionZh) || "Not specified"}</div></section>
        <section className="dossier-section"><h3><Archive size={17} />{tr("Signal construction")}</h3><code>{factor.expression}</code></section>
        <section className="dossier-section"><h3><ShieldCheck size={17} />{tr("Falsification criteria")}</h3><ul>{localizedList(factor.falsificationCriteria, factor.falsificationCriteriaZh).length ? localizedList(factor.falsificationCriteria, factor.falsificationCriteriaZh).map((item) => <li key={item}>{item}</li>) : <li>{tr("No explicit criterion registered.")}</li>}</ul></section>
        {yearly.length > 0 && <section className="dossier-section"><h3><BarChart3 size={17} />{tr("Yearly Rank IC")}</h3><div className="year-bars">{yearly.map(([year, value]) => <div key={year}><span>{year}</span><div><i className={value >= 0 ? "bar-positive" : "bar-negative"} style={{ width: `${Math.abs(value) / maxAbs * 100}%` }} /></div><strong>{value.toFixed(3)}</strong></div>)}</div></section>}
        <section className="lineage-box"><div><small>{tr("CATALOG ID")}</small><strong>{factor.id}</strong></div><div><small>{tr("ARTIFACT")}</small><strong>{factor.artifact.digest}</strong></div><div><small>{tr("PIT")}</small><strong>{factor.pitCompliant ? "COMPLIANT" : "REVIEW"}</strong></div></section>
      </aside>
    </div>
  );
}

function Council({ snapshot }: { snapshot: Snapshot }) {
  const { packet, decision, ballots, mechanismReviewPending } = snapshot.factorCouncil;
  const [selectedGroup, setSelectedGroup] = useState(packet.groups[0]?.id ?? "");
  const group = packet.groups.find((item) => item.id === selectedGroup);
  return (
    <div className="view-stack">
      <div className="page-heading">
        <div><span className="eyebrow">{tr("BOUNDED MULTI-AGENT GOVERNANCE")}</span><h1>{tr("AI Council Chamber")}</h1><p>{tr("Three independent reviewers submit evidence-based votes; the Chair forms the final factor-group selection inside code constraints.")}</p></div>
        <div className="heading-badges"><StatusPill tone="good">{tr("PACKET")} {packet.version || "V2"}</StatusPill><StatusPill tone={decision.fallbackUsed ? "warn" : "good"}>{tr(decision.fallbackUsed ? "FALLBACK USED" : "ACCEPTED")}</StatusPill></div>
      </div>
      {mechanismReviewPending && <div className="notice-banner"><CircleAlert size={18} /><div><strong>{tr("Mechanism review has been upgraded, but this page shows a historical Council run.")}</strong><span>{tr("The new packet carries mechanism fields; per-group mechanism ratings appear after the Council is re-run.")}</span></div></div>}
      <div className="council-layout">
        <Panel title={tr("Candidate groups")} kicker={`${tr("Input cutoff")} · ${packet.inputCutoff}`} className="candidate-panel">
          <div className="candidate-list">{packet.groups.map((item) => {
            const selected = decision.selectedGroups.includes(item.id);
            return <button key={item.id} className={`${selectedGroup === item.id ? "active" : ""} ${selected ? "chosen" : ""}`} onClick={() => setSelectedGroup(item.id)}><span><strong>{item.id}</strong><small>{factorCount(item.factorIds.length)}</small></span><span className="candidate-score">{decimal(item.rankIc, 4)}</span></button>;
          })}</div>
        </Panel>
        <Panel title={group?.id ?? "Group evidence"} kicker={tr("Mechanism + deterministic diagnostics")} className="group-evidence">
          {group && <>
            <div className="evidence-metrics"><div><small>{tr("MEDIAN RANK IC")}</small><strong>{decimal(group.rankIc, 4)}</strong></div><div><small>{tr("ICIR")}</small><strong>{decimal(group.rankIcIr)}</strong></div><div><small>{tr("TURNOVER")}</small><strong>{percent(group.turnover)}</strong></div><div><small>{tr("MAX CORR")}</small><strong>{percent(group.correlation)}</strong></div></div>
            <div className="mechanism-stack">{group.mechanisms.map((item) => <article key={item.factorId}><span>{item.factorId}</span><h3>{localized(item.hypothesis, item.hypothesisZh) || "Hypothesis not registered"}</h3><p>{localized(item.mechanism, item.mechanismZh) || "Mechanism explanation pending."}</p><small>{localized(item.expectedDirection, item.expectedDirectionZh)}</small></article>)}</div>
          </>}
        </Panel>
      </div>
      <Panel title={tr("Independent ballots")} kicker={tr("Reviewer-level audit trail")}>
        <div className="reviewer-grid">{ballots.map((ballot) => {
          const vote = ballot.votes.find((item) => item.group_id === selectedGroup);
          return <article className="reviewer-card" key={ballot.role}><div className="reviewer-title"><div className="reviewer-icon"><Bot size={18} /></div><div><strong>{tr(roleNames[ballot.role] ?? ballot.role)}</strong><small>{tr("Independent reviewer")}</small></div>{vote && <StatusPill tone={vote.action === "enable" ? "good" : vote.action === "disable" ? "bad" : "warn"}>{actionLabel(vote.action)}</StatusPill>}</div>{vote ? <><p>{localized(vote.rationale, vote.rationale_zh)}</p><div className="confidence"><span>{tr("CONFIDENCE")}</span><div><i style={{ width: `${vote.confidence * 100}%` }} /></div><strong>{percent(vote.confidence)}</strong></div>{localizedList(vote.risks, vote.risks_zh).length > 0 && <ul>{localizedList(vote.risks, vote.risks_zh).slice(0, 2).map((risk) => <li key={risk}>{risk}</li>)}</ul>}</> : <p>{tr("No historical vote for this newly eligible group.")}</p>}</article>;
        })}</div>
      </Panel>
      <Panel title={tr("Chair decision")} kicker={`${decision.decisionAt} · ${decision.promptVersion}`} action={<span className="confidence-badge">{percent(decision.confidence)} {tr("confidence")}</span>}>
        <div className="chair-decision"><div className="chair-groups"><div><small>{tr("SELECTED")}</small>{decision.selectedGroups.map((item) => <span className="selected" key={item}><Check size={13} />{item}</span>)}</div><div><small>{tr("DISABLED")}</small>{decision.disabledGroups.map((item) => <span key={item}>{item}</span>)}</div></div><p className="localized">{localized(decision.rationale, decision.rationaleZh)}</p>{decision.fallbackReason && <div className="fallback-reason"><CircleAlert size={16} /><span>{decision.fallbackReason}</span></div>}</div>
      </Panel>
    </div>
  );
}

function PerformanceChart({ curve }: { curve: Snapshot["portfolio"]["runs"][number]["curve"] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!curve.length) return <div className="empty-state">{tr("No replay curve available.")}</div>;
  const withBenchmark = curve.every((item) => typeof item.benchmarkNav === "number");
  const values = withBenchmark ? curve.flatMap((item) => [item.nav, item.benchmarkNav as number]) : curve.map((item) => item.nav);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const y = (value: number) => 250 - (value - min) / range * 210;
  const x = (index: number) => index / (curve.length - 1) * 1000;
  const points = curve.map((item, index) => `${x(index)},${y(item.nav)}`).join(" ");
  const benchmarkPoints = withBenchmark ? curve.map((item, index) => `${x(index)},${y(item.benchmarkNav as number)}`).join(" ") : "";
  const active = hover == null ? curve[curve.length - 1] : curve[hover];
  const activeX = x(hover == null ? curve.length - 1 : hover);
  const activeY = y(active.nav);
  const onMove = (event: MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setHover(Math.max(0, Math.min(curve.length - 1, Math.round((event.clientX - rect.left) / rect.width * (curve.length - 1)))));
  };
  const legend = <div style={{ display: "flex", gap: 18, fontSize: 12, color: "#8aa0b5", marginTop: 8 }}><span><i style={{ display: "inline-block", width: 18, height: 2, background: "#31d7c7", verticalAlign: "middle", marginRight: 6 }} />{tr("Aster")}</span>{withBenchmark ? <span><i style={{ display: "inline-block", width: 18, height: 2, background: "#8aa0b5", verticalAlign: "middle", marginRight: 6 }} />{tr("CSI 500")}</span> : null}</div>;
  return <div className="performance-chart"><div className="chart-readout"><span>{active.date}</span><strong>{tr("NAV")} {active.nav.toFixed(3)}</strong>{withBenchmark ? <small>CSI 500 {(active.benchmarkNav as number).toFixed(3)}</small> : null}<small>{tr("DD")} {percent(active.drawdown)}</small></div><svg viewBox="0 0 1000 280" preserveAspectRatio="none" onMouseMove={onMove} onMouseLeave={() => setHover(null)}><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#31d7c7" stopOpacity=".28" /><stop offset="100%" stopColor="#31d7c7" stopOpacity="0" /></linearGradient></defs><line x1="0" y1="250" x2="1000" y2="250" className="chart-axis" /><polygon points={`0,250 ${points} 1000,250`} fill="url(#area)" />{withBenchmark ? <polyline points={benchmarkPoints} fill="none" stroke="#8aa0b5" strokeWidth={1.6} strokeDasharray="5 4" /> : null}<polyline points={points} className="chart-line" /><line x1={activeX} x2={activeX} y1="28" y2="250" className="chart-crosshair" /><circle cx={activeX} cy={activeY} r={6} className="chart-point" /></svg>{legend}</div>;
}

function SavedPortfolio({ snapshot }: { snapshot: Snapshot }) {
  const [runId, setRunId] = useState(snapshot.portfolio.runs[0]?.id ?? "");
  const run = snapshot.portfolio.runs.find((item) => item.id === runId) ?? snapshot.portfolio.runs[0];
  if (!run) return <div className="empty-state">{tr("No portfolio replay is available.")}</div>;
  return <div className="view-stack"><div className="page-heading"><div><span className="eyebrow">{tr("DETERMINISTIC OPTIMISATION + COUNCIL PROFILE")}</span><h1>{tr("Portfolio Replay")}</h1><p>{tr("NAV, drawdown, Beta and cost come from saved replayable runs; not a representation of future performance.")}</p></div><label className="select-field run-select"><select value={runId} onChange={(event) => setRunId(event.target.value)}>{snapshot.portfolio.runs.map((item) => <option key={item.id} value={item.id}>{tr(item.label)}</option>)}</select></label></div><div className="metric-grid"><MetricCard label={tr("ANNUALISED RETURN")} value={percent(run.metrics.annual_return)} detail={tr("saved replay")} tone={run.metrics.annual_return >= 0 ? "green" : "amber"} /><MetricCard label={tr("SHARPE")} value={decimal(run.metrics.sharpe, 2)} detail={tr("realised risk-adjusted")} /><MetricCard label={tr("MAX DRAWDOWN")} value={percent(run.metrics.max_drawdown)} detail={tr("peak-to-trough")} tone="amber" /><MetricCard label={tr("MAX ABS BETA")} value={decimal(run.metrics.max_abs_estimated_beta, 3)} detail={tr("after futures hedge")} tone="violet" /></div><Panel title={tr("Equity curve")} kicker={tr("Interactive saved replay")} action={<StatusPill tone="warn">{tr("COURSE DEMO · NOT ADVICE")}</StatusPill>}><PerformanceChart curve={run.curve} /></Panel>{run.report?.memo && <Panel title={tr("Council report")} kicker={tr("Latest report")} action={<StatusPill tone="violet">{run.report.decisionAt ?? ""}</StatusPill>}><div className="narrative-card"><Network size={22} /><div><small>{run.report.profile} · β {run.report.targetBeta} · {percent(run.report.confidence)}</small><p className="localized">{localized(run.report.memoEn, run.report.memo)}</p></div></div></Panel>}<div className="two-column"><Panel title={tr("Exposure & cost")} kicker={tr("Deterministic controls")}><div className="stat-list"><div><span>{tr("Mean gross exposure")}</span><strong>{percent(run.metrics.mean_gross_exposure)}</strong></div><div><span>{tr("Total cost fraction")}</span><strong>{percent(run.metrics.total_cost_fraction)}</strong></div><div><span>{tr("Stock turnover")}</span><strong>{decimal(run.metrics.total_stock_turnover, 2)}</strong></div><div><span>{tr("Futures turnover")}</span><strong>{decimal(run.metrics.total_futures_turnover, 2)}</strong></div></div></Panel><Panel title={tr("Interpretation")} kicker={tr("What this run proves")}><div className="narrative-card"><Network size={22} /><p>{tr("This curve shows that data, forecasting, optimisation, IC hedging and portfolio replay run under one audit contract. It is not a formal conclusion on strategy efficacy.")}</p></div></Panel></div></div>;
}

function Portfolio({ snapshot }: { snapshot: Snapshot }) {
  return <div className="view-stack"><InteractiveReplay /><SavedPortfolio snapshot={snapshot} /></div>;
}

function Filings({ snapshot }: { snapshot: Snapshot }) {
  const filing = snapshot.filings;
  const score = filing.score_completed ?? 0;
  const total = filing.score_total ?? 0;
  const parsed = filing.parse_completed ?? 0;
  const documents = filing.documents_total ?? 0;
  const progress = total ? score / total : 0;
  const years = filing.years ?? [];
  const dimensions = [
    ["Management outlook", "Forward-looking strategy and operating confidence"],
    ["Demand strength", "Evidence of product and market demand"],
    ["Margin pressure", "Pricing, cost and impairment pressure"],
    ["Capex intensity", "Investment burden and expansion intensity"],
    ["Risk level", "Disclosed operating and balance-sheet risks"],
  ];
  return <div className="view-stack"><div className="page-heading"><div><span className="eyebrow">{tr("DOCUMENT → AI-FRIENDLY EVIDENCE → FACTOR ROWS")}</span><h1>{tr("Filing Intelligence")}</h1><p>{tr("Filing text is structurally parsed, citation-located and scored by DeepSeek, then converted into PIT factor records.")}</p></div><StatusPill tone={score < total ? "live" : "good"}>{tr(score < total ? "SCORING LIVE" : "COMPLETE")}</StatusPill></div><section className="filing-progress"><div className="progress-copy"><span>{filing.year_start ?? 2020}-{filing.year_end ?? 2025} {tr("ANNUAL REPORT BATCHES")}</span><strong>{percent(progress)}</strong><p>{score} / {total} {tr("scoreable reports completed")}</p></div><div className="radial-progress" style={{ "--progress": `${progress * 360}deg` } as CSSProperties}><div><FileSearch size={25} /><strong>{score}</strong><span>{tr("SCORED")}</span></div></div></section><div className="metric-grid"><MetricCard label={tr("PARSED DOCUMENTS")} value={`${parsed}/${documents}`} detail={`${filing.parse_failures ?? 0} ${tr("parse failure")}`} /><MetricCard label={tr("GENERATED FACTOR ROWS")} value={compact(filing.factor_rows)} detail={tr("five dimensions per successful report")} tone="green" /><MetricCard label={tr("TOKEN USAGE")} value={compact(filing.token_usage?.total_tokens)} detail={tr("prompt + completion")} tone="violet" /><MetricCard label={tr("OCR QUEUE")} value={String(filing.needs_ocr ?? 0)} detail={tr("documents requiring fallback")} tone="amber" /></div>{years.length > 0 && <Panel title={tr("Annual batches")} kicker={tr("2020-2025 completion ledger")}><div className="filing-years">{years.map((year) => { const done = year.score_completed ?? 0; const count = year.score_total ?? year.documents_total ?? 0; return <article key={year.year}><span>{year.year}</span><strong>{done}/{count}</strong><small>{compact(year.factor_rows)} {tr("factor rows")}</small><StatusPill tone={year.state === "complete" ? "good" : "live"}>{year.state ?? "pending"}</StatusPill></article>; })}</div></Panel>}<Panel title={tr("Financial narrative dimensions")} kicker={tr("Structured AI output")}><div className="dimension-grid">{dimensions.map(([name, description], index) => <article key={name}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{name}</strong><p>{description}</p></div></article>)}</div></Panel><div className="notice-banner neutral"><ShieldCheck size={18} /><div><strong>Every score retains source-document lineage and page citations.</strong><span>Scores become usable only from the filing's public availability date.</span></div></div></div>;
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewId>(() => (new URLSearchParams(window.location.search).get("demo") === "tech-crash" ? "portfolio" : "overview"));
  const [lang, setLangState] = useState<Lang>(getLang());
  const switchLang = (next: Lang) => { setLang(next); setLangState(next); };
  const [mode, setMode] = useState<"research" | "showcase">("research");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [factor, setFactor] = useState<Factor | null>(null);
  const [connection, setConnection] = useState<"connecting" | "live" | "polling" | "snapshot" | "offline">("connecting");
  const [lastSync, setLastSync] = useState<Date | null>(null);

  useEffect(() => {
    let disposed = false;
    const refresh = async (initial = false) => {
      try {
        const result = await loadSnapshot();
        if (disposed) return;
        setSnapshot(result.snapshot);
        if (initial) {
          setMode(result.snapshot.meta.mode === "showcase_reenactment" ? "showcase" : "research");
        }
        setConnection(result.source === "live" ? "live" : "snapshot");
        setLastSync(new Date());
        setError("");
      } catch (reason) {
        if (disposed) return;
        setConnection("offline");
        if (initial) setError(reason instanceof Error ? reason.message : String(reason));
      }
    };
    void refresh(true);
    const stopEvents = subscribeToSnapshotEvents(
      () => void refresh(),
      () => setConnection("live"),
      () => setConnection((state) => state === "snapshot" ? state : "polling"),
    );
    const timer = window.setInterval(() => void refresh(), 15_000);
    return () => {
      disposed = true;
      stopEvents();
      window.clearInterval(timer);
    };
  }, []);

  const navigate = (next: ViewId) => {
    if (/(?:demo|start_node)=/.test(window.location.search)) {
      window.history.replaceState({}, "", window.location.pathname);
    }
    setView(next);
    setSidebarOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  if (error) return <main className="load-screen"><CircleAlert size={30} /><h1>{tr("Snapshot unavailable")}</h1><p>{error}</p><code>python scripts/export_dashboard_snapshot.py</code></main>;
  if (!snapshot) return <main className="load-screen"><div className="loader" /><h1>{tr("Booting research console")}</h1><p>{tr("Loading the audited workspace snapshot…")}</p></main>;

  return (
    <div className={`app-shell mode-${mode}`}>
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand"><div className="brand-mark">A</div><div><strong>ASTER</strong><span>RESEARCH CONSOLE</span></div></div>
        <nav>{navigation.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => navigate(item.id)}><Icon size={19} /><span>{tr(item.label)}</span></button>; })}</nav>
        <div className={`sidebar-foot connection-${connection}`}><div><Activity size={15} /><span>{tr("Live feed")}</span><strong>{connection.toUpperCase()}</strong></div><small>Catalog {snapshot.meta.catalogDigest}</small></div>
      </aside>
      {sidebarOpen && <button className="sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-label={tr("Close navigation")} />}
      <main className="workspace">
        <header className="topbar"><button className="mobile-menu" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><div className="workspace-status"><span className={`live-dot connection-${connection}`} /><span>{tr("WORKSPACE")}</span><strong>CSI500 PIT</strong><i /> <span>{tr("AS OF")}</span><strong>{snapshot.meta.asOf}</strong><i /> <span>{tr("SYNC")}</span><strong>{lastSync ? humanDate(lastSync.toISOString()) : "—"}</strong></div><div className="lang-switch">{[["en", "EN"], ["zh", "中文"], ["dual", "Dual"]].map(([id, label]) => <button key={id} className={lang === id ? "active" : ""} onClick={() => switchLang(id as Lang)}>{label}</button>)}</div><div className="mode-switch"><button className={mode === "research" ? "active" : ""} onClick={() => setMode("research")}>{tr("Research")}</button><button className={mode === "showcase" ? "active" : ""} onClick={() => setMode("showcase")}>{tr("Showcase")}</button></div></header>
        <div className="content">
          {view === "overview" && <Overview snapshot={snapshot} navigate={navigate} openFactor={setFactor} />}
          {view === "factors" && <FactorLibrary snapshot={snapshot} openFactor={setFactor} />}
          {view === "council" && <Council snapshot={snapshot} />}
          {view === "filings" && <Filings snapshot={snapshot} />}
          {view === "portfolio" && <Portfolio snapshot={snapshot} />}
        </div>
      </main>
      {factor && <FactorDrawer factor={factor} close={() => setFactor(null)} />}
    </div>
  );
}

export default App;
