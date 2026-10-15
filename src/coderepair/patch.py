"""Patch proposals: parsing, validation, in-memory application and diff rendering.

LLM output is only ever interpreted as data: a list of exact search/replace
edits. Edits are checked against a policy and applied to an in-memory copy of
the snapshot; the source repository on disk is never modified here.
"""

from __future__ import annotations

import ast
import difflib
import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import Limits
from .repo import RepoSnapshot
from .search import is_test_path
from .security import is_sensitive_path


class Edit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = Field(description="Repository-relative POSIX path of an existing file.")
    old: str = Field(description="Exact text copied from the file; must occur exactly once.")
    new: str = Field(description="Replacement text.")


class PatchProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    edits: list[Edit] = Field(default_factory=list)


# Strict JSON schema for structured-output APIs (all fields required, no extras).
PROPOSAL_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "edits"],
    "additionalProperties": False,
}


class ProposalParseError(ValueError):
    pass


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def parse_proposal(raw: str) -> PatchProposal:
    """Parse model output into a :class:`PatchProposal` (JSON, optionally fenced)."""
    text = raw.strip()
    candidates = [text]
    candidates += _FENCED_JSON_RE.findall(text)
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    errors = []
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON: {exc}")
            continue
        try:
            return PatchProposal.model_validate(data)
        except ValidationError as exc:
            errors.append(
                f"schema mismatch: {exc.error_count()} error(s): {exc.errors()[0]['msg']}"
            )
    raise ProposalParseError(errors[-1] if errors else "empty response")


# ------------------------------------------------------------------------ policy

PROTECTED_FILE_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "tox.ini",
        "noxfile.py",
        "pytest.ini",
        "conftest.py",
        "Makefile",
        "Dockerfile",
        "MANIFEST.in",
        ".gitignore",
        ".gitattributes",
        ".pre-commit-config.yaml",
        ".gitlab-ci.yml",
        "requirements.txt",
        "uv.lock",
        "poetry.lock",
    }
)
PROTECTED_DIRS = frozenset({".github", ".circleci", ".gitlab", ".git"})
PROTECTED_SUFFIXES = (".sh", ".bash", ".ps1", ".bat", ".cmd")

_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "process-execution",
        re.compile(r"\b(?:os\.system|os\.popen|subprocess|pty\.spawn|os\.exec\w*)\b"),
    ),
    ("dynamic-code", re.compile(r"(?<![\w.])(?:eval|exec|compile|__import__)\s*\(")),
    ("deserialization", re.compile(r"\b(?:pickle|marshal|shelve)\.loads?\b|yaml\.load\(")),
    ("network", re.compile(r"\b(?:socket|urllib|http\.client|requests|httpx|ftplib)\b|https?://")),
    (
        "filesystem-destruction",
        re.compile(r"\b(?:shutil\.rmtree|os\.remove|os\.unlink|os\.rmdir)\b"),
    ),
    ("native-code", re.compile(r"\bctypes\b|\bcffi\b")),
    ("credential-path", re.compile(r"~/\.ssh|\bid_rsa\b|\.aws/|\.netrc|\bkeychain\b", re.I)),
    ("shell-download", re.compile(r"\b(?:curl|wget)\b")),
)


@dataclass(frozen=True)
class PatchPolicy:
    allow_test_edits: bool = False
    max_edits: int = 20
    max_changed_lines: int = 200
    max_edit_chars: int = 20_000

    @classmethod
    def from_limits(cls, limits: Limits) -> PatchPolicy:
        return cls(
            max_edits=limits.max_edits,
            max_changed_lines=limits.max_changed_lines,
            max_edit_chars=limits.max_edit_chars,
        )


def path_violation(path: str, snapshot: RepoSnapshot, policy: PatchPolicy) -> str | None:
    """Return why ``path`` may not be edited, or None if it may."""
    if not path or "\x00" in path:
        return "empty or NUL-containing path"
    if "\\" in path:
        return "backslashes are not allowed in paths"
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return "absolute paths are not allowed"
    if ".." in PurePosixPath(path).parts:
        return "path traversal ('..') is not allowed"
    if posixpath.normpath(path) != path:
        return f"path is not normalized (expected {posixpath.normpath(path)!r})"
    if is_sensitive_path(path):
        return "sensitive file"
    parts = PurePosixPath(path).parts
    if any(part in PROTECTED_DIRS for part in parts):
        return "protected path (CI / VCS metadata)"
    name = parts[-1]
    if (
        name in PROTECTED_FILE_NAMES
        or name.startswith("requirements")
        or name.endswith(PROTECTED_SUFFIXES)
    ):
        return "protected path (build, packaging or script file)"
    if is_test_path(path) and not policy.allow_test_edits:
        return "protected path (tests may not be modified to make them pass)"
    if path not in snapshot.files:
        return "file does not exist in the repository snapshot (new files are not allowed)"
    return None


# ------------------------------------------------------------------- application


@dataclass
class EditOutcome:
    index: int
    path: str
    applied: bool
    reason: str = ""
    match: str = ""


@dataclass
class PatchResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    outcomes: list[EditOutcome] = field(default_factory=list)
    changed_files: dict[str, str] = field(default_factory=dict)
    diff: str = ""
    lines_added: int = 0
    lines_removed: int = 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "outcomes": [vars(o) for o in self.outcomes],
            "files_changed": sorted(self.changed_files),
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
        }


def _find_trailing_ws_match(text: str, old: str) -> tuple[int, int] | None:
    """Locate ``old`` ignoring trailing whitespace per line; returns a unique char span."""
    old_lines = old.split("\n")
    if old_lines and old_lines[-1] == "":
        old_lines = old_lines[:-1]
    if not old_lines:
        return None
    lines = text.split("\n")
    target = [line.rstrip() for line in old_lines]
    hits = [
        i
        for i in range(len(lines) - len(target) + 1)
        if [line.rstrip() for line in lines[i : i + len(target)]] == target
    ]
    if len(hits) != 1:
        return None
    start = sum(len(line) + 1 for line in lines[: hits[0]])
    end = start + sum(len(line) + 1 for line in lines[hits[0] : hits[0] + len(target)])
    if not old.endswith("\n"):
        end -= 1
    return start, min(end, len(text))


def _risk_warnings(path: str, added_lines: list[str]) -> list[str]:
    warnings = []
    for rule, pattern in _RISK_PATTERNS:
        hits = [line.strip() for line in added_lines if pattern.search(line)]
        if hits:
            warnings.append(f"{path}: added code matches risk rule '{rule}': {hits[0][:120]!r}")
    return warnings


def apply_proposal(
    snapshot: RepoSnapshot, proposal: PatchProposal, policy: PatchPolicy | None = None
) -> PatchResult:
    """Validate every edit and apply them to an in-memory overlay (all or nothing)."""
    policy = policy or PatchPolicy()
    result = PatchResult(ok=False)
    if not proposal.edits:
        result.errors.append("proposal contains no edits")
        return result
    if len(proposal.edits) > policy.max_edits:
        result.errors.append(f"too many edits ({len(proposal.edits)} > {policy.max_edits})")
        return result

    overlay: dict[str, str] = {}
    for i, edit in enumerate(proposal.edits):
        outcome = EditOutcome(i, edit.path, applied=False)
        result.outcomes.append(outcome)
        violation = path_violation(edit.path, snapshot, policy)
        if violation:
            outcome.reason = violation
            continue
        if not edit.old:
            outcome.reason = "'old' must not be empty"
            continue
        if edit.old == edit.new:
            outcome.reason = "'old' and 'new' are identical"
            continue
        if len(edit.old) > policy.max_edit_chars or len(edit.new) > policy.max_edit_chars:
            outcome.reason = f"edit larger than {policy.max_edit_chars} characters"
            continue
        current = overlay.get(edit.path, snapshot.text(edit.path))
        count = current.count(edit.old)
        if count == 1:
            overlay[edit.path] = current.replace(edit.old, edit.new, 1)
            outcome.applied, outcome.match = True, "exact"
        elif count > 1:
            outcome.reason = f"'old' text is ambiguous ({count} matches); include more context"
        else:
            span = _find_trailing_ws_match(current, edit.old)
            if span is None:
                outcome.reason = "'old' text not found in the file"
            else:
                start, end = span
                overlay[edit.path] = current[:start] + edit.new + current[end:]
                outcome.applied, outcome.match = True, "ignoring-trailing-whitespace"

    for outcome in result.outcomes:
        if not outcome.applied:
            result.errors.append(f"edit {outcome.index} ({outcome.path}): {outcome.reason}")
    if result.errors:
        return result

    changed = {p: text for p, text in overlay.items() if text != snapshot.text(p)}
    if not changed:
        result.errors.append("edits do not change any file")
        return result
    for path, text in sorted(changed.items()):
        if path.endswith(".py"):
            try:
                ast.parse(text, filename=path)
            except SyntaxError as exc:
                result.errors.append(
                    f"{path}: edit produces invalid Python (line {exc.lineno}: {exc.msg})"
                )
            except (ValueError, RecursionError, MemoryError) as exc:
                result.errors.append(
                    f"{path}: edit produces unparseable Python ({type(exc).__name__})"
                )
    if result.errors:
        return result

    diff = unified_diff({p: snapshot.text(p) for p in changed}, changed)
    added = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    removed = [
        line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")
    ]
    if len(added) + len(removed) > policy.max_changed_lines:
        result.errors.append(
            f"patch changes {len(added) + len(removed)} lines (limit {policy.max_changed_lines})"
        )
        return result
    for path in sorted(changed):
        file_added = _added_lines_for(diff, path)
        result.warnings.extend(_risk_warnings(path, file_added))
    result.ok = True
    result.changed_files = changed
    result.diff = diff
    result.lines_added, result.lines_removed = len(added), len(removed)
    return result


def _added_lines_for(diff: str, path: str) -> list[str]:
    lines, inside = [], False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            inside = line == f"diff --git a/{path} b/{path}"
        elif inside and line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    return lines


# --------------------------------------------------------------------------- diff


def unified_diff(before: dict[str, str], after: dict[str, str], context: int = 3) -> str:
    """Git-style unified diff (``git apply`` compatible) for modified text files."""
    chunks: list[str] = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path, ""), after.get(path, "")
        if old == new:
            continue
        body = list(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=context,
            )
        )
        if not body:
            continue
        chunks.append(f"diff --git a/{path} b/{path}\n")
        for line in body:
            if line.endswith("\n"):
                chunks.append(line)
            else:
                chunks.append(line + "\n\\ No newline at end of file\n")
    return "".join(chunks)
