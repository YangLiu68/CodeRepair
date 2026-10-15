"""Local HTTP API and minimal diff viewer.

Intended for localhost use only: there is no authentication. Requests are
limited to registered task ids and validated run ids, so no client-supplied
filesystem path ever reaches the server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .agent import propose_patch
from .backends import make_backend
from .benchmark.tasks import TaskError, list_tasks, load_task
from .config import Settings
from .issue import parse_issue
from .llm.base import BackendError
from .repo import ingest_repository
from .retrieval import rank_files
from .search import RepoIndex
from .security import PolicyError
from .trace import RUN_ID_RE, read_trace

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]", "testserver"]
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class ProposalRequest(BaseModel):
    # The scripted backend reads a local file, so it is deliberately not exposed over HTTP.
    backend: Literal["oracle", "anthropic", "ollama"] = "oracle"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="CodeRepair", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def _task(task_id: str):
        try:
            return load_task(settings.tasks_dir, task_id)
        except TaskError as exc:
            raise HTTPException(404, str(exc)) from exc

    def _snapshot(task):
        try:
            return ingest_repository(task.repo_dir, settings.allowed_roots, settings.limits)
        except PolicyError as exc:
            raise HTTPException(403, str(exc)) from exc

    def _run_dir(run_id: str) -> Path:
        if not RUN_ID_RE.match(run_id):
            raise HTTPException(404, "unknown run")
        run_dir = settings.runs_dir / run_id
        if not (run_dir / "summary.json").is_file():
            raise HTTPException(404, "unknown run")
        return run_dir

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/tasks")
    def tasks() -> list[dict]:
        return [task.summary() for task in list_tasks(settings.tasks_dir)]

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str) -> dict:
        task = _task(task_id)
        snapshot = _snapshot(task)
        issue_text = task.read_issue()
        return {
            **task.summary(),
            "issue": issue_text,
            "parsed_issue": parse_issue(issue_text).to_dict(),
            "files": snapshot.paths(),
            "excluded": [vars(e) for e in snapshot.excluded],
            "content_hash": snapshot.content_hash,
        }

    @app.get("/api/tasks/{task_id}/retrieval")
    def retrieval(task_id: str) -> list[dict]:
        task = _task(task_id)
        snapshot = _snapshot(task)
        ranked = rank_files(snapshot, RepoIndex(snapshot), parse_issue(task.read_issue()))
        return [r.to_dict() for r in ranked if r.score > 0]

    @app.post("/api/tasks/{task_id}/proposals")
    def propose(task_id: str, body: ProposalRequest) -> dict:
        task = _task(task_id)
        snapshot = _snapshot(task)
        try:
            backend = make_backend(body.backend, settings, task=task)
        except BackendError as exc:
            raise HTTPException(400, str(exc)) from exc
        run = propose_patch(
            snapshot,
            task.read_issue(),
            backend,
            limits=settings.limits,
            runs_dir=settings.runs_dir,
            task_id=task.id,
        )
        return {**run.summary_dict(), "diff": run.diff}

    @app.get("/api/runs")
    def runs(limit: int = 50) -> list[dict]:
        if not settings.runs_dir.is_dir():
            return []
        dirs = sorted(
            (d for d in settings.runs_dir.iterdir() if RUN_ID_RE.match(d.name)),
            key=lambda d: d.name,
            reverse=True,
        )
        out = []
        for run_dir in dirs[: max(1, min(limit, 200))]:
            summary = run_dir / "summary.json"
            if summary.is_file():
                out.append(json.loads(summary.read_text(encoding="utf-8")))
        return out

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> dict:
        run_dir = _run_dir(run_id)
        patch = run_dir / "proposal.patch"
        return {
            "summary": json.loads((run_dir / "summary.json").read_text(encoding="utf-8")),
            "diff": patch.read_text(encoding="utf-8") if patch.is_file() else "",
            "trace": read_trace(run_dir / "trace.jsonl"),
        }

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
