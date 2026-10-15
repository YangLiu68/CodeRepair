"""Issue parsing.

The issue text is untrusted input. Parsing only extracts hints for retrieval
(file paths, identifiers, traceback frames, test ids) and flags injection
attempts; nothing in an issue is ever executed.
"""

from __future__ import annotations

import builtins
import keyword
import re
from dataclasses import dataclass, field

from .security import InjectionFinding, scan_for_injection

_FENCE_RE = re.compile(r"^```[ \t]*([\w+-]*)[ \t]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_FRAME_RE = re.compile(r'File "([^"\n]+)", line (\d+), in ([\w<>.]+)')
_EXCEPTION_RE = re.compile(
    r"^\s*(?:E\s+)?([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))(?::\s*(.*))?$",
    re.MULTILINE,
)
_TEST_ID_RE = re.compile(r"((?:[\w.\-]+/)*test_[\w.\-]*\.py::[\w\[\]\-.:]+)")
_FILE_RE = re.compile(
    r"(?<![\w.\-])((?:/?[\w.\-]+/)*[\w\-]+\.(?:py|pyi|toml|cfg|ini|json|ya?ml|md|txt|rst))\b"
)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_SNAKE_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b")
_CAMEL_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|[A-Z]{2,}[a-z][A-Za-z0-9]*)\b")
_DOTTED_RE = re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_IGNORED_IDENTIFIERS = (
    frozenset(dir(builtins))
    | frozenset(keyword.kwlist)
    | frozenset({"self", "cls", "args", "kwargs", "stdin", "module", "assert", "python", "pip"})
)


@dataclass(frozen=True)
class CodeBlock:
    language: str
    text: str


@dataclass(frozen=True)
class TracebackFrame:
    path: str
    line: int
    function: str


@dataclass(frozen=True)
class ParsedIssue:
    title: str
    body: str
    raw: str
    code_blocks: tuple[CodeBlock, ...] = ()
    traceback_frames: tuple[TracebackFrame, ...] = ()
    exception: str | None = None
    file_mentions: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    test_ids: tuple[str, ...] = ()
    injection_findings: tuple[InjectionFinding, ...] = field(default=())

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "code_blocks": [{"language": b.language, "text": b.text} for b in self.code_blocks],
            "traceback_frames": [vars(f) for f in self.traceback_frames],
            "exception": self.exception,
            "file_mentions": list(self.file_mentions),
            "identifiers": list(self.identifiers),
            "test_ids": list(self.test_ids),
            "injection_findings": [vars(f) for f in self.injection_findings],
        }


def _dedupe(items) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for item in items:
        if item and item not in seen:
            seen[item] = None
    return tuple(seen)


def _identifier_ok(name: str) -> bool:
    return len(name) >= 3 and name not in _IGNORED_IDENTIFIERS and not name.isdigit()


def _extract_identifiers(text: str, code_blocks: tuple[CodeBlock, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for snippet in _INLINE_CODE_RE.findall(text):
        for dotted in _DOTTED_RE.findall(snippet):
            found.extend(dotted.split("."))
        found.extend(_IDENT_RE.findall(snippet))
    for block in code_blocks:
        found.extend(_CALL_RE.findall(block.text))
        for dotted in _DOTTED_RE.findall(block.text):
            found.extend(dotted.split("."))
    found.extend(_CALL_RE.findall(text))
    found.extend(_SNAKE_RE.findall(text))
    found.extend(_CAMEL_RE.findall(text))
    return _dedupe(name for name in found if _identifier_ok(name))


def _indented_blocks(text: str) -> list[CodeBlock]:
    blocks: list[CodeBlock] = []
    current: list[str] = []
    previous_blank = True
    for line in text.splitlines():
        if (line.startswith("    ") or line.startswith("\t")) and (current or previous_blank):
            current.append(line[4:] if line.startswith("    ") else line[1:])
        else:
            if current:
                blocks.append(CodeBlock("", "\n".join(current)))
                current = []
        previous_blank = not line.strip()
    if current:
        blocks.append(CodeBlock("", "\n".join(current)))
    return blocks


def parse_issue(text: str, *, source: str = "issue") -> ParsedIssue:
    raw = text.replace("\r\n", "\n")
    lines = raw.split("\n")
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip():
            title = line.strip().lstrip("#").strip()
            body_start = i + 1
            break
    body = "\n".join(lines[body_start:]).strip("\n")

    fenced = [CodeBlock(lang.lower(), code.rstrip("\n")) for lang, code in _FENCE_RE.findall(raw)]
    without_fences = _FENCE_RE.sub("", raw)
    code_blocks = tuple(fenced + _indented_blocks(without_fences))

    frames = tuple(
        TracebackFrame(path, int(line), func) for path, line, func in _FRAME_RE.findall(raw)
    )
    exceptions = _EXCEPTION_RE.findall(raw)
    exception = None
    if exceptions:
        name, message = exceptions[-1]
        exception = f"{name}: {message}".rstrip(": ") if message else name

    test_ids = _dedupe(_TEST_ID_RE.findall(raw))
    file_mentions = _dedupe(
        [frame.path for frame in frames]
        + [tid.split("::", 1)[0] for tid in test_ids]
        + _FILE_RE.findall(raw)
    )
    return ParsedIssue(
        title=title[:200],
        body=body,
        raw=raw,
        code_blocks=code_blocks,
        traceback_frames=frames,
        exception=exception,
        file_mentions=file_mentions,
        identifiers=_extract_identifiers(raw, code_blocks),
        test_ids=test_ids,
        injection_findings=tuple(scan_for_injection(raw, source)),
    )
