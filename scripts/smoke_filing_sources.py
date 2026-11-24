"""Small live probe for CNINFO-primary and exchange-fallback filing sources."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aster_data.filing_sources import (  # noqa: E402
    OfficialFilingClient,
    newest_full_report,
)


def main() -> int:
    client = OfficialFilingClient(PROJECT_ROOT, timeout=30)
    output: dict = {"range": ["2024-01-01", "2025-06-30"], "samples": {}}

    for code in ("600519", "000001"):
        sample = {
            "source_status": {},
            "primary": None,
            "exchange_probe": None,
        }
        try:
            records = client.query_cninfo(
                code, "2024-01-01", "2025-06-30", "annual"
            )
            sample["source_status"]["cninfo"] = f"catalogue_ok:{len(records)}"
            selected = newest_full_report(records)
            artifact = client.download(selected)
            sample["source_status"]["cninfo"] += ";download_ok"
            sample["primary"] = {
                "selected": {
                    key: value for key, value in asdict(selected).items() if key != "raw"
                },
                "download": {
                    **asdict(artifact),
                    "record_path": str(artifact.record_path),
                    "blob_path": str(artifact.blob_path),
                },
            }
        except Exception as exc:
            previous = sample["source_status"].get("cninfo", "")
            detail = f"{type(exc).__name__}:{exc}"
            sample["source_status"]["cninfo"] = (
                f"{previous};download_error:{detail}"
                if previous
                else f"catalogue_error:{detail}"
            )

        exchange = "sse" if code.startswith("6") else "szse"
        try:
            records = client.query_exchange(
                code, "2024-01-01", "2025-06-30", "annual"
            )
            sample["source_status"][exchange] = f"catalogue_ok:{len(records)}"
            selected = newest_full_report(records)
            artifact = client.download(selected)
            sample["source_status"][exchange] += ";download_ok"
            sample["exchange_probe"] = {
                "selected": {
                    key: value for key, value in asdict(selected).items() if key != "raw"
                },
                "download": {
                    **asdict(artifact),
                    "record_path": str(artifact.record_path),
                    "blob_path": str(artifact.blob_path),
                },
                "same_sha256_as_primary": bool(
                    sample["primary"]
                    and artifact.sha256 == sample["primary"]["download"]["sha256"]
                ),
            }
        except Exception as exc:
            previous = sample["source_status"].get(exchange, "")
            detail = f"{type(exc).__name__}:{exc}"
            sample["source_status"][exchange] = (
                f"{previous};download_error:{detail}"
                if previous
                else f"catalogue_error:{detail}"
            )
        output["samples"][code] = sample

    report_path = PROJECT_ROOT / "run" / "filing_sources_smoke.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    print(f"report_path: {report_path}")

    probes = [
        item.get(key)
        for item in output["samples"].values()
        for key in ("primary", "exchange_probe")
    ]
    return 0 if all(probes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
