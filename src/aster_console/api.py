"""FastAPI adapter for the sanitised Aster Research Console snapshot."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .replay import ReplayService


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
REPLAY = ReplayService()


class RethinkRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)


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


async def replay_event_stream(session_id: str, interval_seconds: float = 1.0) -> AsyncIterator[str]:
    last_version = ""
    while True:
        try:
            session = await asyncio.to_thread(REPLAY.get_session, session_id)
            if session["version"] != last_version:
                yield f"event: replay\ndata: {json.dumps(session, ensure_ascii=False)}\n\n"
                last_version = session["version"]
            else:
                yield ": keep-alive\n\n"
        except KeyError:
            yield "event: replay-error\ndata: {\"error\":\"unknown session\"}\n\n"
            return
        await asyncio.sleep(interval_seconds)


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError):
        return HTTPException(status_code=404, detail=str(error).strip("'"))
    if isinstance(error, ValueError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=503, detail=f"{type(error).__name__}: {error}")


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

    @app.post("/api/replay/sessions")
    async def create_replay_session(automatic: bool = False, start_node: str | None = None) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(REPLAY.create_session, automatic, start_node)
        except Exception as error:
            raise _http_error(error) from error
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/replay/sessions/{session_id}")
    async def get_replay_session(session_id: str) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(REPLAY.get_session, session_id)
        except Exception as error:
            raise _http_error(error) from error
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.post("/api/replay/{session_id}/nodes/{node_id}/rethink")
    async def rethink_replay_node(
        session_id: str, node_id: str, request: RethinkRequest
    ) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(
                REPLAY.rethink, session_id, node_id, request.instruction
            )
        except Exception as error:
            raise _http_error(error) from error
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.post("/api/replay/{session_id}/nodes/{node_id}/accept")
    async def accept_replay_node(session_id: str, node_id: str) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(REPLAY.accept, session_id, node_id)
        except Exception as error:
            raise _http_error(error) from error
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.post("/api/replay/{session_id}/nodes/{node_id}/run")
    async def run_replay_node(session_id: str, node_id: str) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(REPLAY.run_node, session_id, node_id)
        except Exception as error:
            raise _http_error(error) from error
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.post("/api/replay/{session_id}/nodes/{node_id}/play")
    async def play_replay_node(session_id: str, node_id: str) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(
                REPLAY.set_playback, session_id, node_id, "playing"
            )
        except Exception as error:
            raise _http_error(error) from error
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.post("/api/replay/{session_id}/nodes/{node_id}/pause")
    async def pause_replay_node(session_id: str, node_id: str) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(
                REPLAY.set_playback, session_id, node_id, "paused"
            )
        except Exception as error:
            raise _http_error(error) from error
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/replay/{session_id}/events")
    async def replay_events(session_id: str) -> StreamingResponse:
        return StreamingResponse(
            replay_event_stream(session_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="console")
    else:
        @app.get("/")
        async def service_info() -> dict[str, str]:
            return {"service": "Aster Research Console", "frontend": "not built"}

    return app


app = create_app()

