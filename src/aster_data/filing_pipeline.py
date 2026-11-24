"""Resumable filing download and evidence-preserving PDF parsing jobs."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from .filing_sources import OfficialFilingClient
from .io import instrument_from_code, sha256_file, write_bytes_atomic, write_json_atomic


def universe_codes(universe_path: Path) -> list[str]:
    frame = pd.read_parquet(universe_path)
    if "instrument" not in frame:
        raise ValueError("universe artifact has no instrument column")
    return sorted({instrument_from_code(value)[2:] for value in frame["instrument"]})


def download_filings_bulk(
    *,
    project_root: Path,
    universe_path: Path,
    start: str,
    end: str,
    report_types: Iterable[str] = ("annual",),
    verify_exchange: bool = False,
    request_delay: float = 1.5,
    limit: int | None = None,
) -> dict:
    """Download all full reports returned by CNINFO, with exchange gap fallback."""

    client = OfficialFilingClient(project_root)
    codes = universe_codes(universe_path)
    if limit is not None:
        codes = codes[:limit]
    report_types = tuple(report_types)
    status_path = project_root / "data" / "raw" / "filings" / "bulk_status.json"
    failures_path = project_root / "data" / "raw" / "filings" / "bulk_failures.jsonl"
    completed = downloaded = skipped = failures = 0
    for code in codes:
        for report_type in report_types:
            response_marker = (
                project_root / "data" / "raw" / "filings" / "responses" / "cninfo"
                / f"{code}_{report_type}_{start}_{end}.json"
            )
            try:
                records, sources = client.search_with_fallback(
                    code, start, end, report_type, verify_exchange=verify_exchange
                )
                for record in records:
                    if not record.is_full_report:
                        continue
                    record_path = (
                        project_root / "data" / "raw" / "filings" / "records"
                        / record.source / code / f"{record.announcement_id}.json"
                    )
                    if record_path.exists():
                        skipped += 1
                    else:
                        client.download(record)
                        downloaded += 1
                completed += 1
            except Exception as exc:  # keep the batch resumable across source outages
                failures += 1
                line = json.dumps(
                    {
                        "code": code,
                        "report_type": report_type,
                        "error": f"{type(exc).__name__}: {exc}",
                        "at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                    },
                    ensure_ascii=False,
                ) + "\n"
                failures_path.parent.mkdir(parents=True, exist_ok=True)
                with failures_path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
            payload = {
                "state": "running",
                "codes": len(codes),
                "report_types": list(report_types),
                "jobs_total": len(codes) * len(report_types),
                "jobs_completed": completed,
                "downloaded": downloaded,
                "skipped": skipped,
                "failures": failures,
                "last_code": code,
                "last_response_exists": response_marker.exists(),
                "updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            }
            write_json_atomic(status_path, payload)
            if request_delay:
                time.sleep(request_delay)
    payload["state"] = "complete"
    write_json_atomic(status_path, payload)
    return payload


def parse_filing_records(
    *, project_root: Path, limit: int | None = None, minimum_chars_per_page: int = 80
) -> dict:
    """Turn immutable PDFs into page-addressable JSON and Markdown.

    PyPDF is the dependable baseline. Documents with weak text extraction are
    explicitly marked ``needs_ocr`` so MinerU can be applied selectively later.
    """

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Install pypdf from requirements-data.txt") from exc

    records = sorted((project_root / "data" / "raw" / "filings" / "records").rglob("*.json"))
    if limit is not None:
        records = records[:limit]
    parsed_root = project_root / "data" / "curated" / "filings_ai"
    seen: set[str] = set()
    parsed = skipped = failed = 0
    for record_path in records:
        metadata = json.loads(record_path.read_text(encoding="utf-8"))
        digest = metadata["sha256"]
        if digest in seen:
            skipped += 1
            continue
        seen.add(digest)
        source_pdf = project_root / "data" / "raw" / "filings" / metadata["blob"]
        target_dir = parsed_root / metadata["security_code"] / digest
        json_path = target_dir / "document.json"
        markdown_path = target_dir / "document.md"
        if json_path.exists() and markdown_path.exists():
            skipped += 1
            continue
        try:
            reader = PdfReader(source_pdf)
            pages = []
            markdown = [
                "---",
                f"security_code: {metadata['security_code']}",
                f"announcement_time: {metadata['announcement_time']}",
                f"source_sha256: {digest}",
                "parser: pypdf-baseline",
                "---",
                "",
                f"# {metadata['title']}",
            ]
            for number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").replace("\x00", "").strip()
                pages.append({"page": number, "text": text, "characters": len(text)})
                markdown.extend(["", f"## Page {number}", "", text])
            average = sum(item["characters"] for item in pages) / max(1, len(pages))
            quality = "needs_ocr" if average < minimum_chars_per_page else "text_extracted"
            payload = {
                "schema": "aster-filing-ai-v1",
                "security_code": metadata["security_code"],
                "instrument": instrument_from_code(metadata["security_code"]),
                "title": metadata["title"],
                "report_type": metadata["report_type"],
                "announcement_time": metadata["announcement_time"],
                "available_at": metadata["announcement_time"],
                "source": metadata["source"],
                "source_record": str(record_path.resolve()),
                "source_pdf": str(source_pdf.resolve()),
                "source_sha256": digest,
                "source_hash_verified": sha256_file(source_pdf) == digest,
                "parser": "pypdf-baseline",
                "quality": quality,
                "page_count": len(pages),
                "average_characters_per_page": average,
                "pages": pages,
            }
            write_json_atomic(json_path, payload)
            write_bytes_atomic(markdown_path, ("\n".join(markdown) + "\n").encode("utf-8"))
            parsed += 1
        except Exception as exc:
            failed += 1
            write_json_atomic(
                target_dir / "error.json",
                {"source_sha256": digest, "error": f"{type(exc).__name__}: {exc}"},
            )
    manifest = {
        "dataset": "aster-filing-ai-v1",
        "record_files": len(records),
        "unique_documents": len(seen),
        "parsed": parsed,
        "skipped": skipped,
        "failed": failed,
        "parser_policy": "pypdf baseline; needs_ocr documents route to MinerU manually",
    }
    write_json_atomic(parsed_root / "manifest.json", manifest)
    return manifest
