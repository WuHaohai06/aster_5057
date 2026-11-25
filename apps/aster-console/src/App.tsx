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
            <strong>{stage.label}</strong>
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
          <h1>From raw evidence<br />to bounded decisions.</h1>
          <p>
            CSI500 数据、AI 因子挖掘、机制评审、组合优化与回测，汇聚在同一个可审计的研究界面。
          </p>
          <div className="hero-actions">
            <button className="primary-button" onClick={() => navigate("council")}>Open Council</button>
            <button className="ghost-button" onClick={() => navigate("factors")}>Explore factors</button>
          </div>
        </div>
        <div className="signal-orbit" aria-label="Research system summary">
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
        <MetricCard label="FACTOR CATALOG" value={String(snapshot.factors.length)} detail={`${validated} passed lifecycle validation`} />
        <MetricCard label="AI-MINED" value={String(quanta.length)} detail="QuantaAlpha candidates" tone="violet" />
        <MetricCard label="FILING INTELLIGENCE" value={filingTotal ? percent(filingDone / filingTotal) : "—"} detail={`${filingDone} / ${filingTotal} reports scored`} tone="green" />
        <MetricCard label="LATEST REPLAY" value={portfolio ? percent(portfolio.metrics.annual_return) : "—"} detail="annualised return · disclosed run" tone="amber" />
      </div>

      <Panel title="Research pipeline" kicker="Live system map" action={<StatusPill tone="live">WORKSPACE LIVE</StatusPill>}>
        <Pipeline snapshot={snapshot} navigate={navigate} />
      </Panel>

      <Panel title="Background jobs" kicker="Live sanitised status" action={<StatusPill tone="live">AUTO REFRESH</StatusPill>}>
        <JobMonitor jobs={snapshot.jobs} />
      </Panel>

      <div className="two-column">
        <Panel title="Signal leaderboard" kicker="Canonical diagnostics" action={<button className="text-button" onClick={() => navigate("factors")}>View library</button>}>
          <div className="leaderboard">
            {topFactors.map((factor, index) => (
              <button key={factor.id} onClick={() => openFactor(factor)}>
                <span className="rank">{index + 1}</span>
                <span className="factor-ident"><strong>{factor.name}</strong><small>{factor.group}</small></span>
                <span className="metric-pair"><small>RANK IC</small><strong>{decimal(factor.metrics.rankIc, 4)}</strong></span>
                <span className="metric-pair"><small>ICIR</small><strong>{decimal(factor.metrics.rankIcIr)}</strong></span>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Latest Council state" kicker="Historical accepted artifact" action={<StatusPill tone={snapshot.factorCouncil.decision.fallbackUsed ? "warn" : "good"}>{snapshot.factorCouncil.decision.status.toUpperCase()}</StatusPill>}>
          <div className="council-summary">
            <div className="selected-strip">
              {snapshot.factorCouncil.decision.selectedGroups.map((group) => <span key={group}><Check size={14} />{group}</span>)}
            </div>
            <p>{snapshot.factorCouncil.decision.rationale}</p>
            <button className="text-button" onClick={() => navigate("council")}>Inspect ballots and evidence</button>
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
      .filter((factor) => !lowered || `${factor.name} ${factor.id} ${factor.group} ${factor.hypothesis}`.toLowerCase().includes(lowered))
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
        <div><span className="eyebrow">UNIFIED FACTOR CATALOG</span><h1>Factor Library</h1><p>从经济学假设、标准诊断到 Council 生命周期的统一研究对象。</p></div>
        <div className="heading-stats"><strong>{filtered.length}</strong><span>visible / {snapshot.factors.length} total</span></div>
      </div>
      <Panel title="Catalog explorer" kicker="Search · filter · inspect">
        <div className="filter-bar">
          <label className="search-field"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search factor, group or hypothesis" /></label>
          <label className="select-field"><Filter size={15} /><select value={origin} onChange={(event) => setOrigin(event.target.value)}><option value="all">All origins</option>{origins.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label className="select-field"><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All lifecycle states</option><option value="candidate">Candidate</option><option value="validated">Validated</option><option value="demo_selected">Demo selected</option></select></label>
          <label className="select-field"><select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)}><option value="rankIc">Sort: Rank IC</option><option value="coverage">Sort: Coverage</option><option value="name">Sort: Name</option></select></label>
        </div>
        <div className="factor-table-wrap">
          <table className="factor-table">
            <thead><tr><th>Factor</th><th>Origin</th><th>Lifecycle</th><th>Rank IC</th><th>ICIR</th><th>Coverage</th><th>Turnover</th><th>Redundancy</th><th /></tr></thead>
            <tbody>{filtered.map((factor) => (
              <tr key={factor.id} onClick={() => openFactor(factor)}>
                <td><strong>{factor.name}</strong><small>{factor.id} · {factor.group}</small></td>
                <td><span className="origin-tag">{factor.origin}</span></td>
                <td><StatusPill tone={factor.status === "candidate" ? "neutral" : factor.status === "demo_selected" ? "violet" : "good"}>{factor.status.replace("_", " ")}</StatusPill></td>
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
        <button className="icon-button drawer-close" onClick={close} aria-label="Close factor details"><X size={20} /></button>
        <span className="eyebrow">FACTOR DOSSIER · {factor.origin}</span>
        <h2>{factor.name}</h2>
        <p className="drawer-description">{factor.description}</p>
        <div className="drawer-tags"><StatusPill tone={factor.status === "candidate" ? "neutral" : "good"}>{factor.status}</StatusPill>{factor.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
        <div className="drawer-metrics">
          <div><small>RANK IC</small><strong>{decimal(factor.metrics.rankIc, 4)}</strong></div>
          <div><small>ICIR</small><strong>{decimal(factor.metrics.rankIcIr)}</strong></div>
          <div><small>COVERAGE</small><strong>{percent(factor.metrics.coverage)}</strong></div>
          <div><small>TURNOVER</small><strong>{percent(factor.metrics.turnover)}</strong></div>
        </div>
        <section className="dossier-section"><h3><BookOpenText size={17} />Economic hypothesis</h3><p>{factor.hypothesis || "No structured hypothesis has been registered."}</p></section>
        <section className="dossier-section"><h3><GitBranch size={17} />Mechanism</h3><p>{factor.mechanism || "Mechanism review is pending."}</p><div className="direction-callout"><span>EXPECTED DIRECTION</span>{factor.expectedDirection || "Not specified"}</div></section>
        <section className="dossier-section"><h3><Archive size={17} />Signal construction</h3><code>{factor.expression}</code></section>
        <section className="dossier-section"><h3><ShieldCheck size={17} />Falsification criteria</h3><ul>{factor.falsificationCriteria.length ? factor.falsificationCriteria.map((item) => <li key={item}>{item}</li>) : <li>No explicit criterion registered.</li>}</ul></section>
        {yearly.length > 0 && <section className="dossier-section"><h3><BarChart3 size={17} />Yearly Rank IC</h3><div className="year-bars">{yearly.map(([year, value]) => <div key={year}><span>{year}</span><div><i className={value >= 0 ? "bar-positive" : "bar-negative"} style={{ width: `${Math.abs(value) / maxAbs * 100}%` }} /></div><strong>{value.toFixed(3)}</strong></div>)}</div></section>}
        <section className="lineage-box"><div><small>CATALOG ID</small><strong>{factor.id}</strong></div><div><small>ARTIFACT</small><strong>{factor.artifact.digest}</strong></div><div><small>PIT</small><strong>{factor.pitCompliant ? "COMPLIANT" : "REVIEW"}</strong></div></section>
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
        <div><span className="eyebrow">BOUNDED MULTI-AGENT GOVERNANCE</span><h1>AI Council Chamber</h1><p>三位独立 Reviewer 提交证据化投票，Chair 在代码约束内形成最终因子组选择。</p></div>
        <div className="heading-badges"><StatusPill tone="good">PACKET {packet.version || "V2"}</StatusPill><StatusPill tone={decision.fallbackUsed ? "warn" : "good"}>{decision.fallbackUsed ? "FALLBACK USED" : "ACCEPTED"}</StatusPill></div>
      </div>
      {mechanismReviewPending && <div className="notice-banner"><CircleAlert size={18} /><div><strong>机制评审已升级，但当前展示的是历史 Council 运行。</strong><span>新版 packet 已包含机制字段；重新运行 Council 后会出现逐组机制评级。</span></div></div>}
      <div className="council-layout">
        <Panel title="Candidate groups" kicker={`Input cutoff · ${packet.inputCutoff}`} className="candidate-panel">
          <div className="candidate-list">{packet.groups.map((item) => {
            const selected = decision.selectedGroups.includes(item.id);
            return <button key={item.id} className={`${selectedGroup === item.id ? "active" : ""} ${selected ? "chosen" : ""}`} onClick={() => setSelectedGroup(item.id)}><span><strong>{item.id}</strong><small>{item.factorIds.length} factor{item.factorIds.length === 1 ? "" : "s"}</small></span><span className="candidate-score">{decimal(item.rankIc, 4)}</span></button>;
          })}</div>
        </Panel>
        <Panel title={group?.id ?? "Group evidence"} kicker="Mechanism + deterministic diagnostics" className="group-evidence">
          {group && <>
            <div className="evidence-metrics"><div><small>MEDIAN RANK IC</small><strong>{decimal(group.rankIc, 4)}</strong></div><div><small>ICIR</small><strong>{decimal(group.rankIcIr)}</strong></div><div><small>TURNOVER</small><strong>{percent(group.turnover)}</strong></div><div><small>MAX CORR</small><strong>{percent(group.correlation)}</strong></div></div>
            <div className="mechanism-stack">{group.mechanisms.map((item) => <article key={item.factorId}><span>{item.factorId}</span><h3>{item.hypothesis || "Hypothesis not registered"}</h3><p>{item.mechanism || "Mechanism explanation pending."}</p><small>{item.expectedDirection}</small></article>)}</div>
          </>}
        </Panel>
      </div>
      <Panel title="Independent ballots" kicker="Reviewer-level audit trail">
        <div className="reviewer-grid">{ballots.map((ballot) => {
          const vote = ballot.votes.find((item) => item.group_id === selectedGroup);
          return <article className="reviewer-card" key={ballot.role}><div className="reviewer-title"><div className="reviewer-icon"><Bot size={18} /></div><div><strong>{roleNames[ballot.role] ?? ballot.role}</strong><small>Independent reviewer</small></div>{vote && <StatusPill tone={vote.action === "enable" ? "good" : vote.action === "disable" ? "bad" : "warn"}>{vote.action}</StatusPill>}</div>{vote ? <><p>{vote.rationale}</p><div className="confidence"><span>CONFIDENCE</span><div><i style={{ width: `${vote.confidence * 100}%` }} /></div><strong>{percent(vote.confidence)}</strong></div>{vote.risks.length > 0 && <ul>{vote.risks.slice(0, 2).map((risk) => <li key={risk}>{risk}</li>)}</ul>}</> : <p>No historical vote for this newly eligible group.</p>}</article>;
        })}</div>
      </Panel>
      <Panel title="Chair decision" kicker={`${decision.decisionAt} · ${decision.promptVersion}`} action={<span className="confidence-badge">{percent(decision.confidence)} confidence</span>}>
        <div className="chair-decision"><div className="chair-groups"><div><small>SELECTED</small>{decision.selectedGroups.map((item) => <span className="selected" key={item}><Check size={13} />{item}</span>)}</div><div><small>DISABLED</small>{decision.disabledGroups.map((item) => <span key={item}>{item}</span>)}</div></div><p>{decision.rationale}</p>{decision.fallbackReason && <div className="fallback-reason"><CircleAlert size={16} /><span>{decision.fallbackReason}</span></div>}</div>
      </Panel>
    </div>
  );
}

function PerformanceChart({ curve }: { curve: Snapshot["portfolio"]["runs"][number]["curve"] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!curve.length) return <div className="empty-state">No replay curve available.</div>;
  const min = Math.min(...curve.map((item) => item.nav));
  const max = Math.max(...curve.map((item) => item.nav));
  const range = max - min || 1;
  const points = curve.map((item, index) => `${index / (curve.length - 1) * 1000},${250 - (item.nav - min) / range * 210}`).join(" ");
  const active = hover == null ? curve[curve.length - 1] : curve[hover];
  const activeX = (hover == null ? curve.length - 1 : hover) / (curve.length - 1) * 1000;
  const activeY = 250 - (active.nav - min) / range * 210;
  const onMove = (event: MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setHover(Math.max(0, Math.min(curve.length - 1, Math.round((event.clientX - rect.left) / rect.width * (curve.length - 1)))));
  };
  return <div className="performance-chart"><div className="chart-readout"><span>{active.date}</span><strong>NAV {active.nav.toFixed(3)}</strong><small>DD {percent(active.drawdown)}</small></div><svg viewBox="0 0 1000 280" preserveAspectRatio="none" onMouseMove={onMove} onMouseLeave={() => setHover(null)}><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#31d7c7" stopOpacity=".28" /><stop offset="100%" stopColor="#31d7c7" stopOpacity="0" /></linearGradient></defs><line x1="0" y1="250" x2="1000" y2="250" className="chart-axis" /><polygon points={`0,250 ${points} 1000,250`} fill="url(#area)" /><polyline points={points} className="chart-line" /><line x1={activeX} x2={activeX} y1="28" y2="250" className="chart-crosshair" /><circle cx={activeX} cy={activeY} r="6" className="chart-point" /></svg></div>;
}

function Portfolio({ snapshot }: { snapshot: Snapshot }) {
  const [runId, setRunId] = useState(snapshot.portfolio.runs[0]?.id ?? "");
  const run = snapshot.portfolio.runs.find((item) => item.id === runId) ?? snapshot.portfolio.runs[0];
  if (!run) return <div className="empty-state">No portfolio replay is available.</div>;
  return <div className="view-stack"><div className="page-heading"><div><span className="eyebrow">DETERMINISTIC OPTIMISATION + COUNCIL PROFILE</span><h1>Portfolio Replay</h1><p>净值、回撤、Beta 与成本来自保存的可重放运行；不代表未来投资表现。</p></div><label className="select-field run-select"><select value={runId} onChange={(event) => setRunId(event.target.value)}>{snapshot.portfolio.runs.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label></div><div className="metric-grid"><MetricCard label="ANNUALISED RETURN" value={percent(run.metrics.annual_return)} detail="saved replay" tone={run.metrics.annual_return >= 0 ? "green" : "amber"} /><MetricCard label="SHARPE" value={decimal(run.metrics.sharpe, 2)} detail="realised risk-adjusted" /><MetricCard label="MAX DRAWDOWN" value={percent(run.metrics.max_drawdown)} detail="peak-to-trough" tone="amber" /><MetricCard label="MAX ABS BETA" value={decimal(run.metrics.max_abs_estimated_beta, 3)} detail="after futures hedge" tone="violet" /></div><Panel title="Equity curve" kicker="Interactive saved replay" action={<StatusPill tone="warn">COURSE DEMO · NOT ADVICE</StatusPill>}><PerformanceChart curve={run.curve} /></Panel><div className="two-column"><Panel title="Exposure & cost" kicker="Deterministic controls"><div className="stat-list"><div><span>Mean gross exposure</span><strong>{percent(run.metrics.mean_gross_exposure)}</strong></div><div><span>Total cost fraction</span><strong>{percent(run.metrics.total_cost_fraction)}</strong></div><div><span>Stock turnover</span><strong>{decimal(run.metrics.total_stock_turnover, 2)}</strong></div><div><span>Futures turnover</span><strong>{decimal(run.metrics.total_futures_turnover, 2)}</strong></div></div></Panel><Panel title="Interpretation" kicker="What this run proves"><div className="narrative-card"><Network size={22} /><p>这条曲线证明数据、预测、优化、IC 对冲和组合回放能够在同一套审计契约下运行。它不是对策略有效性的正式结论。</p></div></Panel></div></div>;
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
  return <div className="view-stack"><div className="page-heading"><div><span className="eyebrow">DOCUMENT → AI-FRIENDLY EVIDENCE → FACTOR ROWS</span><h1>Filing Intelligence</h1><p>财报原文经过结构化解析、引用定位和 DeepSeek 评分，最终转换为 PIT 因子记录。</p></div><StatusPill tone={score < total ? "live" : "good"}>{score < total ? "SCORING LIVE" : "COMPLETE"}</StatusPill></div><section className="filing-progress"><div className="progress-copy"><span>{filing.year_start ?? 2020}-{filing.year_end ?? 2025} ANNUAL REPORT BATCHES</span><strong>{percent(progress)}</strong><p>{score} of {total} scoreable reports completed</p></div><div className="radial-progress" style={{ "--progress": `${progress * 360}deg` } as CSSProperties}><div><FileSearch size={25} /><strong>{score}</strong><span>SCORED</span></div></div></section><div className="metric-grid"><MetricCard label="PARSED DOCUMENTS" value={`${parsed}/${documents}`} detail={`${filing.parse_failures ?? 0} parse failure`} /><MetricCard label="GENERATED FACTOR ROWS" value={compact(filing.factor_rows)} detail="five dimensions per successful report" tone="green" /><MetricCard label="TOKEN USAGE" value={compact(filing.token_usage?.total_tokens)} detail="prompt + completion" tone="violet" /><MetricCard label="OCR QUEUE" value={String(filing.needs_ocr ?? 0)} detail="documents requiring fallback" tone="amber" /></div>{years.length > 0 && <Panel title="Annual batches" kicker="2020-2025 completion ledger"><div className="filing-years">{years.map((year) => { const done = year.score_completed ?? 0; const count = year.score_total ?? year.documents_total ?? 0; return <article key={year.year}><span>{year.year}</span><strong>{done}/{count}</strong><small>{compact(year.factor_rows)} factor rows</small><StatusPill tone={year.state === "complete" ? "good" : "live"}>{year.state ?? "pending"}</StatusPill></article>; })}</div></Panel>}<Panel title="Financial narrative dimensions" kicker="Structured AI output"><div className="dimension-grid">{dimensions.map(([name, description], index) => <article key={name}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{name}</strong><p>{description}</p></div></article>)}</div></Panel><div className="notice-banner neutral"><ShieldCheck size={18} /><div><strong>Every score retains source-document lineage and page citations.</strong><span>Scores become usable only from the filing's public availability date.</span></div></div></div>;
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewId>("overview");
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

  const navigate = (next: ViewId) => { setView(next); setSidebarOpen(false); window.scrollTo({ top: 0, behavior: "smooth" }); };
  if (error) return <main className="load-screen"><CircleAlert size={30} /><h1>Snapshot unavailable</h1><p>{error}</p><code>python scripts/export_dashboard_snapshot.py</code></main>;
  if (!snapshot) return <main className="load-screen"><div className="loader" /><h1>Booting research console</h1><p>Loading the audited workspace snapshot…</p></main>;

  return (
    <div className={`app-shell mode-${mode}`}>
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand"><div className="brand-mark">A</div><div><strong>ASTER</strong><span>RESEARCH CONSOLE</span></div></div>
        <nav>{navigation.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => navigate(item.id)}><Icon size={19} /><span>{item.label}</span></button>; })}</nav>
        <div className={`sidebar-foot connection-${connection}`}><div><Activity size={15} /><span>Live feed</span><strong>{connection.toUpperCase()}</strong></div><small>Catalog {snapshot.meta.catalogDigest}</small></div>
      </aside>
      {sidebarOpen && <button className="sidebar-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation" />}
      <main className="workspace">
        <header className="topbar"><button className="mobile-menu" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><div className="workspace-status"><span className={`live-dot connection-${connection}`} /><span>WORKSPACE</span><strong>CSI500 PIT</strong><i /> <span>AS OF</span><strong>{snapshot.meta.asOf}</strong><i /> <span>SYNC</span><strong>{lastSync ? humanDate(lastSync.toISOString()) : "—"}</strong></div><div className="mode-switch"><button className={mode === "research" ? "active" : ""} onClick={() => setMode("research")}>Research</button><button className={mode === "showcase" ? "active" : ""} onClick={() => setMode("showcase")}>Showcase</button></div></header>
        {mode === "showcase" && <div className="showcase-disclosure"><CircleAlert size={15} />{snapshot.meta.showcaseDisclosure}</div>}
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
