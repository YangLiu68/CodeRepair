"""Local HTTP API and dashboard.

Intended for localhost use only: there is no authentication. Requests are
limited to registered task ids, validated run ids and known benchmark result
names, so no client-supplied filesystem path ever reaches the server. State-
changing requests (proposals, repairs, approvals, self-tests) must be JSON and,
when the browser sends an ``Origin``, come from this server's own origin, which
blocks cross-site request forgery from other pages the user has open.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .agent import propose_patch
from .approval import ApprovalError, approve
from .backends import make_backend
from .benchmark.tasks import TaskError, list_tasks, load_any_task
from .config import PROJECT_ROOT, Settings
from .issue import parse_issue
from .llm.base import BackendError
from .loop import RepairBudget, repair
from .repo import ingest_repository
from .retrieval import rank_files
from .sandbox.base import SandboxError
from .sandbox.factory import make_sandbox, sandbox_status
from .sandbox.probes import run_probes
from .search import RepoIndex
from .security import PolicyError
from .trace import RUN_ID_RE, read_trace

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


RESULTS_DIR = PROJECT_ROOT / "docs" / "results"
_RESULT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_LOOPBACK_ORIGIN = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$")


class ProposalRequest(BaseModel):
    # The scripted backend reads a local file, so it is deliberately not exposed over HTTP.
    backend: Literal["oracle", "anthropic", "ollama"] = "oracle"


class RepairRequest(BaseModel):
    backend: Literal["oracle", "anthropic", "ollama"] = "oracle"
    max_attempts: int = Field(default=3, ge=1, le=6)
    candidates: int = Field(default=1, ge=1, le=3)
    repro_test: bool = False


class ApprovalRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    candidate: int | None = Field(default=None, ge=1, le=20)
    acknowledge_risks: bool = False
    include_repro_test: bool = False
    note: str = Field(default="", max_length=500)


def create_app(settings: Settings | None = None, *, extra_hosts: tuple[str, ...] = ()) -> FastAPI:
    """``extra_hosts`` exists for the test client (``testserver``); never for real use."""
    settings = settings or Settings.from_env()
    app = FastAPI(title="CodeRepair", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*ALLOWED_HOSTS, *extra_hosts])

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            content_type = request.headers.get("content-type", "").split(";")[0].strip()
            if origin is not None and not (
                _LOOPBACK_ORIGIN.match(origin) and origin.split("//", 1)[1] == host
            ):
                return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
            if content_type != "application/json":
                return JSONResponse({"detail": "JSON body required"}, status_code=415)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def _task(task_id: str):
        try:
            return load_any_task(settings.task_dirs, task_id)
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
        return [task.summary() for d in settings.task_dirs for task in list_tasks(d)]

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

    def _sandbox():
        try:
            return make_sandbox(settings.sandbox, settings.cache_dir, settings.sandbox_image)
        except SandboxError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/tasks/{task_id}/repairs")
    def repair_task(task_id: str, body: RepairRequest) -> dict:
        task = _task(task_id)
        snapshot = _snapshot(task)
        sandbox = _sandbox()
        try:
            backend = make_backend(body.backend, settings, task=task)
        except BackendError as exc:
            raise HTTPException(400, str(exc)) from exc
        run = repair(
            snapshot,
            task.read_issue(),
            backend,
            sandbox,
            budget=RepairBudget(
                max_attempts=body.max_attempts,
                candidates=body.candidates,
                repro_test=body.repro_test,
            ),
            limits=settings.limits,
            sandbox_limits=settings.sandbox_limits(),
            runs_dir=settings.runs_dir,
            task_id=task.id,
        )
        return {**run.summary_dict(), "diff": run.diff}

    @app.get("/api/sandbox")
    def sandbox_info() -> dict:
        statuses = sandbox_status(settings.cache_dir, settings.sandbox_image)
        usable = [s.name for s in statuses if s.available]
        return {
            "configured": settings.sandbox,
            "selected": usable[0] if usable and settings.sandbox == "auto" else settings.sandbox,
            "backends": [vars(s) for s in statuses],
        }

    @app.post("/api/sandbox/selftest")
    def sandbox_selftest() -> dict:
        sandbox = _sandbox()
        reports = run_probes(sandbox)
        return {
            "sandbox": sandbox.name,
            "isolation": sandbox.isolation,
            "contained": sum(r.contained for r in reports),
            "total": len(reports),
            "probes": [r.to_dict() for r in reports],
        }

    @app.post("/api/runs/{run_id}/approval")
    def approve_run(run_id: str, body: ApprovalRequest) -> dict:
        run_dir = _run_dir(run_id)
        try:
            record = approve(
                run_dir,
                candidate=body.candidate,
                reviewer=body.reviewer,
                acknowledge_risks=body.acknowledge_risks,
                include_reproduction_test=body.include_repro_test,
                note=body.note,
            )
        except ApprovalError as exc:
            raise HTTPException(409, str(exc)) from exc
        return vars(record)

    def _result_files() -> dict[str, Path]:
        files = {}
        for directory in (RESULTS_DIR, settings.runs_dir / "bench"):
            if directory.is_dir():
                for path in sorted(directory.glob("*.summary.json")):
                    name = path.name.removesuffix(".summary.json")
                    if _RESULT_NAME_RE.match(name):
                        files.setdefault(name, path)
        return files

    @app.get("/api/benchmarks")
    def benchmarks() -> list[dict]:
        out = []
        for name, path in _result_files().items():
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append({"name": name, "meta": data.get("meta"), "summary": data.get("summary")})
        return out

    @app.get("/api/benchmarks/{name}")
    def benchmark_rows(name: str) -> dict:
        path = _result_files().get(name)
        if path is None:
            raise HTTPException(404, "unknown benchmark result")
        data = json.loads(path.read_text(encoding="utf-8"))
        rows_path = path.with_name(name + ".jsonl")
        rows = []
        if rows_path.is_file():
            for line in rows_path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record.get("config") == data.get("config"):
                    rows.append(record["row"])
        return {"name": name, **data, "rows": rows}

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
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        candidates = {}
        for card in summary.get("candidates") or []:
            index = int(card["candidate"])
            path = run_dir / f"candidate-{index}.patch"
            candidates[str(index)] = path.read_text(encoding="utf-8") if path.is_file() else ""
        approval = run_dir / "approval.json"
        return {
            "summary": summary,
            "diff": patch.read_text(encoding="utf-8") if patch.is_file() else "",
            "candidate_patches": candidates,
            "approval": json.loads(approval.read_text(encoding="utf-8"))
            if approval.is_file()
            else None,
            "trace": read_trace(run_dir / "trace.jsonl"),
        }

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
