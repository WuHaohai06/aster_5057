"""Parallel, resumable annual-report parsing and citation-validated LLM factors."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from filelock import FileLock, Timeout

from .filing_text_factors import _llm_payload
from .io import instrument_from_code, sha256_file, write_bytes_atomic, write_json_atomic


LOGGER = logging.getLogger("aster_data.filing_factor_batch")
FACTOR_ID_MAP = {
    "llm_management_outlook": "filing_management_outlook",
    "llm_demand_strength": "filing_demand_strength",
    "llm_margin_pressure": "filing_margin_pressure",
    "llm_capex_intensity": "filing_investment_intensity",
    "llm_risk_level": "filing_uncertainty",
}


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def fiscal_year(title: str) -> int | None:
    value = str(title)
    if "半年度报告" in value:
        return None
    match = re.search(r"(20\d{2})\s*年?[\s_]*年度报告", value)
    return int(match.group(1)) if match else None


def discover_records(project_root: Path, year: int) -> list[dict]:
    unique: dict[str, dict] = {}
    record_root = project_root / "data" / "raw" / "filings" / "records"
    for path in record_root.rglob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        digest = payload.get("sha256")
        if digest and fiscal_year(payload.get("title", "")) == year:
            payload["record_path"] = str(path.resolve())
            unique[digest] = payload
    return sorted(unique.values(), key=lambda item: (item.get("security_code", ""), item["sha256"]))


def _parse_one(project_root_text: str, metadata: dict, minimum_chars: int) -> dict:
    from pypdf import PdfReader

    project_root = Path(project_root_text)
    digest = metadata["sha256"]
    target_dir = project_root / "data" / "curated" / "filings_ai" / metadata["security_code"] / digest
    json_path = target_dir / "document.json"
    markdown_path = target_dir / "document.md"
    if json_path.exists() and markdown_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        return {
            "digest": digest, "status": "skipped", "quality": payload.get("quality"),
            "pages": payload.get("page_count", 0), "document": str(json_path),
        }
    try:
        source_pdf = project_root / "data" / "raw" / "filings" / metadata["blob"]
        reader = PdfReader(source_pdf)
        pages = []
        markdown = [
            "---", f"security_code: {metadata['security_code']}",
            f"announcement_time: {metadata['announcement_time']}",
            f"source_sha256: {digest}", "parser: pypdf-baseline", "---", "",
            f"# {metadata['title']}",
        ]
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").replace("\x00", "").strip()
            pages.append({"page": number, "text": text, "characters": len(text)})
            markdown.extend(["", f"## Page {number}", "", text])
        average = sum(item["characters"] for item in pages) / max(1, len(pages))
        quality = "needs_ocr" if average < minimum_chars else "text_extracted"
        payload = {
            "schema": "aster-filing-ai-v1",
            "security_code": metadata["security_code"],
            "instrument": instrument_from_code(metadata["security_code"]),
            "title": metadata["title"],
            "fiscal_year": fiscal_year(metadata["title"]),
            "report_type": metadata["report_type"],
            "announcement_time": metadata["announcement_time"],
            "available_at": metadata["announcement_time"],
            "source": metadata["source"],
            "source_record": metadata["record_path"],
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
        return {
            "digest": digest, "status": "parsed", "quality": quality,
            "pages": len(pages), "document": str(json_path),
        }
    except Exception as error:
        return {"digest": digest, "status": "failed", "error": f"{type(error).__name__}: {error}"}


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def _score_one(
    document_path_text: str,
    output_root_text: str,
    api_key: str,
    base_url: str,
    model: str,
    retries: int,
) -> dict:
    document_path = Path(document_path_text)
    output_root = Path(output_root_text)
    document = json.loads(document_path.read_text(encoding="utf-8"))
    digest = document["source_sha256"]
    checkpoint = output_root / "checkpoints" / f"{digest}.json"
    if checkpoint.exists():
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        return {"digest": digest, "status": "skipped", **payload}
    last_error = "not attempted"
    for attempt in range(1, retries + 1):
        try:
            rows, evidence = _llm_payload(
                document, api_key=api_key, base_url=base_url, model=model
            )
            for row in rows:
                row["factor_id"] = FACTOR_ID_MAP.get(row["factor_id"], row["factor_id"])
                row["factor_group"] = "filing_analysis"
                row["version"] = "aster-filing-analysis-v1"
            columns = [
                "date", "available_at", "instrument", "factor_id", "factor_group",
                "value", "origin", "source_id", "version",
            ]
            frame = pd.DataFrame(rows, columns=columns)
            artifact = output_root / "documents" / f"{digest}.parquet"
            _write_parquet_atomic(artifact, frame)
            write_json_atomic(output_root / "evidence" / f"{digest}.json", {
                "source_document": str(document_path.resolve()),
                "source_sha256": digest,
                "fiscal_year": document.get("fiscal_year"),
                **evidence,
            })
            usage = evidence.get("usage") or {}
            result = {
                "rows": len(frame), "usage": usage, "artifact": str(artifact.resolve()),
                "completed_at": _now(),
            }
            write_json_atomic(checkpoint, result)
            return {"digest": digest, "status": "scored", **result}
        except Exception as error:
            last_error = f"{type(error).__name__}: {error}"
            if attempt < retries:
                delay = min(300, 20 * (2 ** (attempt - 1)))
                time.sleep(delay)
    return {"digest": digest, "status": "failed", "error": last_error}


class AnnualFilingFactorBatch:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project_root = Path(args.project_root).resolve()
        self.run_root = self.project_root / "run" / f"filing_factor_{args.year}"
        self.output_root = (
            self.project_root / "data" / "curated" / "factors" / "filing_analysis" / str(args.year)
        )
        self.status_path = self.run_root / "status.json"
        self.failures_path = self.run_root / "failures.json"
        self.failures: dict[str, dict] = {}

    def status(self, state: str, **values) -> None:
        write_json_atomic(self.status_path, {
            "pid": os.getpid(), "state": state, "fiscal_year": self.args.year,
            "parse_workers": self.args.parse_workers, "llm_workers": self.args.llm_workers,
            "updated_at": _now(), **values,
        })

    def run(self) -> None:
        records = discover_records(self.project_root, self.args.year)
        total = len(records)
        self.status("parsing", documents_total=total, parse_completed=0, score_completed=0)
        parse_completed = needs_ocr = 0
        document_paths: list[str] = []
        with ProcessPoolExecutor(max_workers=self.args.parse_workers) as executor:
            futures = {
                executor.submit(_parse_one, str(self.project_root), item, self.args.minimum_chars): item
                for item in records
            }
            for future in as_completed(futures):
                result = future.result()
                parse_completed += 1
                if result["status"] == "failed":
                    self.failures[f"parse:{result['digest']}"] = result
                else:
                    document_paths.append(result["document"])
                    needs_ocr += int(result.get("quality") == "needs_ocr")
                self.status(
                    "parsing", documents_total=total, parse_completed=parse_completed,
                    parse_failures=sum(key.startswith("parse:") for key in self.failures),
                    needs_ocr=needs_ocr, score_completed=0, current=result["digest"],
                )
        write_json_atomic(self.failures_path, self.failures)

        api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY or OPENAI_API_KEY is required")
        score_completed = factor_rows = 0
        token_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.status(
            "scoring", documents_total=total, parse_completed=parse_completed,
            parse_failures=sum(key.startswith("parse:") for key in self.failures),
            needs_ocr=needs_ocr, score_total=len(document_paths), score_completed=0,
            token_usage=token_totals,
        )
        with ThreadPoolExecutor(max_workers=self.args.llm_workers) as executor:
            futures = {
                executor.submit(
                    _score_one, path, str(self.output_root), api_key,
                    self.args.base_url, self.args.model, self.args.retries,
                ): path for path in document_paths
            }
            for future in as_completed(futures):
                result = future.result()
                score_completed += 1
                if result["status"] == "failed":
                    self.failures[f"score:{result['digest']}"] = result
                else:
                    factor_rows += int(result.get("rows", 0))
                    for field in token_totals:
                        value = (result.get("usage") or {}).get(field)
                        if value is not None:
                            token_totals[field] += int(value)
                write_json_atomic(self.failures_path, self.failures)
                self.status(
                    "scoring", documents_total=total, parse_completed=parse_completed,
                    parse_failures=sum(key.startswith("parse:") for key in self.failures),
                    needs_ocr=needs_ocr, score_total=len(document_paths),
                    score_completed=score_completed,
                    score_failures=sum(key.startswith("score:") for key in self.failures),
                    factor_rows=factor_rows, token_usage=token_totals,
                    current=result["digest"],
                )

        parts = []
        for path in sorted((self.output_root / "documents").glob("*.parquet")):
            frame = pd.read_parquet(path)
            if not frame.empty:
                parts.append(frame)
        combined = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        aggregate = self.output_root / f"filing_factors_{self.args.year}.parquet"
        _write_parquet_atomic(aggregate, combined)
        manifest = {
            "dataset": "aster-filing-analysis-v1", "fiscal_year": self.args.year,
            "documents_total": total, "documents_scored": score_completed,
            "factor_rows": len(combined), "factor_ids": (
                sorted(combined["factor_id"].unique()) if not combined.empty else []
            ),
            "needs_ocr": needs_ocr, "failures": len(self.failures),
            "token_usage": token_totals, "path": str(aggregate.resolve()),
            "sha256": sha256_file(aggregate), "completed_at": _now(),
        }
        write_json_atomic(self.output_root / "manifest.json", manifest)
        self.status("complete", **manifest)


def _setup_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    for handler in (logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        LOGGER.addHandler(handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--parse-workers", type=int, default=6)
    parser.add_argument("--llm-workers", type=int, default=8)
    parser.add_argument("--minimum-chars", type=int, default=80)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-flash")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = args.project_root.resolve()
    run_root = project_root / "run" / f"filing_factor_{args.year}"
    run_root.mkdir(parents=True, exist_ok=True)
    _setup_logging(project_root / "logs" / f"filing_factor_{args.year}.log")
    lock = FileLock(str(run_root / "pipeline.lock"))
    try:
        with lock.acquire(timeout=0):
            AnnualFilingFactorBatch(args).run()
    except Timeout:
        raise SystemExit(f"another fiscal-year {args.year} filing job is already running")


if __name__ == "__main__":
    main()
