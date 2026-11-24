# Financial, factor-evidence, and research pipeline v1

This slice closes the path from official filings and PIT financial rows to
Factor Council evidence and a reproducible research release.

## Implemented contracts

- `scripts/download_filings_bulk.py` queries CNINFO first and uses SSE/SZSE on
  gaps. PDFs are content-addressed by SHA-256; the job is resumable.
- `scripts/parse_filings.py` writes page-addressable JSON and Markdown. PyPDF is
  the baseline; low-text documents are marked `needs_ocr` for selective MinerU
  processing rather than silently returning an empty document.
- `scripts/build_financial_factors.py` preserves disclosure `date` as
  `available_at`. The evaluator forward-fills a value only after disclosure.
- `scripts/generate_filing_text_factors.py` provides deterministic text
  features by default and an optional citation-validated DeepSeek mode. LLM
  scores with missing evidence or invalid page references are rejected.
- `scripts/ingest_quantalpha_results.py` accepts CSV/Parquet factor output and
  enforces the canonical long schema. It does not infer economic meaning.
- `scripts/build_factor_evidence.py` builds price-volume baselines, matured
  forward labels, coverage, Rank IC/IR, turnover, redundancy, and real market
  context.
- `scripts/build_factor_council_packet.py` applies hard PIT and coverage gates.
- `scripts/audit_research_run.py` verifies inputs, creates a controlled
  experiment matrix, reconciles return attribution, writes a report, and
  hashes the release files.

The canonical factor key is `(date, instrument, factor_id)`. `available_at`
must never exceed the signal date. Raw PDF text retains page numbers and the
source PDF hash so an LLM claim can be mapped back to evidence.

## Typical commands

```powershell
powershell -File .\scripts\start_filing_download.ps1
conda run -n aster_5057_whh python .\scripts\parse_filings.py
conda run -n aster_5057_whh python .\scripts\build_financial_factors.py `
  --pit-root .\data\raw\qlib_full\pit --output-root .\data\curated\factors
conda run -n aster_5057_whh python .\scripts\build_factor_evidence.py `
  --market .\data\curated\market\daily.parquet `
  --factor .\data\curated\factors\financial_factors.parquet `
  --output-root .\data\council\real_evidence --as-of 2025-12-31
```

## Intentional degradation paths

1. If PDF text extraction is weak, retain the original PDF and mark it for OCR;
   do not allow missing text to become a neutral factor.
2. If structured PIT coverage is below policy, the Council excludes financial
   factors and retains the deterministic price-volume fallback groups.
3. If QuantaAlpha produces no candidate, conventional factors still run.
4. If any input audit fails, the release command exits non-zero even though it
   leaves diagnostic artifacts for investigation.

The current financial endpoint exposes `roeWa` and `YOYNI`. This is a useful
minimum implementation, not a complete accounting factor library. Balance
sheet, cash-flow, restatement handling, and text-derived factors remain future
extensions.
