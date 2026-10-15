"""Milestone 4: the human approval gate.

Nothing CodeRepair produces reaches a repository without two explicit human
steps:

1. ``coderepair approve RUN --candidate N --reviewer NAME`` records who approved
   which candidate, the SHA-256 of its diff, the checks it passed and any risks
   the reviewer acknowledged (``approval.json``, mode 0600), and exports
   ``approved.patch``. Candidates with high-severity security findings, failing
   visible tests or regressions are refused unless the reviewer passes
   ``--acknowledge-risks``.
2. ``coderepair apply RUN --repo PATH`` re-ingests the repository under the
   usual path policy, re-applies the approved edits, and writes files only if
   the result is byte-for-byte the approved diff (so the repository has not
   changed underneath the approval) and the approval record is intact.

``apply`` never runs ``git`` (repository configuration can make git execute
code), never commits, never pushes and never merges: it edits the working
tree and prints the commands a human can use to inspect and commit.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .config import Limits
from .patch import PatchProposal, apply_proposal
from .repo import ingest_repository
from .security import PolicyError
from .trace import RUN_ID_RE

APPROVAL_FILE = "approval.json"
APPROVED_PATCH = "approved.patch"


class ApprovalError(PermissionError):
    pass


@dataclass(frozen=True)
class ApprovalRecord:
    run_id: str
    candidate: int
    diff_sha256: str
    reviewer: str
    approved_at: str
    os_user: str
    repo_root: str
    snapshot_hash: str
    files: list[str]
    checks: dict
    acknowledged_risks: list[str]
    include_reproduction_test: bool
    note: str = ""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_run_dir(runs_dir: Path, run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id):
        raise ApprovalError(f"invalid run id {run_id!r}")
    run_dir = runs_dir / run_id
    if not (run_dir / "summary.json").is_file():
        raise ApprovalError(f"no run {run_id!r} in {runs_dir}")
    return run_dir


def _load_summary(run_dir: Path) -> dict:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    if summary.get("mode") != "repair-loop" or not summary.get("candidates"):
        raise ApprovalError("this run has no scored candidates to approve")
    return summary


def risks_of(card: dict) -> list[str]:
    risks = []
    if not card["visible_all_pass"]:
        risks.append("visible tests fail with this candidate")
    if card["regressions"]:
        risks.append(f"{len(card['regressions'])} previously passing test(s) fail")
    risks += [f"security finding: {f}" for f in card["security"] if f.startswith("[high]")]
    for check in ("lint", "typecheck"):
        result = card.get(check)
        if result and result["status"] == "new-issues":
            risks.append(f"{result['tool']} reports {len(result['new'])} new issue(s)")
    return risks


def approve(
    run_dir: Path,
    *,
    candidate: int | None,
    reviewer: str,
    acknowledge_risks: bool = False,
    include_reproduction_test: bool = False,
    note: str = "",
) -> ApprovalRecord:
    if not reviewer.strip():
        raise ApprovalError("a reviewer name is required")
    if (run_dir / APPROVAL_FILE).exists():
        raise ApprovalError(f"run {run_dir.name} is already approved; approvals are final")
    summary = _load_summary(run_dir)
    cards = {card["candidate"]: card for card in summary["candidates"]}
    chosen = candidate if candidate is not None else summary["selected_candidate"]
    if chosen not in cards:
        raise ApprovalError(f"candidate {chosen} does not exist (have {sorted(cards)})")
    card = cards[chosen]
    risks = risks_of(card)
    if risks and not acknowledge_risks:
        raise ApprovalError(
            "candidate has unresolved risks; review them and pass --acknowledge-risks: "
            + "; ".join(risks)
        )
    repro = summary.get("reproduction_test") or {}
    if include_reproduction_test and repro.get("status") != "reproduces":
        raise ApprovalError("there is no usable reproduction test to include")
    diff = (run_dir / f"candidate-{chosen}.patch").read_text(encoding="utf-8")
    record = ApprovalRecord(
        run_id=summary["run_id"],
        candidate=chosen,
        diff_sha256=sha256_text(diff),
        reviewer=reviewer.strip(),
        approved_at=datetime.now(UTC).isoformat(timespec="seconds"),
        os_user=getpass.getuser(),
        repo_root=summary["repo_root"],
        snapshot_hash=summary["snapshot_hash"],
        files=card["files_changed"],
        checks={k: card[k] for k in ("visible_all_pass", "regressions", "reproduction_test")},
        acknowledged_risks=risks,
        include_reproduction_test=include_reproduction_test,
        note=note,
    )
    approved = diff
    if include_reproduction_test:
        approved += _new_file_diff(repro["path"], repro["code"])
    _write_private(run_dir / APPROVED_PATCH, approved)
    _write_private(run_dir / APPROVAL_FILE, json.dumps(asdict(record), indent=2) + "\n")
    return record


def _new_file_diff(path: str, text: str) -> str:
    lines = text.splitlines(keepends=True)
    body = "".join("+" + line if line.endswith("\n") else f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{body}"
    )


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def load_approval(run_dir: Path) -> ApprovalRecord:
    path = run_dir / APPROVAL_FILE
    if not path.is_file():
        raise ApprovalError(f"run {run_dir.name} has not been approved")
    return ApprovalRecord(**json.loads(path.read_text(encoding="utf-8")))


@dataclass
class ApplyResult:
    repo_root: Path
    written: list[str]


def apply_approved(
    run_dir: Path,
    repo: str | Path,
    *,
    allowed_roots: tuple[Path, ...],
    protected_roots: tuple[Path, ...] = (),
    limits: Limits | None = None,
) -> ApplyResult:
    """Write an approved candidate into ``repo`` after re-verifying everything."""
    record = load_approval(run_dir)
    summary = _load_summary(run_dir)
    diff = (run_dir / f"candidate-{record.candidate}.patch").read_text(encoding="utf-8")
    if sha256_text(diff) != record.diff_sha256:
        raise ApprovalError("the candidate patch changed after approval; refusing to apply")
    if summary["run_id"] != record.run_id:
        raise ApprovalError("approval record does not belong to this run")
    snapshot = ingest_repository(repo, allowed_roots, limits or Limits())
    root = snapshot.root
    for protected in protected_roots:
        real = protected.resolve()
        if root == real or real in root.parents:
            raise PolicyError(f"refusing to write into a protected location: {root}")
    proposal = PatchProposal.model_validate_json(
        (run_dir / f"candidate-{record.candidate}.json").read_text(encoding="utf-8")
    )
    result = apply_proposal(snapshot, proposal)
    if not result.ok:
        raise ApprovalError(f"approved edits no longer apply: {result.errors}")
    if result.diff != diff:
        raise ApprovalError("the repository changed since the proposal was made; re-run CodeRepair")
    writes = dict(result.changed_files)
    if record.include_reproduction_test:
        repro = summary["reproduction_test"]
        rel = repro["path"]
        if rel in snapshot.files or (root / rel).exists():
            raise ApprovalError(f"{rel} already exists in the repository")
        writes[rel] = repro["code"]
    for rel in writes:
        parts = PurePosixPath(rel).parts
        if not parts or ".." in parts or rel.startswith("/"):
            raise ApprovalError(f"unsafe path {rel!r}")
    written = []
    for rel, text in sorted(writes.items()):
        target = root.joinpath(*PurePosixPath(rel).parts)
        if target.is_symlink():
            raise ApprovalError(f"refusing to write through a symlink: {rel}")
        _atomic_write(target, text)
        written.append(rel)
    return ApplyResult(root, written)


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix=".coderepair-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
