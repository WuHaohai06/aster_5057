"""Official-source adapters for immutable Chinese A-share filing archives.

CNINFO is the primary catalogue.  Exchange catalogues are deliberately kept
as independent adapters so they can validate CNINFO and fill source-specific
gaps without changing the identity or availability time of a filing.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests


CNINFO_BASE = "https://www.cninfo.com.cn"
CNINFO_STATIC_BASE = "https://static.cninfo.com.cn/"
SSE_BASE = "https://www.sse.com.cn"
SZSE_STATIC_BASE = "https://disc.static.szse.cn/download/"

REPORT_CATEGORIES = {
    "annual": "category_ndbg_szsh",
    "semiannual": "category_bndbg_szsh",
    "q1": "category_yjdbg_szsh",
    "q3": "category_sjdbg_szsh",
    "correction": "category_bcgz_szsh",
}


def _clean_title(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def _exchange_for(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return "sse"
    if code.startswith(("0", "1", "2", "3")):
        return "szse"
    if code.startswith(("4", "8")):
        return "bse"
    raise ValueError(f"Cannot infer exchange for A-share code {code!r}")


def _is_full_report(title: str) -> bool:
    title = _clean_title(title)
    excluded = ("摘要", "英文版", "取消", "提示性公告")
    return "报告" in title and not any(marker in title for marker in excluded)


def _matches_report_type(title: str, report_type: str) -> bool:
    title = _clean_title(title)
    if report_type == "annual":
        return "年度报告" in title or bool(re.search(r"\d{4}年年报", title))
    if report_type == "semiannual":
        return "半年度报告" in title or "中期报告" in title
    if report_type == "q1":
        return "第一季度报告" in title or "一季度报告" in title
    if report_type == "q3":
        return "第三季度报告" in title or "三季度报告" in title
    if report_type == "correction":
        return any(marker in title for marker in ("更正", "修订", "补充"))
    return False


def _cninfo_time(value: Any) -> str:
    if value in (None, ""):
        return ""
    timestamp = float(value) / 1000.0
    return (
        datetime.fromtimestamp(timestamp, tz=UTC)
        .astimezone(ZoneInfo("Asia/Shanghai"))
        .isoformat(timespec="seconds")
    )


@dataclass(frozen=True)
class FilingRecord:
    source: str
    exchange: str
    security_code: str
    security_name: str
    announcement_id: str
    title: str
    announcement_time: str
    document_url: str
    report_type: str
    is_full_report: bool
    raw: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class DownloadedFiling:
    record_path: Path
    blob_path: Path
    sha256: str
    byte_count: int


class SourceUnavailable(RuntimeError):
    """A source could not be queried without invalidating other sources."""


class OfficialFilingClient:
    def __init__(
        self,
        project_root: Path | None = None,
        *,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.raw_root = self.project_root / "data" / "raw" / "filings"
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/131 Safari/537.36 "
                    "AsterResearch/0.1"
                ),
                "Accept": "application/json,text/plain,*/*",
            }
        )
        self._cninfo_org_ids: dict[str, str] | None = None

    def query_cninfo(
        self,
        code: str,
        start: str,
        end: str,
        report_type: str = "annual",
    ) -> list[FilingRecord]:
        """Query CNINFO and retain every raw announcement field."""

        if report_type not in REPORT_CATEGORIES:
            raise ValueError(f"Unsupported report type: {report_type}")
        org_ids = self._get_cninfo_org_ids()
        if code not in org_ids:
            raise SourceUnavailable(f"CNINFO current stock map has no orgId for {code}")

        endpoint = f"{CNINFO_BASE}/new/hisAnnouncement/query"
        headers = {
            "Origin": CNINFO_BASE,
            "Referer": (
                f"{CNINFO_BASE}/new/commonUrl/pageOfSearch?"
                "url=disclosure/list/search"
            ),
        }
        payload = {
            "pageNum": 1,
            "pageSize": 30,
            "column": "szse",
            "tabName": "fulltext",
            "plate": "",
            "stock": f"{code},{org_ids[code]}",
            "searchkey": "",
            "secid": "",
            "category": REPORT_CATEGORIES[report_type],
            "trade": "",
            "seDate": f"{start}~{end}",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        first = self._post_json(endpoint, data=payload, headers=headers, source="cninfo")
        total = int(first.get("totalAnnouncement") or 0)
        pages = max(1, (total + 29) // 30)
        announcements = list(first.get("announcements") or [])
        for page in range(2, pages + 1):
            payload["pageNum"] = page
            response = self._post_json(
                endpoint, data=payload, headers=headers, source="cninfo"
            )
            announcements.extend(response.get("announcements") or [])

        self._write_query_response(
            "cninfo", code, start, end, report_type, {"announcements": announcements}
        )
        records: list[FilingRecord] = []
        for item in announcements:
            adjunct = item.get("adjunctUrl") or ""
            if not adjunct:
                continue
            title = _clean_title(item.get("announcementTitle") or "")
            records.append(
                FilingRecord(
                    source="cninfo",
                    exchange=_exchange_for(code),
                    security_code=str(item.get("secCode") or code),
                    security_name=str(item.get("secName") or ""),
                    announcement_id=str(item.get("announcementId") or adjunct),
                    title=title,
                    announcement_time=_cninfo_time(item.get("announcementTime")),
                    document_url=urljoin(CNINFO_STATIC_BASE, adjunct.lstrip("/")),
                    report_type=report_type,
                    is_full_report=_is_full_report(title),
                    raw=item,
                )
            )
        return records

    def query_exchange(
        self,
        code: str,
        start: str,
        end: str,
        report_type: str = "annual",
    ) -> list[FilingRecord]:
        exchange = _exchange_for(code)
        if exchange == "sse":
            return self._query_sse(code, start, end, report_type)
        if exchange == "szse":
            return self._query_szse(code, start, end, report_type)
        raise SourceUnavailable("BSE fallback is not implemented in this first slice")

    def search_with_fallback(
        self,
        code: str,
        start: str,
        end: str,
        report_type: str = "annual",
        *,
        verify_exchange: bool = False,
    ) -> tuple[list[FilingRecord], dict[str, str]]:
        """Use CNINFO first and query the exchange only on gaps or verification."""

        status: dict[str, str] = {}
        try:
            primary = self.query_cninfo(code, start, end, report_type)
            status["cninfo"] = f"ok:{len(primary)}"
        except Exception as exc:
            primary = []
            status["cninfo"] = f"error:{type(exc).__name__}:{exc}"

        full_primary = [record for record in primary if record.is_full_report]
        fallback: list[FilingRecord] = []
        if verify_exchange or not full_primary:
            exchange = _exchange_for(code)
            try:
                fallback = self.query_exchange(code, start, end, report_type)
                status[exchange] = f"ok:{len(fallback)}"
            except Exception as exc:
                status[exchange] = f"error:{type(exc).__name__}:{exc}"
        return (primary if full_primary else fallback), status

    def download(self, record: FilingRecord) -> DownloadedFiling:
        """Download and validate a PDF, then store it as an immutable blob."""

        try:
            response = self.session.get(
                record.document_url,
                headers={"Referer": self._referer_for(record.source)},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SourceUnavailable(
                f"{record.source} PDF download failed: {type(exc).__name__}: {exc}"
            ) from exc
        content = response.content
        if not content.startswith(b"%PDF-"):
            content_type = response.headers.get("Content-Type", "")
            raise SourceUnavailable(
                f"Expected PDF from {record.document_url}, got {content_type!r} "
                f"with prefix {content[:16]!r}"
            )
        digest = hashlib.sha256(content).hexdigest()
        blob = self.raw_root / "blobs" / "sha256" / digest[:2] / f"{digest}.pdf"
        self._atomic_write_bytes(blob, content)

        record_path = (
            self.raw_root
            / "records"
            / record.source
            / record.security_code
            / f"{record.announcement_id}.json"
        )
        payload = {
            **asdict(record),
            "sha256": digest,
            "byte_count": len(content),
            "blob": blob.relative_to(self.raw_root).as_posix(),
            "retrieved_at": datetime.now(tz=ZoneInfo("Asia/Shanghai")).isoformat(
                timespec="seconds"
            ),
        }
        self._atomic_write_json(record_path, payload)
        return DownloadedFiling(record_path, blob, digest, len(content))

    def _get_cninfo_org_ids(self) -> dict[str, str]:
        if self._cninfo_org_ids is not None:
            return self._cninfo_org_ids
        url = f"{CNINFO_BASE}/new/data/szse_stock.json"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            rows = response.json()["stockList"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise SourceUnavailable(f"CNINFO stock map failed: {exc}") from exc
        self._cninfo_org_ids = {
            str(row["code"]): str(row["orgId"])
            for row in rows
            if row.get("code") and row.get("orgId")
        }
        return self._cninfo_org_ids

    def _query_sse(
        self, code: str, start: str, end: str, report_type: str
    ) -> list[FilingRecord]:
        endpoint = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
        params = {
            "isPagination": "true",
            "productId": code,
            "keyWord": "",
            "securityType": "0101,120100,020100,020200,120200",
            "reportType2": "DQBG",
            "reportType": "ALL",
            "beginDate": start,
            "endDate": end,
            "pageHelp.pageSize": 100,
            "pageHelp.pageNo": 1,
            "pageHelp.beginPage": 1,
            "pageHelp.endPage": 1,
            "pageHelp.cacheSize": 1,
        }
        headers = {
            "Referer": (
                f"{SSE_BASE}/assortment/stock/list/info/announcement/index.shtml?"
                f"productId={code}"
            )
        }
        response = self._get_json(endpoint, params=params, headers=headers, source="sse")
        rows = ((response.get("pageHelp") or {}).get("data") or [])
        self._write_query_response("sse", code, start, end, report_type, response)
        records: list[FilingRecord] = []
        for item in rows:
            title = _clean_title(item.get("TITLE") or "")
            url = item.get("URL") or ""
            if not url or not _matches_report_type(title, report_type):
                continue
            records.append(
                FilingRecord(
                    source="sse",
                    exchange="sse",
                    security_code=str(item.get("SECURITY_CODE") or code),
                    security_name=str(item.get("SECURITY_NAME") or ""),
                    announcement_id=Path(url).stem,
                    title=title,
                    announcement_time=str(item.get("ADDDATE") or item.get("SSEDATE") or ""),
                    document_url=urljoin(SSE_BASE, url),
                    report_type=report_type,
                    is_full_report=_is_full_report(title),
                    raw=item,
                )
            )
        return records

    def _query_szse(
        self, code: str, start: str, end: str, report_type: str
    ) -> list[FilingRecord]:
        endpoint = "https://www.szse.cn/api/disc/announcement/annList"
        payload = {
            "seDate": [start, end],
            "stock": [code],
            "channelCode": ["listedNotice_disc"],
            "bigCategoryId": ["010301"],
            "pageSize": 100,
            "pageNum": 1,
        }
        headers = {
            "Content-Type": "application/json",
            "Referer": "https://www.szse.cn/disclosure/listed/notice/index.html",
        }
        response = self._post_json(
            endpoint,
            params={"random": "0.3141592653589793"},
            json=payload,
            headers=headers,
            source="szse",
        )
        rows = response.get("data") or []
        self._write_query_response("szse", code, start, end, report_type, response)
        records: list[FilingRecord] = []
        for item in rows:
            title = _clean_title(item.get("title") or "")
            path = item.get("attachPath") or ""
            if not path or not _matches_report_type(title, report_type):
                continue
            sec_codes = item.get("secCode") or [code]
            sec_names = item.get("secName") or [""]
            records.append(
                FilingRecord(
                    source="szse",
                    exchange="szse",
                    security_code=str(sec_codes[0] if isinstance(sec_codes, list) else sec_codes),
                    security_name=str(sec_names[0] if isinstance(sec_names, list) else sec_names),
                    announcement_id=str(item.get("id") or Path(path).stem),
                    title=title,
                    announcement_time=str(item.get("publishTime") or ""),
                    document_url=urljoin(SZSE_STATIC_BASE, path.lstrip("/")),
                    report_type=report_type,
                    is_full_report=_is_full_report(title),
                    raw=item,
                )
            )
        return records

    def _get_json(self, url: str, *, source: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.session.get(url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SourceUnavailable(f"{source} query failed: {type(exc).__name__}: {exc}") from exc

    def _post_json(self, url: str, *, source: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.session.post(url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SourceUnavailable(f"{source} query failed: {type(exc).__name__}: {exc}") from exc

    def _write_query_response(
        self,
        source: str,
        code: str,
        start: str,
        end: str,
        report_type: str,
        payload: dict[str, Any],
    ) -> None:
        path = (
            self.raw_root
            / "responses"
            / source
            / f"{code}_{report_type}_{start}_{end}.json"
        )
        self._atomic_write_json(path, payload)

    @staticmethod
    def _referer_for(source: str) -> str:
        if source == "cninfo":
            return f"{CNINFO_BASE}/"
        if source == "sse":
            return f"{SSE_BASE}/"
        return "https://www.szse.cn/"

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        os.replace(temporary, path)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)


def newest_full_report(records: Iterable[FilingRecord]) -> FilingRecord:
    full = [record for record in records if record.is_full_report]
    if not full:
        raise SourceUnavailable("No full report found in query result")
    return max(full, key=lambda record: (record.announcement_time, record.announcement_id))
