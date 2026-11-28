# Factor Council evidence refresh v1

## Why this exists

The console replay used to carry stale Factor Council evidence forward without
saying so.  Three separate breaks caused every 2026 quarter to run on a
2025-12-31 packet:

1. **Frozen conventional factors.** `build_factor_library` pinned the six
   deterministic price-volume records to
   `data/council/real_evidence_2025/market_factors.parquet`, so their labels could
   never move past 2025-12-31.  Their yearly and decay diagnostics were empty.
2. **No quarterly packets.** Only three Council packets existed
   (2021-12-31, 2025-12-31, 2026-11-24).  `ReplayService._discover_nodes` takes
   the newest packet at or before each quarter end, so all four 2026 quarters
   received the 2025-12-31 packet.  It also rewrote the packet's `input_cutoff`
   to the quarter end, which made stale diagnostics look current.
3. **Council calls could not finish.** `deepseek-flash` spends its output budget
   on hidden reasoning first.  With `max_tokens=6000` all three reviewer calls
   ended with `finish_reason=length`, `content_chars=0` (26k characters of
   reasoning), so the orchestrator fell back to `conventional_low_vol` +
   `conventional_reversal` deterministically.  A chair answer that selected the
   fallback anchors plus two style groups was also rejected because
   `use_fallback=true` is only valid for exactly the fallback pair.

The observable symptom: 2026 had two active features (`low_vol`, `reversal`)
instead of the 5.5-8.6 features used in earlier years, and the first clean
point-in-time year produced -28%/yr alpha.

## What the refresh does

`scripts/refresh_factor_evidence.py` rebuilds one quarter at a time:

1. rebuild `market_factors.parquet` from the market store with `as_of=cutoff`;
2. rebase the catalogue's conventional records onto that file
   (`rebase_market_factor_artifacts`);
3. re-evaluate every research-eligible factor as of the cutoff in bounded
   chunks (conventional, style, then one QuantaAlpha group at a time - the whole
   library is ~70M rows and would not fit in memory at once);
4. export the research Council inputs (registry + diagnostics);
5. build the Council packet with `decision_at = input_cutoff = cutoff`.

Artifacts land in `data/council/quarterly_evidence/<cutoff>/`:

```text
library/catalog.json              # per-cutoff copy, refreshed diagnostics
evidence/market_factors.parquet   # rebuilt, conventional factors
evidence/market_state.json
evidence/eval/<chunk>/            # per-chunk registry + diagnostics
council_inputs/                   # registry + diagnostics for the packet
packet.json                       # PIT packet for the cutoff
refresh.json                      # summary (44 factors, observed_at == cutoff)
```

## Commands

Build evidence and packets for the three missing 2026 quarters:

```powershell
python scripts/refresh_factor_evidence.py `
  --cutoff 2026-03-31 --cutoff 2026-06-30 --cutoff 2026-09-30 `
  --output-root data/council/quarterly_evidence
```

Run the Council for each packet (needs the stored DeepSeek key):

```powershell
python scripts/refresh_factor_evidence.py `
  --cutoff 2026-03-31 --cutoff 2026-06-30 --cutoff 2026-09-30 `
  --output-root data/council/quarterly_evidence --run-council
```

`decision.json` is written under `data/council/real_runs/<cutoff>_<timestamp>_.../`.
`ReplayService` picks the newest packet per quarter, so a new replay session
uses the fresh decisions; existing sessions keep the schedule they were built
with.

## Guards added

- `ReplayService._rebase_packet` keeps the packet's own `input_cutoff`; only the
  decision date moves to the quarter end.
- Each node now carries `evidence_age_days` and `evidence_stale`, and
  `_public_session` exposes `evidence_health` with `current`, `carry_forward`,
  `stale`, `oldest_evidence_as_of` and warnings.
- `DeepSeekCouncilClient` defaults to 20k output tokens, retries once at 32k when
  a reasoning response ends with `length` and empty content, and uses a 300s
  timeout.
- The chair prompt states that `use_fallback=true` requires exactly the declared
  fallback groups, and the orchestrator re-asks once when a chair answer only
  violates that rule.

## Verification

```powershell
# 2026-09-30 packet: 44 factors, all diagnostics observed at the cutoff
Get-Content data/council/quarterly_evidence/2026-09-30/refresh.json

# Decision should be "accepted" with style groups, not "fallback"
Get-Content data/council/real_runs/<run_id>/decision.json
```

Tests: `tests/test_evidence_refresh.py`, `tests/test_llm_budget.py`,
`tests/test_council.py`, `tests/test_interactive_replay.py`.
