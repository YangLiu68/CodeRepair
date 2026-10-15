"""Security policy: which repositories may be read, which files are never read,
secret redaction for outbound prompts, and prompt-injection detection.

Everything read from a repository or an issue is treated as untrusted data.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class PolicyError(PermissionError):
    """Raised when a path or operation violates the security policy."""


# Locations under $HOME that must never be ingested, even if an allowed root is misconfigured.
DENIED_HOME_ENTRIES = (
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".kube",
    ".docker",
    ".config",
    ".netrc",
    ".git-credentials",
    ".password-store",
    ".local/share/keyrings",
    "Library/Keychains",
)
DENIED_SYSTEM_DIRS = (
    "/etc",
    "/private/etc",
    "/var/run",
    "/private/var/run",
    "/root",
    "/proc",
    "/sys",
)

# Directories skipped during ingestion because they are tooling output, not source.
IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".eggs",
        "dist",
        "build",
        ".idea",
    }
)
SENSITIVE_DIR_NAMES = frozenset({".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker"})

_SENSITIVE_NAME_GLOBS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "*.kdbx",
    "*.tfstate",
    "*.tfstate.*",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "service-account*.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
)
_SAFE_ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})


def is_sensitive_path(relpath: str) -> bool:
    """True for files that may hold credentials; they are never read or sent anywhere."""
    parts = PurePosixPath(relpath).parts
    if any(part in SENSITIVE_DIR_NAMES for part in parts[:-1]):
        return True
    name = parts[-1] if parts else relpath
    if name in _SAFE_ENV_TEMPLATES:
        return False
    return any(fnmatch.fnmatchcase(name.lower(), pattern) for pattern in _SENSITIVE_NAME_GLOBS)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def denied_locations(home: Path | None = None) -> list[Path]:
    home = (home or Path.home()).resolve()
    return [home / entry for entry in DENIED_HOME_ENTRIES] + [Path(d) for d in DENIED_SYSTEM_DIRS]


def resolve_repo_root(
    path: str | Path, allowed_roots: tuple[Path, ...], *, home: Path | None = None
) -> Path:
    """Resolve ``path`` (following symlinks) and check it against the repository policy.

    A repository root must be an existing directory inside one of ``allowed_roots``,
    must not be (or contain) the home directory, and must not sit inside a denied
    location such as ``~/.ssh`` or ``/etc``.
    """
    home = (home or Path.home()).resolve()
    try:
        real = Path(path).expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise PolicyError(f"repository path does not exist: {path}") from exc
    if not real.is_dir():
        raise PolicyError(f"repository path is not a directory: {real}")
    if real == home or _is_within(home, real):
        raise PolicyError(f"refusing to ingest the home directory or one of its parents: {real}")
    for denied in denied_locations(home):
        denied_real = denied.resolve() if denied.exists() else denied
        if _is_within(real, denied_real) or _is_within(real, denied):
            raise PolicyError(f"refusing to ingest a denied location: {real}")
    roots = [r.expanduser().resolve() for r in allowed_roots]
    if not any(_is_within(real, root) for root in roots):
        shown = ", ".join(str(r) for r in roots) or "(none)"
        raise PolicyError(
            f"{real} is outside the allowed roots [{shown}]; "
            "set CODEREPAIR_ALLOWED_ROOTS to allow it"
        )
    return real


# --------------------------------------------------------------------------- secrets

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
            re.DOTALL,
        ),
    ),
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"),
    ),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-style-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
)
_ASSIGNMENT_SECRET = re.compile(
    r"""(?ix)
    \b(password|passwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|token)\b
    (\s*[:=]\s*)
    (["'])([^"'\s]{8,})\3
    """
)


@dataclass(frozen=True)
class Redaction:
    kind: str
    count: int


def redact_secrets(text: str) -> tuple[str, list[Redaction]]:
    """Replace likely credentials with ``[REDACTED:<kind>]`` before text leaves the process."""
    found: list[Redaction] = []
    for kind, pattern in _SECRET_PATTERNS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        if n:
            found.append(Redaction(kind, n))

    def _assignment(match: re.Match[str]) -> str:
        return (
            f"{match.group(1)}{match.group(2)}{match.group(3)}[REDACTED:assignment]{match.group(3)}"
        )

    text, n = _ASSIGNMENT_SECRET.subn(_assignment, text)
    if n:
        found.append(Redaction("assignment", n))
    return text, found


# ---------------------------------------------------------------- prompt injection

_INJECTION_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "override-instructions",
        "high",
        re.compile(
            r"\b(?:ignore|disregard|forget|override)\b[^\n]{0,40}?"
            r"\b(?:previous|prior|above|earlier|all|the|your|any)\b[^\n]{0,20}?"
            r"\b(?:instructions?|prompts?|rules|messages|issue|guidelines)\b",
            re.IGNORECASE,
        ),
    ),
    ("system-override", "high", re.compile(r"\bsystem\s+(?:override|prompt|message)\b", re.I)),
    ("role-reassignment", "medium", re.compile(r"\byou are now\b|\bmaintenance mode\b", re.I)),
    (
        "addressed-to-agents",
        "medium",
        re.compile(
            r"\b(?:ai|llm)\s+(?:coding\s+)?(?:agents?|assistants?)\b|"
            r"\b(?:automated|autonomous)\s+agents?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "remote-code-execution",
        "high",
        re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba|z)?sh\b", re.IGNORECASE),
    ),
    (
        "credential-exfiltration",
        "high",
        re.compile(r"~/\.ssh|\bid_rsa\b|\.aws/credentials|\.netrc\b|\bprivate key\b", re.I),
    ),
    (
        "concealment",
        "high",
        re.compile(r"\bdo not (?:tell|mention|inform|reveal)\b[^\n]{0,30}\buser\b", re.I),
    ),
    (
        "test-tampering",
        "medium",
        re.compile(r"\b(?:delete|remove|skip|disable)\b[^\n]{0,15}\btests?\b", re.I),
    ),
)


@dataclass(frozen=True)
class InjectionFinding:
    source: str
    line: int
    rule: str
    severity: str
    excerpt: str


def scan_for_injection(text: str, source: str) -> list[InjectionFinding]:
    """Flag text that tries to instruct an AI agent. Findings are reported, never obeyed."""
    findings: list[InjectionFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule, severity, pattern in _INJECTION_PATTERNS:
            if pattern.search(line):
                excerpt = line.strip()
                if len(excerpt) > 160:
                    excerpt = excerpt[:157] + "..."
                findings.append(InjectionFinding(source, lineno, rule, severity, excerpt))
    return findings
