# Aster AI Factor Council v2

## Scope

Council v2 selects an enabled group mask from a versioned registry of already
approved factors. It cannot create or edit formulas, assign continuous factor
weights, place trades, or use evidence after `input_cutoff`.

The workflow is:

1. Build a deterministic point-in-time packet.
2. Run three independent reviewers in parallel.
3. Run the chair only after every ballot passes schema and citation checks.
4. Validate the chair mask with deterministic rules.
5. Persist packet, ballots, raw model outputs, decision and file hashes.
6. Use the declared fixed factor pool on any failure or explicit chair fallback.

## Roles

- `market_regime_reviewer`: price-observable regime evidence only.
- `factor_evidence_reviewer`: matured IC, decay, stability, turnover and redundancy.
- `risk_data_reviewer`: coverage, lineage, proxy limits and multiple-testing risk.
- `chair`: reconciles ballots under hard constraints; it is not a majority voter.

## Inputs

Four JSON inputs are required:

- factor registry: version, group, formula, origin and approval status;
- diagnostics: only labels matured by the cutoff, coverage, IC/ICIR, decay and turnover;
- market state: benchmark trend/volatility, breadth, dispersion and correlation;
- policy: group-count limits, hard evidence gates, required baselines and fallback groups.

Files prefixed with `smoke_` under `config/council` are synthetic integration
fixtures. They must never be presented as research results.

## Commands

Build a packet:

```powershell
$env:PYTHONPATH = "$PWD\src"
conda run -n aster_5057_quantaalpha python -m aster_council build-packet `
  --registry .\config\council\smoke_factor_registry.json `
  --diagnostics .\config\council\smoke_diagnostics.json `
  --market .\config\council\smoke_market_state.json `
  --policy .\config\council\smoke_policy.json `
  --decision-at 2024-12-31 `
  --input-cutoff 2024-12-31 `
  --output .\run\council_smoke\packet.json
```

Run with DeepSeek and the current-user DPAPI credential:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_factor_council.ps1 `
  -PacketPath .\run\council_smoke\packet.json
```

Run deterministically without an API:

```powershell
$env:PYTHONPATH = "$PWD\src"
conda run -n aster_5057_quantaalpha python -m aster_council run `
  --packet .\run\council_smoke\packet.json `
  --output-root .\run\council_smoke\offline_runs `
  --static-responses .\config\council\smoke_static_responses.json
```

## Hard guarantees and limitations

- Unmatured labels and diagnostics observed after the cutoff are excluded.
- Every citation must resolve to an evidence ID in the packet.
- Every candidate group must be classified exactly once.
- Every reviewer must separately assess every candidate group's economic
  mechanism, PIT consistency and falsifiability. Missing mechanism reviews
  invalidate the ballot and trigger the deterministic fallback.
- The packet carries the stated hypothesis, mechanism explanation, expected
  direction, falsification criteria and mechanism source; these are claims for
  Council scrutiny, not facts certified by the framework.
- Group-count and conventional-baseline constraints are enforced outside the LLM.
- Runs are immutable directories with a SHA-256 manifest.
- Repeating a provider model name does not pin the provider's underlying weights;
  therefore historical raw outputs and final decisions are retained.
- V2 consumes prepared diagnostics and structured mechanism claims. Producing
  diagnostics from factor values remains deterministic code.

## Filing AI showcase chain

The filing chain imports five annual-report scores as separate Council groups:
`filing_demand_strength`, `filing_management_outlook`, `filing_uncertainty`,
`filing_investment_intensity`, and `filing_margin_pressure`. Event timestamps
are mapped to the first trading day on or after public availability; the latest
public score is then held until the next filing.

The normal policy remains `min_factor_coverage=0.75`. The six-year filing
scores currently cover only about 42.6%–42.8% of eligible member-days, so they
remain research-ineligible candidates. The course-demo configuration
`config/council/filing_ai_showcase_policy.json` uses a disclosed 0.29 historical
coverage gate for the 2021-12-31 packet. Its companion directive explicitly
selects the five filing groups with low-volatility and QuantaAlpha A01/A03. This
is a retrospective showcase reenactment and does not promote those factors in
the research catalog.
