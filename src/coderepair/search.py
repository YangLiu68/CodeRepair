"""Read-only code search over a :class:`RepoSnapshot`.

Provides literal/regex grep, a Python symbol index built with ``ast`` (parsing
only, nothing is imported or executed), a module import graph, and BM25 ranking.
There are deliberately no write operations here.
"""

from __future__ import annotations

import ast
import fnmatch
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath

from .repo import RepoSnapshot

MAX_REGEX_LENGTH = 200
MAX_SCAN_LINE_LENGTH = 2_000

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL_SPLIT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have i if in into is it its of on or so
    that the their then there these this to was were when which while will with you your
    def return self cls import none true false class pass not elif else try except raise
    lambda yield async await global nonlocal assert del is we our can does do did get got
    should would could expected actual instead also only one two""".split()
)


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    return (
        any(part in {"tests", "test", "testing"} for part in p.parts[:-1])
        or (name.startswith("test_") and name.endswith(".py"))
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def module_name(path: str) -> str | None:
    """``pkg/sub/mod.py`` -> ``pkg.sub.mod``; ``pkg/__init__.py`` -> ``pkg``."""
    p = PurePosixPath(path)
    if p.suffix != ".py":
        return None
    parts = list(p.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def tokenize(text: str) -> list[str]:
    """Identifier-aware tokens: ``total_covered`` -> total_covered, total, covered."""
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        lowered = raw.lower()
        pieces = [
            piece.lower() for chunk in raw.split("_") for piece in _CAMEL_SPLIT_RE.findall(chunk)
        ]
        if lowered not in _STOPWORDS and len(lowered) > 1:
            tokens.append(lowered)
        if len(pieces) > 1:
            tokens.extend(p for p in pieces if p not in _STOPWORDS and len(p) > 1)
    return tokens


@dataclass(frozen=True)
class Symbol:
    name: str
    qualname: str
    kind: str
    path: str
    line: int
    end_line: int


@dataclass(frozen=True)
class GrepMatch:
    path: str
    line: int
    text: str


class _SymbolVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.stack: list[str] = []
        self.symbols: list[Symbol] = []

    def _add(self, node: ast.AST, name: str, kind: str) -> None:
        qual = ".".join([*self.stack, name])
        end = getattr(node, "end_lineno", None) or node.lineno
        self.symbols.append(Symbol(name, qual, kind, self.path, node.lineno, end))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add(node, node.name, "class")
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._add(node, node.name, "method" if self.stack else "function")
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self.stack:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._add(node, target.id, "variable")


def _resolve_import(module: str | None, level: int, current: str, is_package: bool) -> str | None:
    if level == 0:
        return module
    base = current.split(".") if current else []
    if not is_package:
        base = base[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)] if level - 1 <= len(base) else []
    if module:
        base = base + module.split(".")
    return ".".join(base) or None


class RepoIndex:
    """Search structures for one snapshot. Built once; read-only afterwards."""

    def __init__(self, snapshot: RepoSnapshot) -> None:
        self.snapshot = snapshot
        self.symbols: list[Symbol] = []
        self.parse_errors: dict[str, str] = {}
        self.imports: dict[str, set[str]] = {}
        self._module_to_path: dict[str, str] = {}
        for path in snapshot.paths():
            mod = module_name(path)
            if mod:
                self._module_to_path[mod] = path
        for path in snapshot.paths():
            if path.endswith(".py"):
                self._index_python(path)
        self._build_bm25()

    # ------------------------------------------------------------------ python
    def _index_python(self, path: str) -> None:
        try:
            tree = ast.parse(self.snapshot.text(path), filename=path)
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            self.parse_errors[path] = f"{type(exc).__name__}: {exc}"
            self.imports[path] = set()
            return
        visitor = _SymbolVisitor(path)
        visitor.visit(tree)
        self.symbols.extend(visitor.symbols)
        current = module_name(path) or ""
        is_package = path.endswith("__init__.py")
        targets: set[str] = set()
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                resolved = _resolve_import(node.module, node.level, current, is_package)
                if resolved:
                    names = [resolved] + [f"{resolved}.{alias.name}" for alias in node.names]
            for name in names:
                target = self._module_to_path.get(name)
                if target and target != path:
                    targets.add(target)
        self.imports[path] = targets

    def imported_by(self, path: str) -> list[str]:
        return sorted(src for src, targets in self.imports.items() if path in targets)

    def find_symbol(self, name: str) -> list[Symbol]:
        return [s for s in self.symbols if s.name == name or s.qualname == name]

    def symbols_in(self, path: str) -> list[Symbol]:
        return [s for s in self.symbols if s.path == path]

    # -------------------------------------------------------------------- grep
    def list_files(self, pattern: str | None = None) -> list[str]:
        paths = self.snapshot.paths()
        return [p for p in paths if pattern is None or fnmatch.fnmatchcase(p, pattern)]

    def read(self, path: str, start: int = 1, end: int | None = None) -> str:
        lines = self.snapshot.text(path).splitlines()
        start = max(start, 1)
        end = len(lines) if end is None else min(end, len(lines))
        return "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(start, end + 1))

    def grep(
        self,
        query: str,
        *,
        regex: bool = False,
        case_sensitive: bool = False,
        path_glob: str | None = None,
        max_results: int = 100,
    ) -> list[GrepMatch]:
        if not query:
            return []
        flags = 0 if case_sensitive else re.IGNORECASE
        if regex:
            if len(query) > MAX_REGEX_LENGTH:
                raise ValueError(f"regex longer than {MAX_REGEX_LENGTH} characters")
            pattern = re.compile(query, flags)
        else:
            pattern = re.compile(re.escape(query), flags)
        results: list[GrepMatch] = []
        for path in self.list_files(path_glob):
            for lineno, line in enumerate(self.snapshot.text(path).splitlines(), start=1):
                if pattern.search(line[:MAX_SCAN_LINE_LENGTH]):
                    results.append(GrepMatch(path, lineno, line.rstrip()[:300]))
                    if len(results) >= max_results:
                        return results
        return results

    # -------------------------------------------------------------------- bm25
    def _build_bm25(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1, self._b = k1, b
        self._doc_tf: dict[str, Counter[str]] = {}
        self._doc_len: dict[str, int] = {}
        df: Counter[str] = Counter()
        for path in self.snapshot.paths():
            path_tokens = tokenize(path.replace("/", " ").replace(".", " "))
            symbol_tokens = [t for s in self.symbols_in(path) for t in tokenize(s.name)]
            tokens = tokenize(self.snapshot.text(path)) + path_tokens * 3 + symbol_tokens * 2
            tf = Counter(tokens)
            self._doc_tf[path] = tf
            self._doc_len[path] = max(len(tokens), 1)
            df.update(tf.keys())
        n_docs = max(len(self._doc_tf), 1)
        self._avg_len = sum(self._doc_len.values()) / n_docs
        self._idf = {t: math.log(1 + (n_docs - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def bm25(self, query_tokens: list[str]) -> dict[str, float]:
        query = Counter(query_tokens)
        scores: dict[str, float] = {}
        for path, tf in self._doc_tf.items():
            score = 0.0
            norm = self._k1 * (1 - self._b + self._b * self._doc_len[path] / self._avg_len)
            for term, qf in query.items():
                f = tf.get(term)
                if f:
                    score += self._idf.get(term, 0.0) * f * (self._k1 + 1) / (f + norm) * min(qf, 3)
            scores[path] = score
        return scores
