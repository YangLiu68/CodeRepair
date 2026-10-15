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
import secrets
import stat
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .config import Limits
from .patch import PatchProposal, apply_proposal
from .repo import ingest_repository
from .security import PolicyError, same_or_inside
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
    #: SHA-256 of the reproduction test code (when it is part of the approval)
    reproduction_test_sha256: str = ""


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
        reproduction_test_sha256=sha256_text(repro["code"]) if include_reproduction_test else "",
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
    """Write an approved candidate into ``repo`` after re-verifying everything.

    Checks, in order: the approval belongs to this run; the candidate patch and the
    reproduction test are byte-identical to what was approved; ``repo`` passes the
    ingestion policy, is not a protected location, is the repository the run was made
    on, and still has the same content; re-applying the approved edits reproduces the
    approved diff exactly. Files are then written through directory handles opened
    without following symlinks, after a last check that each file is unchanged.
    """
    record = load_approval(run_dir)
    summary = _load_summary(run_dir)
    if summary["run_id"] != record.run_id:
        raise ApprovalError("approval record does not belong to this run")
    diff = (run_dir / f"candidate-{record.candidate}.patch").read_text(encoding="utf-8")
    if sha256_text(diff) != record.diff_sha256:
        raise ApprovalError("the candidate patch changed after approval; refusing to apply")
    repro = summary.get("reproduction_test") or {}
    if record.include_reproduction_test and (
        sha256_text(repro.get("code", "")) != record.reproduction_test_sha256
    ):
        raise ApprovalError("the reproduction test changed after approval; refusing to apply")

    snapshot = ingest_repository(repo, allowed_roots, limits or Limits())
    root = snapshot.root
    for protected in protected_roots:
        if same_or_inside(root, protected):
            raise PolicyError(f"refusing to write into a protected location: {root}")
    if not same_or_inside(root, Path(record.repo_root)) or not same_or_inside(
        Path(record.repo_root), root
    ):
        raise ApprovalError(
            f"this approval is for {record.repo_root}, not {root}; re-run CodeRepair there"
        )
    if snapshot.content_hash != record.snapshot_hash:
        raise ApprovalError("the repository changed since the run; re-run CodeRepair")
    proposal = PatchProposal.model_validate_json(
        (run_dir / f"candidate-{record.candidate}.json").read_text(encoding="utf-8")
    )
    result = apply_proposal(snapshot, proposal)
    if not result.ok:
        raise ApprovalError(f"approved edits no longer apply: {result.errors}")
    if result.diff != diff:
        raise ApprovalError("the repository changed since the run; re-run CodeRepair")

    writes: dict[str, tuple[str | None, str]] = {
        rel: (snapshot.text(rel), text) for rel, text in result.changed_files.items()
    }
    if record.include_reproduction_test:
        writes[repro["path"]] = (None, repro["code"])
    for rel in writes:
        parts = PurePosixPath(rel).parts
        if not parts or ".." in parts or rel.startswith("/") or any(p in ("", ".") for p in parts):
            raise ApprovalError(f"unsafe path {rel!r}")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # First pass: every target is a regular file (or absent) reached without symlinks,
        # with exactly the content the approval was made against.
        for rel, (expected, _new) in sorted(writes.items()):
            _check_target(root_fd, rel, expected)
        written = []
        for rel, (_expected, new) in sorted(writes.items()):
            _write_target(root_fd, rel, new)
            written.append(rel)
    finally:
        os.close(root_fd)
    return ApplyResult(root, written)


def _open_parent(root_fd: int, rel: str, *, create: bool) -> int:
    """Open the parent directory of ``rel`` component by component, never following links."""
    fd = os.dup(root_fd)
    try:
        for part in PurePosixPath(rel).parts[:-1]:
            try:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o755, dir_fd=fd)
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:  # ELOOP / ENOTDIR: a symlink or a file in the way
                raise ApprovalError(f"refusing to write through {part!r} in {rel}: {exc}") from exc
            os.close(fd)
            fd = next_fd
    except BaseException:
        os.close(fd)
        raise
    return fd


def _check_target(root_fd: int, rel: str, expected: str | None) -> None:
    name = PurePosixPath(rel).name
    try:
        dir_fd = _open_parent(root_fd, rel, create=False)
    except FileNotFoundError:
        if expected is None:
            return  # a new file in a new directory
        raise ApprovalError(f"{rel} disappeared since the run") from None
    try:
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            if expected is None:
                return
            raise ApprovalError(f"{rel} disappeared since the run") from None
        if expected is None:
            raise ApprovalError(f"{rel} already exists in the repository")
        if not stat.S_ISREG(info.st_mode):
            raise ApprovalError(f"refusing to write {rel}: not a regular file")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        with os.fdopen(fd, "r", encoding="utf-8", newline="") as fh:
            if fh.read() != expected:
                raise ApprovalError(f"{rel} changed since the run; re-run CodeRepair")
    finally:
        os.close(dir_fd)


def _write_target(root_fd: int, rel: str, text: str) -> None:
    name = PurePosixPath(rel).name
    dir_fd = _open_parent(root_fd, rel, create=True)
    try:
        try:
            mode = stat.S_IMODE(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode)
        except FileNotFoundError:
            mode = 0o644
        tmp = f".coderepair-{secrets.token_hex(6)}.tmp"
        fd = os.open(
            tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
                os.fchmod(fh.fileno(), mode)
            os.replace(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
            raise
    finally:
        os.close(dir_fd)
