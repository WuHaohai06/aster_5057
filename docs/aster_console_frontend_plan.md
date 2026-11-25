# Aster Research Console — Frontend Plan

## Product objective

Aster Research Console is the interactive presentation and audit surface for the
whole project. It should explain how raw data becomes an AI-generated hypothesis,
how the hypothesis becomes a tested factor, how the two Councils make bounded
decisions, and how those decisions reach portfolio replay.

The product is designed for a business-literacy course demonstration. It must be
visually compelling, but it must also keep `research` and
`showcase_reenactment` visibly separated and never present hindsight as a live
prediction.

## Experience principles

1. **Traceability before decoration.** Every selected factor should link back to
   its hypothesis, mechanism, source, diagnostics and Council evidence.
2. **A single research story.** The main path is Data → Mining → Evaluation →
   Factor Council → Forecast → Optimisation → Portfolio Council → Replay.
3. **Bounded AI is visible.** AI proposes and votes; deterministic code enforces
   data cutoffs, eligibility, portfolio constraints and fallback.
4. **Honest modes.** Research and retrospective showcase modes use different
   badges, disclosures and colour treatments.
5. **Live with a static fallback.** The browser consumes the same sanitised
   contract from a read-only FastAPI adapter and falls back to a static JSON
   snapshot when the service is unavailable.

## Information architecture

### Command Center

- End-to-end pipeline graph with clickable stages and state.
- Live job cards for market, financial and filing pipelines.
- Factor-library and Council summary.
- Latest replay headline metrics and disclosure.

### Factor Library

- Search, origin/family/status filters and metric sorting.
- Rank IC, ICIR, coverage, turnover and redundancy columns.
- Factor drawer with formula, economic hypothesis, mechanism, expected direction,
  falsification criteria, PIT status, lineage and yearly evidence.
- Factor comparison and correlation matrix are phase-two features.

### AI Council

- Candidate factor groups and the current packet cutoff.
- Independent reviewer ballots, confidence, citations and dissent.
- Structured mechanism review status: support, PIT consistency and falsifiability.
- Chair result, fallback reason and immutable disclosure.
- Timeline replay is a phase-two feature.

### Filing Intelligence

- Parse and LLM-scoring progress, failures, token usage and generated rows.
- Five filing dimensions and citation drill-down in phase two.

### Portfolio & Replay

- Equity and drawdown series, benchmark comparison and headline metrics.
- Portfolio Council profile, beta/hedge and optimisation diagnostics in phase two.
- Council decision markers on the replay timeline in phase two.

## Visual direction

- Dark quantitative workstation, inspired by institutional research terminals.
- Ink/navy surfaces, cyan for active research, green for validated state, amber
  for caveats and rose only for hard failure.
- Dense but readable tables, monospaced numeric labels, subtle gridlines and no
  ornamental finance imagery.
- Minimum 16 px body text and 14 px operational labels.

## Architecture

```text
Current workspace JSON / CSV / Parquet
                 |
                 v
scripts/export_dashboard_snapshot.py (sanitised contract)
                 |
          +------+------+
          |             |
          v             v
FastAPI /api/snapshot   public/data/snapshot.json
          |             (static fallback)
          +------+------+
                 v
React + TypeScript + Vite application
       SSE event + 15-second polling
```

The browser never receives credentials, raw provider responses, local absolute
paths, process IDs, log paths, full PDFs or large Parquet files. The same
snapshot schema is served by the read-only endpoint and the static fallback.

## Snapshot contract

- `meta`: generation time, as-of date, schema, mode disclosure.
- `pipeline`: stage state, counts and navigation destination.
- `jobs`: sanitised background-job state.
- `factors`: catalog definition, mechanism and diagnostic summary.
- `factorCouncil`: packet candidates, latest decision and reviewer ballots.
- `portfolio`: metrics and downsampled daily curve.
- `filings`: annual filing pipeline progress and usage.

## Delivery phases

### Phase 1 — interactive foundation

- Vite/React shell and responsive terminal visual system.
- Command Center, Factor Library/detail, Council, Filing and Portfolio views.
- Snapshot exporter and current-workspace snapshot.
- Search, filtering, navigation, drawers, mode disclosure and chart interaction.

### Phase 2 — research depth

- Factor comparison, yearly IC charts and correlation heatmap.
- Council timeline replay and citation drawer.
- Filing company/document browser.
- Portfolio exposure, beta, hedge and decision markers.

### Phase 3 — local live mode (implemented)

- Read-only FastAPI service using the snapshot contract.
- Polling/SSE for background jobs and newly mined factor candidates.
- Six-year filing aggregation and current data-download state.
- No task-control endpoints and no secrets in the browser.
- Optional Cloudflare tunnel launcher; access control remains at the tunnel edge.

## Acceptance criteria for Phase 1

- Production build succeeds from a clean dependency install.
- Every navigation item renders useful real workspace data.
- Factors can be searched, filtered and opened without a page reload.
- Council selections and fallback status are explicitly distinguishable.
- Research/showcase disclosure remains visible.
- The app works at desktop presentation width and mobile/tablet widths.
- Snapshot contains no secret or absolute local filesystem path.

