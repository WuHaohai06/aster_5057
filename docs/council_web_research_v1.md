# Council web research v1

Factor Council replay uses a two-stage online research workflow:

1. DeepSeek Search API executes three quarter-specific searches covering market policy,
   liquidity/risk appetite, industry conditions and factor style.
2. A deterministic evidence firewall validates publication dates and search quality.
3. Accepted web evidence is appended to the local quantitative packet.
4. A separate structured DeepSeek call returns the schema-validated Council decision.

The split is required because DeepSeek web tools return text and citations, while the
Council decision must remain strict JSON.

## Research-mode evidence firewall

- `published_at` must exist and be no later than the quarter's `input_cutoff`.
- The source must be published within 365 days before the quarterly decision.
- DeepSeek Search `rerank_score` must be at least 1.5.
- Unknown evidence IDs remain rejected by deterministic Council validation.
- Accepted and rejected results are both retained for audit.

Showcase mode may retain post-decision sources, but the fixed retrospective disclosure
remains visible and the web-evidence artifact carries an additional hindsight warning.

Each source retains URL, title, site, publication time, snippet, summary, authority,
rerank score, PIT eligibility, content hash and a stable `web:*` evidence ID. Runtime
artifacts are stored beside the replay session under `run/aster_console/replay_sessions`.

Set `ASTER_COUNCIL_WEB_SEARCH=0` before starting the console to disable online research.
Search failures are recorded and the Council continues with local evidence rather than
silently treating failed searches as an empty market signal.

