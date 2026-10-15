"""Milestone 4: static checks on a candidate patch.

* **Lint** (``ruff``) and **type check** (``mypy``) run on two throwaway copies
  of the repository's Python files, before and after the patch, and only
  diagnostics the patch *introduces* are reported. Both tools analyse source
  without importing or executing it. Repository configuration is ignored
  (``ruff --isolated``; ``mypy --config-file`` pointing at an empty file, so no
  mypy plugins from the repository can load), the environment is scrubbed and
  both run with a timeout. mypy is started with ``python -I`` so that a
  ``mypy.py`` or ``typing_extensions.py`` in the copied repository (the working
  directory) can never shadow the real modules. If a tool is not installed the
  check is reported as skipped, never as passed.
* **Security review** compares the AST of every changed file before and after
  the patch and flags newly introduced risky constructs (process execution,
  dynamic code, unsafe deserialisation, network access, ``shell=True``,
  disabled TLS verification, native code, destructive filesystem calls,
  hard-coded secrets) and removed ``raise`` statements, which often means a
  validation check was deleted.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .repo import RepoSnapshot
from .security import HIDDEN_CHARS, redact_secrets

_TOOL_TIMEOUT_S = 60

_RUFF_RULES = "F,E9,B"


@dataclass(frozen=True)
class Diagnostic:
    tool: str
    path: str
    line: int
    code: str
    message: str

    def key(self) -> tuple[str, str, str]:
        return (self.path, self.code, self.message)

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message}"


@dataclass
class CheckResult:
    tool: str
    status: str  # "ok" | "new-issues" | "skipped" | "error"
    new: list[Diagnostic] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "status": self.status,
            "new": [str(d) for d in self.new],
            "detail": self.detail,
        }


# ------------------------------------------------------------------ tool running


def _write_tree(root: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        parts = PurePosixPath(rel).parts
        if not parts or ".." in parts or rel.startswith("/"):
            continue
        target = root.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _tool_env(home: Path) -> dict[str, str]:
    return {
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), "/usr/bin", "/bin"]),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_COLOR": "1",
    }


def _ruff_binary() -> str | None:
    candidate = Path(sys.executable).parent / "ruff"
    if candidate.exists():
        return str(candidate)
    return shutil.which("ruff")


def _mypy_available() -> bool:
    try:
        import mypy  # noqa: F401
    except ImportError:
        return False
    return True


def _run_ruff(tree: Path, home: Path) -> list[Diagnostic]:
    ruff = _ruff_binary()
    if ruff is None:
        raise FileNotFoundError("ruff")
    proc = subprocess.run(  # noqa: S603 - fixed argv; ruff only parses the files
        [
            ruff,
            "check",
            "--isolated",
            "--no-cache",
            "--exit-zero",
            "--select",
            _RUFF_RULES,
            "--output-format",
            "json",
            ".",
        ],
        cwd=tree,
        env=_tool_env(home),
        capture_output=True,
        text=True,
        timeout=_TOOL_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300] or f"ruff exited {proc.returncode}")
    diagnostics = []
    for item in json.loads(proc.stdout or "[]"):
        path = Path(item["filename"]).resolve().relative_to(tree.resolve()).as_posix()
        diagnostics.append(
            Diagnostic(
                "ruff",
                path,
                int(item["location"]["row"]),
                str(item.get("code") or "syntax"),
                str(item["message"]),
            )
        )
    return diagnostics


_MYPY_LINE = re.compile(
    r"^(?P<path>[^:\n]+):(?P<line>\d+): error: (?P<msg>.*?)(?:  \[(?P<code>[\w-]+)\])?$"
)


def _run_mypy(tree: Path, home: Path) -> list[Diagnostic]:
    config = home / "mypy.ini"
    config.write_text("[mypy]\n", encoding="utf-8")
    targets = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*.py"))
    if not targets:
        return []
    proc = subprocess.run(  # noqa: S603 - fixed argv; mypy analyses, never imports, the code
        [
            sys.executable,
            "-I",  # isolated: the copied repository (cwd) is not on sys.path
            "-m",
            "mypy",
            "--config-file",
            str(config),
            "--cache-dir",
            str(home / "mypy-cache"),
            "--no-site-packages",
            "--ignore-missing-imports",
            "--follow-imports=silent",
            "--show-error-codes",
            "--no-error-summary",
            "--hide-error-context",
            "--no-color-output",
            "--explicit-package-bases",
            *targets,
        ],
        cwd=tree,
        env={**_tool_env(home), "MYPY_FORCE_COLOR": "0"},
        capture_output=True,
        text=True,
        timeout=_TOOL_TIMEOUT_S,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError((proc.stderr or proc.stdout).strip()[:300])
    diagnostics = []
    for line in proc.stdout.splitlines():
        match = _MYPY_LINE.match(line.strip())
        if match:
            diagnostics.append(
                Diagnostic(
                    "mypy",
                    match["path"],
                    int(match["line"]),
                    match["code"] or "error",
                    match["msg"],
                )
            )
    return diagnostics


def _delta(tool: str, runner, before: Mapping[str, str], after: Mapping[str, str]) -> CheckResult:
    with tempfile.TemporaryDirectory(prefix=f"coderepair-{tool}-") as tmp:
        root = Path(tmp)
        old_tree, new_tree, home = root / "before", root / "after", root / "home"
        for d in (old_tree, new_tree, home):
            d.mkdir()
        _write_tree(old_tree, before)
        _write_tree(new_tree, after)
        try:
            old = runner(old_tree, home)
            new = runner(new_tree, home)
        except FileNotFoundError:
            return CheckResult(tool, "skipped", detail=f"{tool} is not installed")
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            return CheckResult(tool, "error", detail=str(exc)[:300])
    remaining = Counter(d.key() for d in old)
    introduced = []
    for diag in new:
        if remaining[diag.key()] > 0:
            remaining[diag.key()] -= 1
        else:
            introduced.append(diag)
    status = "new-issues" if introduced else "ok"
    return CheckResult(tool, status, introduced, f"{len(old)} before, {len(new)} after")


def lint_delta(snapshot: RepoSnapshot, changed: Mapping[str, str]) -> CheckResult:
    before = {p: snapshot.text(p) for p in snapshot.paths() if p.endswith(".py")}
    return _delta("ruff", _run_ruff, before, {**before, **changed})


def typecheck_delta(snapshot: RepoSnapshot, changed: Mapping[str, str]) -> CheckResult:
    if not _mypy_available():
        return CheckResult("mypy", "skipped", detail="mypy is not installed")
    before = {p: snapshot.text(p) for p in snapshot.paths() if p.endswith(".py")}
    return _delta("mypy", _run_mypy, before, {**before, **changed})


# ---------------------------------------------------------------- security review


@dataclass(frozen=True)
class SecurityFinding:
    path: str
    rule: str
    severity: str  # "high" | "medium"
    detail: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.path}: {self.rule}: {self.detail}"


_CALL_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "process-execution",
        "high",
        re.compile(
            r"^(os\.(system|popen|exec\w*|spawn\w*|fork\w*|posix_spawn\w*)"
            r"|subprocess\.\w+|pty\.spawn)$"
        ),
    ),
    (
        "dynamic-code",
        "high",
        re.compile(r"^(eval|exec|compile|__import__|importlib\.import_module)$"),
    ),
    (
        "unsafe-deserialization",
        "high",
        re.compile(r"^(pickle\.loads?|cPickle\.loads?|marshal\.loads?|shelve\.open|dill\.loads?)$"),
    ),
    (
        "network",
        "high",
        re.compile(
            r"^(socket\.\w+|urllib\.request\.\w+|http\.client\.\w+|requests\.\w+"
            r"|httpx\.\w+|ftplib\.\w+|smtplib\.\w+)$"
        ),
    ),
    ("native-code", "high", re.compile(r"^ctypes\.\w+")),
    (
        "filesystem-destruction",
        "medium",
        re.compile(r"^(shutil\.rmtree|os\.(remove|unlink|rmdir|removedirs|chmod|chown))$"),
    ),
    ("insecure-temp-file", "medium", re.compile(r"^tempfile\.mktemp$")),
)
_RISKY_IMPORTS = {
    "subprocess": "process-execution",
    "socket": "network",
    "ctypes": "native-code",
    "pickle": "unsafe-deserialization",
    "marshal": "unsafe-deserialization",
    "requests": "network",
    "httpx": "network",
    "urllib.request": "network",
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _constructs(source: str) -> Counter[tuple[str, str, str]] | None:
    """Multiset of (rule, severity, detail) for risky constructs in ``source``."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    found: Counter[tuple[str, str, str]] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name:
                head, _, rest = name.partition(".")
                resolved = aliases.get(head, head) + (f".{rest}" if rest else "")
                for rule, severity, pattern in _CALL_RULES:
                    if pattern.match(resolved):
                        found[(rule, severity, f"call to {resolved}()")] += 1
                if resolved == "yaml.load" and not any(k.arg == "Loader" for k in node.keywords):
                    found[("unsafe-deserialization", "high", "yaml.load() without a Loader")] += 1
            for keyword in node.keywords:
                value = keyword.value
                if (
                    keyword.arg == "shell"
                    and isinstance(value, ast.Constant)
                    and value.value is True
                ):
                    found[("shell-injection", "high", "shell=True")] += 1
                if (
                    keyword.arg == "verify"
                    and isinstance(value, ast.Constant)
                    and value.value is False
                ):
                    found[("tls-verification-disabled", "high", "verify=False")] += 1
        elif isinstance(node, ast.Import | ast.ImportFrom):
            modules = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for module in modules:
                for risky, rule in _RISKY_IMPORTS.items():
                    if module == risky or module.startswith(risky + "."):
                        found[(rule, "high", f"imports {module}")] += 1
        elif isinstance(node, ast.Raise):
            found[("raise", "info", "raise")] += 1
    return found


def security_review(snapshot: RepoSnapshot, changed: Mapping[str, str]) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for path, new_text in sorted(changed.items()):
        old_text = snapshot.text(path) if path in snapshot.files else ""
        old_lines = set(old_text.splitlines())
        added = [line for line in new_text.splitlines() if line not in old_lines]
        hidden = [line for line in added if HIDDEN_CHARS.search(line)]
        if hidden:
            findings.append(
                SecurityFinding(
                    path,
                    "hidden-characters",
                    "high",
                    f"{len(hidden)} added line(s) contain control or bidirectional characters "
                    "that can hide code from a reviewer",
                )
            )
        _, secrets = redact_secrets("\n".join(added))
        for redaction in secrets:
            findings.append(
                SecurityFinding(
                    path, "hard-coded-secret", "high", f"{redaction.count} {redaction.kind}"
                )
            )
        if not path.endswith(".py"):
            continue
        before, after = _constructs(old_text), _constructs(new_text)
        if before is None or after is None:
            continue
        for (rule, severity, detail), count in sorted((after - before).items()):
            if rule != "raise":
                findings.append(SecurityFinding(path, rule, severity, f"{detail} (+{count})"))
        removed_raises = before[("raise", "info", "raise")] - after[("raise", "info", "raise")]
        if removed_raises > 0:
            findings.append(
                SecurityFinding(
                    path,
                    "removed-validation",
                    "medium",
                    f"{removed_raises} raise statement(s) removed; "
                    "check that no validation was dropped",
                )
            )
    return findings
