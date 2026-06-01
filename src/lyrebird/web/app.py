"""FastAPI app — REST + SSE for the multi-agent pipeline.

Endpoints:
    GET  /                              static SPA entry
    GET  /static/*                       static assets
    GET  /api/sample-resume               returns resume.redacted.md text
    POST /api/runs                        starts a new pipeline run
    GET  /api/runs                        lists active + recent runs
    GET  /api/runs/{run_id}               metadata + status
    GET  /api/runs/{run_id}/snapshot      all events so far (after_seq optional)
    GET  /api/runs/{run_id}/events        SSE stream of events
    GET  /api/runs/{run_id}/report        final ExtractionReport (404 if not done)
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from lyrebird.i18n import I18nRegistry, negotiate_locale
from lyrebird.observability import EventType
from lyrebird.web.registry import RunRegistry

log = logging.getLogger(__name__)

# Project layout discovery
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILLS_ROOT = PROJECT_ROOT / "skills"
ARTIFACTS_ROOT = PROJECT_ROOT / "artifacts"
RUNS_ROOT = PROJECT_ROOT / "runs"
WEB_ROOT = Path(__file__).resolve().parent / "static"
SAMPLE_RESUME = PROJECT_ROOT / "resume.redacted.md"
I18N_ROOT = Path(__file__).resolve().parents[1] / "i18n" / "locales"

LANG_COOKIE_NAME = "lyrebird_lang"
LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


# ---------- request / response schemas ----------

class StartRunRequest(BaseModel):
    resume_text: str = Field(min_length=80, max_length=200_000)
    target_role: Optional[str] = Field(default=None, max_length=200)
    candidate_id: str = Field(default="cand_user", max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    turns: int = Field(default=6, ge=2, le=12)
    min_incidents: int = Field(default=3, ge=1, le=10)


class StartRunResponse(BaseModel):
    run_id: str
    status: str
    events_url: str
    snapshot_url: str
    report_url: str


class RunInfo(BaseModel):
    run_id: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    params: dict
    error: Optional[str] = None


# ---------- lifespan: create registry, shut it down cleanly ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        log.warning(
            "DEEPSEEK_API_KEY not set in env — runs will fail at LLM call time. "
            "Set it in .env before starting the server."
        )
    registry = RunRegistry(
        skills_root=SKILLS_ROOT,
        artifact_root=ARTIFACTS_ROOT,
        runs_root=RUNS_ROOT,
    )
    app.state.registry = registry
    app.state.i18n = I18nRegistry(root=I18N_ROOT, default="zh")
    log.info("Lyrebird API ready. skills=%s artifacts=%s runs=%s i18n=%s",
             SKILLS_ROOT, ARTIFACTS_ROOT, RUNS_ROOT,
             app.state.i18n.available())
    try:
        yield
    finally:
        registry.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Lyrebird",
        description="Multi-agent cognitive mechanism extraction system",
        version="0.2.0",
        lifespan=lifespan,
    )

    # ---------- API routes ----------

    @app.get("/api/i18n/locales")
    def i18n_locales(request: Request):
        """List available locales with their display names + the negotiated current."""
        i18n: I18nRegistry = request.app.state.i18n
        items = []
        for code in i18n.available():
            entries = i18n.get(code)
            items.append({
                "code": code,
                "name": entries.get("meta.lang_name", code),
                "native": entries.get("meta.lang_native", code),
                "html_lang": entries.get("meta.html_lang", code),
            })
        current = _resolve_locale(request, i18n)
        return {"default": i18n.default, "current": current, "locales": items}

    @app.get("/api/i18n/{locale}")
    def i18n_strings(locale: str, request: Request, response: Response):
        """Return the flat string table for a locale. Sets cookie so the choice persists."""
        i18n: I18nRegistry = request.app.state.i18n
        if locale not in i18n.available():
            # Fallback to default but signal it
            chosen = i18n.default
            response.headers["X-Lyrebird-Fallback"] = "true"
        else:
            chosen = locale
        # Persist user's explicit pick
        response.set_cookie(
            LANG_COOKIE_NAME, chosen,
            max_age=LANG_COOKIE_MAX_AGE,
            samesite="lax",
            httponly=False,  # readable from JS for UI sync
        )
        return {
            "locale": chosen,
            "strings": i18n.get(chosen),
        }

    @app.get("/api/sample-resume")
    def sample_resume():
        if not SAMPLE_RESUME.exists():
            raise HTTPException(404, "sample resume not found")
        return {"resume_text": SAMPLE_RESUME.read_text(encoding="utf-8")}

    @app.post("/api/runs", response_model=StartRunResponse)
    def start_run(req: StartRunRequest, request: Request):
        registry: RunRegistry = request.app.state.registry
        handle = registry.start_run(
            resume_text=req.resume_text,
            target_role=req.target_role,
            candidate_id=req.candidate_id,
            turns=req.turns,
            min_incidents=req.min_incidents,
        )
        return StartRunResponse(
            run_id=handle.run_id,
            status=handle.status,
            events_url=f"/api/runs/{handle.run_id}/events",
            snapshot_url=f"/api/runs/{handle.run_id}/snapshot",
            report_url=f"/api/runs/{handle.run_id}/report",
        )

    @app.get("/api/runs", response_model=list[RunInfo])
    def list_runs(request: Request):
        registry: RunRegistry = request.app.state.registry
        return [
            RunInfo(
                run_id=h.run_id,
                status=h.status,
                started_at=h.started_at.isoformat(),
                finished_at=h.finished_at.isoformat() if h.finished_at else None,
                params=h.params,
                error=h.error,
            )
            for h in registry.list_runs()
        ]

    @app.get("/api/runs/{run_id}", response_model=RunInfo)
    def get_run(run_id: str, request: Request):
        registry: RunRegistry = request.app.state.registry
        h = registry.get(run_id)
        if h is None:
            raise HTTPException(404, "run not found")
        return RunInfo(
            run_id=h.run_id,
            status=h.status,
            started_at=h.started_at.isoformat(),
            finished_at=h.finished_at.isoformat() if h.finished_at else None,
            params=h.params,
            error=h.error,
        )

    @app.get("/api/runs/{run_id}/snapshot")
    def get_snapshot(run_id: str, request: Request, after_seq: int = 0):
        registry: RunRegistry = request.app.state.registry
        h = registry.get(run_id)
        if h is None:
            raise HTTPException(404, "run not found")
        return {
            "run_id": run_id,
            "status": h.status,
            "events": [e.to_dict() for e in h.bus.snapshot(after_seq=after_seq)],
        }

    @app.get("/api/runs/{run_id}/report")
    def get_report(run_id: str, request: Request):
        registry: RunRegistry = request.app.state.registry
        h = registry.get(run_id)
        if h is None:
            raise HTTPException(404, "run not found")
        if h.result is None:
            if h.error:
                raise HTTPException(500, f"run failed: {h.error}")
            raise HTTPException(409, "run not yet complete")
        return h.result.report.model_dump(mode="json")

    @app.get("/api/runs/{run_id}/events")
    async def stream_events(run_id: str, request: Request, last_event_id: int = 0):
        registry: RunRegistry = request.app.state.registry
        h = registry.get(run_id)
        if h is None:
            raise HTTPException(404, "run not found")

        # Browsers auto-reconnect with the Last-Event-ID header set to the last
        # `id:` field they received. Honor it so we don't double-deliver on reconnect.
        header_leid = request.headers.get("last-event-id")
        if header_leid:
            try:
                last_event_id = max(last_event_id, int(header_leid))
            except ValueError:
                pass

        async def event_gen():
            # Replay anything the client may have missed
            for ev in h.bus.snapshot(after_seq=last_event_id):
                if await request.is_disconnected():
                    return
                yield {
                    "id": str(ev.seq),
                    "event": ev.type.value,
                    "data": ev.model_dump_json() if hasattr(ev, "model_dump_json") else _ev_to_json(ev),
                }
            # If terminated already, close
            if h.bus.is_terminal():
                return

            # Now wait for new events. Subscribe is thread-safe.
            sub = h.bus.subscribe()
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        # Bridge sync queue -> async with to_thread
                        ev = await asyncio.to_thread(sub.get, True, 1.0)
                    except Exception:
                        # Queue.Empty (timeout) — keep looping so we can check disconnect
                        if h.bus.is_terminal():
                            return
                        continue
                    yield {
                        "id": str(ev.seq),
                        "event": ev.type.value,
                        "data": _ev_to_json(ev),
                    }
                    if ev.type in (EventType.RUN_COMPLETED, EventType.RUN_FAILED):
                        return
            finally:
                h.bus.unsubscribe(sub)

        return EventSourceResponse(event_gen(), ping=15)

    # ---------- static front-end ----------

    if WEB_ROOT.exists():
        app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        index_html = WEB_ROOT / "index.html"
        if not index_html.exists():
            return JSONResponse({"detail": "frontend not built"}, status_code=503)
        i18n: I18nRegistry = request.app.state.i18n
        locale = _resolve_locale(request, i18n)
        # Send the static HTML, but persist the negotiated locale on first visit
        resp = FileResponse(index_html)
        resp.set_cookie(
            LANG_COOKIE_NAME, locale,
            max_age=LANG_COOKIE_MAX_AGE,
            samesite="lax",
            httponly=False,
        )
        return resp

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    return app


def _ev_to_json(ev) -> str:
    """Compact JSON encoding for SSE data line."""
    import json
    return json.dumps(ev.to_dict(), ensure_ascii=False)


def _resolve_locale(request: Request, i18n: I18nRegistry) -> str:
    """Three-tier locale negotiation. Used by `/` and `/api/i18n/locales`."""
    return negotiate_locale(
        query=request.query_params.get("lang"),
        cookie=request.cookies.get(LANG_COOKIE_NAME),
        accept_language=request.headers.get("accept-language"),
        available=set(i18n.available()),
        default=i18n.default,
    )


# uvicorn entry: lyrebird.web.app:app
app = create_app()
