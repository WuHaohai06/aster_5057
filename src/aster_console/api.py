"""FastAPI adapter for the sanitised Aster Research Console snapshot."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "apps/aster-console/dist"
EXPORTER_PATH = PROJECT_ROOT / "scripts/export_dashboard_snapshot.py"


def _load_exporter() -> Any:
    spec = importlib.util.spec_from_file_location("aster_dashboard_snapshot", EXPORTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load snapshot exporter: {EXPORTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXPORTER = _load_exporter()


def build_snapshot() -> dict[str, Any]:
    return EXPORTER.build_snapshot()


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    stable = dict(snapshot)
    stable["meta"] = {**snapshot.get("meta", {}), "generatedAt": ""}
    encoded = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


async def event_stream(interval_seconds: float = 5.0) -> AsyncIterator[str]:
    last_digest = ""
    while True:
        try:
            snapshot = await asyncio.to_thread(build_snapshot)
            digest = snapshot_digest(snapshot)
            if digest != last_digest:
                payload = json.dumps(
                    {"version": digest, "generatedAt": snapshot["meta"]["generatedAt"]},
                    ensure_ascii=False,
                )
                yield f"event: snapshot\ndata: {payload}\n\n"
                last_digest = digest
            else:
                yield ": keep-alive\n\n"
        except Exception as exc:  # keep existing clients alive during partial file writes
            payload = json.dumps({"type": type(exc).__name__}, ensure_ascii=False)
            yield f"event: snapshot-error\ndata: {payload}\n\n"
        await asyncio.sleep(interval_seconds)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Aster Research Console",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        snapshot = await asyncio.to_thread(build_snapshot)
        return {
            "status": "ok",
            "schema": snapshot["meta"]["schema"],
            "version": snapshot_digest(snapshot),
            "generatedAt": snapshot["meta"]["generatedAt"],
        }

    @app.get("/api/snapshot")
    async def snapshot() -> JSONResponse:
        payload = await asyncio.to_thread(build_snapshot)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="console")
    else:
        @app.get("/")
        async def service_info() -> dict[str, str]:
            return {"service": "Aster Research Console", "frontend": "not built"}

    return app


app = create_app()

