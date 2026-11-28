import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Check, CircleAlert, Pause, Play, RotateCcw, Send, Sparkles } from "lucide-react";
import {
  acceptReplayNode,
  createReplaySession,
  rethinkReplayNode,
  runReplayNode,
  setReplayPlayback,
  subscribeToReplayEvents,
} from "./data";
import type { ReplaySession } from "./types";
import { tr } from "./i18n";

function ReplayCurve({ curve }: { curve: Array<{ date: string; nav: number }> }) {
  if (curve.length < 2) return <div className="replay-empty">{tr("Run and play the accepted segment to reveal its path.")}</div>;
  const min = Math.min(...curve.map((item) => item.nav));
  const max = Math.max(...curve.map((item) => item.nav));
  const range = max - min || 1;
  const points = curve.map((item, index) =>
    `${index / (curve.length - 1) * 1000},${220 - (item.nav - min) / range * 180}`,
  ).join(" ");
  const last = curve[curve.length - 1];
  return <div className="replay-live-chart"><div><span>{last.date}</span><strong>{tr("NAV")} {last.nav.toFixed(3)}</strong></div><svg viewBox="0 0 1000 240" preserveAspectRatio="none"><line x1="0" y1="220" x2="1000" y2="220" /><polyline points={points} /></svg></div>;
}

export default function InteractiveReplay() {
  const [session, setSession] = useState<ReplaySession | null>(null);
  const [activeNodeId, setActiveNodeId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [cursor, setCursor] = useState(0);
  const node = useMemo(
    () => session?.nodes.find((item) => item.node_id === activeNodeId) ?? session?.nodes[0],
    [session, activeNodeId],
  );
  const round = node?.rounds[node.rounds.length - 1];
  const portfolioRound = node?.portfolio_rounds[node.portfolio_rounds.length - 1];
  const pitWebEvidence = (node?.web_evidence?.accepted ?? []).filter((source) => {
    const published = (source.published_at ?? "").slice(0, 10);
    return Boolean(published) && published <= (node?.decision_at ?? "");
  });

  useEffect(() => {
    if (!session) return undefined;
    return subscribeToReplayEvents(session.session_id, setSession, () => undefined);
  }, [session?.session_id]);

  useEffect(() => {
    if (session?.automation_mode === "automatic") {
      setActiveNodeId(session.nodes[session.current_node_index]?.node_id ?? "");
    }
  }, [session?.automation_mode, session?.current_node_index]);

  useEffect(() => {
    if (!session || !node || session.playback.state !== "playing" || session.playback.node_id !== node.node_id) return undefined;
    const timer = window.setInterval(() => {
      setCursor((value) => Math.min(node.run.curve.length, value + Math.max(1, Math.ceil(node.run.curve.length / 180))));
    }, 120);
    return () => window.clearInterval(timer);
  }, [session?.playback.state, session?.playback.node_id, node?.node_id, node?.run.curve.length]);

  useEffect(() => {
    if (!session || !node || session.playback.state !== "playing") return;
    if (node.run.curve.length > 0 && cursor >= node.run.curve.length) {
      void setReplayPlayback(session.session_id, node.node_id, "pause").then(setSession);
    }
  }, [cursor, session?.playback.state, session?.session_id, node?.node_id, node?.run.curve.length]);

  const act = async (label: string, operation: () => Promise<ReplaySession>) => {
    setBusy(label); setError("");
    try { setSession(await operation()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(""); }
  };

  const autoStarted = useRef(false);
  const start = (automatic = false) => void act("start", async () => {
    const params = new URLSearchParams(window.location.search);
    const startNode =
      params.get("start_node") ??
      (params.get("demo") === "tech-crash" ? "2026-06-30" : undefined);
    const next = await createReplaySession(automatic, startNode);
    const initialNode = next.nodes[next.current_node_index ?? 0] ?? next.nodes[0];
    setActiveNodeId(initialNode?.node_id ?? ""); setCursor(0); return next;
  });

  useEffect(() => {
    const active = document.querySelector('.replay-timeline button.active');
    if (active) active.scrollIntoView({ inline: 'center', block: 'nearest' });
  }, [node?.node_id]);

  useEffect(() => {
    const demo = new URLSearchParams(window.location.search).get("demo");
    if (demo === "tech-crash" && !autoStarted.current && !session) {
      autoStarted.current = true;
      start(false);
    }
  }, []);

  if (!session || !node || !round || !portfolioRound) {
    return <section className="interactive-replay replay-welcome"><div><span>{tr("QUARTERLY COUNCIL LAB")}</span><h2>{tr("Unified AI Council Replay")}</h2><p>{tr("Each quarter runs two sequential agendas: factor selection first, then portfolio exposure and industry allocation. Challenge the combined package or accept it once.")}</p></div><div className="replay-welcome-actions"><button className="replay-primary" onClick={() => start(false)} disabled={Boolean(busy)}><Sparkles size={17} />{tr(busy ? "Starting…" : "Start interactive quarterly replay")}</button><button className="replay-secondary" onClick={() => start(true)} disabled={Boolean(busy)}><Play size={17} />{tr("Run automatic quarterly replay")}</button><button className="replay-ghost" onClick={() => { window.location.href = "/?demo=tech-crash"; }}>2026 tech-crash demo</button><button className="replay-ghost" onClick={() => { setSession(null); setActiveNodeId(""); setCursor(0); window.history.replaceState({}, "", window.location.pathname); }}>Default 2021 demo</button></div></section>;
  }

  const reconsiderations = node.rounds.filter((item) => item.origin === "human_reconsideration").length;
  const packageValid = round.valid && portfolioRound.valid && round.round_id === portfolioRound.factor_round_id && portfolioRound.model !== "deterministic-policy";
  const canRethink = !node.accepted_round_id && reconsiderations < session.max_reconsideration_rounds;
  const visibleCurve = node.run.curve.slice(0, cursor);
  const isPlaying = session.playback.state === "playing" && session.playback.node_id === node.node_id;
  const togglePlay = () => void act("playback", async () => {
    if (!isPlaying && cursor >= node.run.curve.length) setCursor(1);
    return setReplayPlayback(session.session_id, node.node_id, isPlaying ? "pause" : "play");
  });

  return <section className="interactive-replay">
    <div className="replay-head"><div><span>QUARTERLY COUNCIL · {session.automation_mode.toUpperCase()} · {session.automation_state.toUpperCase()} · DECISION {node.decision_at}</span><h2>{tr("Unified AI Council Replay")}</h2><p>{tr("Factor Agenda selects the alpha inputs. Portfolio Agenda then sets the approved beta profile and industry tilts. One instruction reruns both prompts.")}</p></div><button className="replay-ghost" onClick={() => start(false)}><RotateCcw size={15} />{tr("New session")}</button>
      <button className="replay-ghost" onClick={() => { setSession(null); setActiveNodeId(""); setCursor(0); window.history.replaceState({}, "", window.location.pathname); }}>Exit session</button></div>
    <div className="replay-timeline">{session.nodes.map((item, index) => <button key={item.node_id} className={`${item.node_id === node.node_id ? "active" : ""} state-${item.status}`} onClick={() => { setActiveNodeId(item.node_id); setCursor(0); }}><i>{item.accepted_round_id ? <Check size={13} /> : index + 1}</i><span>{item.decision_at}<small>{item.status}</small></span></button>)}</div>
    <div className="replay-grid">
      <div className="replay-council">
        <div className="replay-agenda">
          <div className="replay-section-title"><Bot size={18} /><div><strong>1 · Factor Agenda · {round.round_id}</strong><small>Packet {node.packet_digest.slice(0, 12)} · evidence {node.evidence_as_of} ({node.evidence_status})</small></div><b>{Math.round(round.confidence * 100)}%</b></div>
          <div className="replay-groups">{round.selected_groups.map((group) => <span key={group}><Check size={12} />{group}</span>)}</div>
          <p className="replay-rationale">{round.rationale}</p>
          {round.validation_errors.length > 0 && <div className="replay-errors">{round.validation_errors.map((item) => <span key={item}>{item}</span>)}</div>}
        </div>
        <div className="replay-agenda replay-portfolio-agenda">
          <div className="replay-section-title"><Bot size={18} /><div><strong>2 · Portfolio Agenda · {portfolioRound.round_id}</strong><small>{tr("Bounded profile, beta target and industry policy")}</small></div><b>{Math.round(portfolioRound.confidence * 100)}%</b></div>
          <div className="replay-policy-grid"><div><span>{tr("PROFILE")}</span><strong>{portfolioRound.selected_profile_id}</strong></div><div><span>{tr("STOCK")}</span><strong>{Math.round(portfolioRound.stock_target * 100)}%</strong></div><div><span>{tr("TARGET β")}</span><strong>{portfolioRound.target_beta.toFixed(2)}</strong></div><div><span>{tr("TILT")}</span><strong>{Math.round(portfolioRound.industry_active_tilt * 100)}%</strong></div></div>
          <div className="replay-industry"><div><span>{tr("OVERWEIGHT")}</span><strong>{portfolioRound.industry_overweights.join(" · ") || tr("Neutral")}</strong></div><div><span>{tr("UNDERWEIGHT")}</span><strong>{portfolioRound.industry_underweights.join(" · ") || tr("Neutral")}</strong></div></div>
          <p className="replay-rationale">{portfolioRound.rationale}</p>
          {portfolioRound.validation_errors.length > 0 && <div className="replay-errors">{portfolioRound.validation_errors.map((item) => <span key={item}>{item}</span>)}</div>}
        </div>
        {node.web_evidence && <div className="replay-web-evidence"><div><strong>{tr("SHARED WEB EVIDENCE")}</strong><span>{pitWebEvidence.length} PIT-safe · {node.web_evidence.rejected.length} rejected</span></div>{pitWebEvidence.slice(0, 5).map((source) => <a key={source.evidence_id} href={source.url} target="_blank" rel="noreferrer"><span>{source.site_name ?? "Web"} · {source.published_at?.slice(0, 10) ?? "undated"}</span><strong>{source.title}</strong></a>)}{pitWebEvidence.length === 0 && <small>No PIT-dated web evidence retained for this node.</small>}{node.web_evidence.errors.map((item) => <small key={item}>{item}</small>)}</div>}
        <div className="replay-rounds">{node.rounds.map((item) => <article key={item.round_id} className={item.round_id === round.round_id ? "active" : ""}><span>{item.round_id}</span><strong>{tr(item.origin === "human_reconsideration" ? "Human-guided two-agenda reconsideration" : "AI quarterly package")}</strong>{item.human_instruction && <p>“{item.human_instruction}”</p>}<small>{item.valid ? "factor validated" : "factor invalid"} · {node.portfolio_rounds.find((policy) => policy.round_id === item.round_id)?.valid ? "portfolio validated" : "portfolio invalid"}</small></article>)}</div>
      </div>
      <div className="replay-human">
        <span className="replay-label">{tr("YOUR INSTRUCTION TO BOTH AGENDAS")}</span>
        <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} disabled={!canRethink || Boolean(busy)} placeholder={tr("Example: Reconsider factor redundancy first, then reassess beta and industry concentration using the revised factor package.")} />
        <div className="replay-actions"><button className="replay-secondary" disabled={!canRethink || !instruction.trim() || Boolean(busy)} onClick={() => void act("rethink", async () => { const next = await rethinkReplayNode(session.session_id, node.node_id, instruction); setInstruction(""); return next; })}><Send size={15} />{tr("Rerun both agendas")} ({reconsiderations}/{session.max_reconsideration_rounds})</button><button className="replay-primary" disabled={Boolean(node.accepted_round_id) || !packageValid || Boolean(busy)} onClick={() => void act("accept", () => acceptReplayNode(session.session_id, node.node_id))}><Check size={15} />{tr(node.accepted_round_id ? "Package accepted" : portfolioRound.model === "deterministic-policy" ? "Council deliberating…" : "Accept decision package")}</button></div>
        <div className="replay-run"><div><strong>{tr("Next segment")}</strong><span>{node.segment_start} → {node.segment_end}</span></div><button className="replay-primary" disabled={!node.accepted_round_id || node.run.state === "computing" || node.run.state === "ready" || Boolean(busy)} onClick={() => void act("run", () => runReplayNode(session.session_id, node.node_id))}><Play size={15} />{tr(node.run.state === "computing" ? "Computing…" : node.run.state === "ready" ? "Ready" : "Run segment")}</button></div>
        {node.run.error && <div className="replay-errors"><span>{node.run.error}</span></div>}
      </div>
    </div>
    <div className="replay-player"><div className="replay-player-head"><div><strong>{tr("Live segment playback")}</strong><span>{visibleCurve.length}/{node.run.curve.length} {tr("sessions")}</span></div><button onClick={togglePlay} disabled={node.run.state !== "ready" || Boolean(busy)}>{isPlaying ? <Pause size={16} /> : <Play size={16} />}{tr(isPlaying ? "Pause" : "Play")}</button></div><ReplayCurve curve={visibleCurve} /></div>
    {error && <div className="replay-errors"><span>{error}</span></div>}
  </section>;
}
