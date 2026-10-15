"""Rank repository files by relevance to an issue, with human-readable reasons."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .issue import ParsedIssue
from .repo import RepoSnapshot
from .search import RepoIndex, is_test_path, tokenize

# Weights are fixed constants, not tuned per task; see BENCHMARK.md for how they were chosen.
W_BM25 = 1.0
W_PATH_MENTION = 2.0
W_TRACEBACK = 3.0
W_SYMBOL = 1.5
W_SYMBOL_CAP = 3.0
W_FAILING_TEST_IMPORT = 1.0
W_IMPORT_PROPAGATION = 0.3
NON_CODE_FACTOR = 0.3
REEXPORT_FACTOR = 0.5


@dataclass
class RankedFile:
    path: str
    score: float
    is_test: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "score": round(self.score, 4),
            "is_test": self.is_test,
            "reasons": self.reasons,
        }


def resolve_mention(mention: str, paths: list[str]) -> list[str]:
    """Map a path from an issue (possibly absolute or from another machine) to repo paths."""
    mention_parts = [
        p for p in PurePosixPath(mention.replace("\\", "/")).parts if p not in ("/", ".")
    ]
    if not mention_parts:
        return []
    best: list[str] = []
    best_len = 0
    for path in paths:
        parts = PurePosixPath(path).parts
        n = 0
        while n < min(len(parts), len(mention_parts)) and parts[-1 - n] == mention_parts[-1 - n]:
            n += 1
        if n == 0:
            continue
        if n > best_len:
            best, best_len = [path], n
        elif n == best_len:
            best.append(path)
    # A bare file name that matches several files is too ambiguous to trust.
    return best if (best_len >= 2 or len(best) == 1) else []


def _closure(index: RepoIndex, start: str, depth: int) -> set[str]:
    seen: set[str] = set()
    frontier = {start}
    for _ in range(depth):
        nxt: set[str] = set()
        for path in frontier:
            for target in index.imports.get(path, ()):
                if target not in seen and target != start:
                    seen.add(target)
                    nxt.add(target)
        frontier = nxt
    return seen


def rank_files(snapshot: RepoSnapshot, index: RepoIndex, issue: ParsedIssue) -> list[RankedFile]:
    paths = snapshot.paths()
    ranked = {p: RankedFile(p, 0.0, is_test_path(p)) for p in paths}

    # 1. Lexical similarity between the whole issue and each file.
    bm25 = index.bm25(tokenize(issue.raw))
    top = max(bm25.values(), default=0.0) or 1.0
    for path, score in bm25.items():
        if score > 0:
            ranked[path].score += W_BM25 * score / top
            ranked[path].reasons.append(f"lexical match {score / top:.2f}")

    # 2. Files named in the issue text, test ids or traceback frames.
    frame_paths = {frame.path for frame in issue.traceback_frames}
    for mention in issue.file_mentions:
        for path in resolve_mention(mention, paths):
            if mention in frame_paths:
                lines = [f.line for f in issue.traceback_frames if f.path == mention]
                ranked[path].score += W_TRACEBACK
                ranked[path].reasons.append(f"traceback frame (line {', '.join(map(str, lines))})")
            else:
                ranked[path].score += W_PATH_MENTION
                ranked[path].reasons.append(f"mentioned in issue as {mention!r}")

    # 3. Files defining identifiers the issue names.
    wanted = set(issue.identifiers)
    for path in paths:
        defined = sorted({s.name for s in index.symbols_in(path) if s.name in wanted})
        if defined:
            ranked[path].score += min(W_SYMBOL * len(defined), W_SYMBOL_CAP)
            ranked[path].reasons.append("defines " + ", ".join(f"`{d}`" for d in defined))

    # 4. Source modules imported (transitively) by failing tests named in the issue.
    failing_tests = {
        p for tid in issue.test_ids for p in resolve_mention(tid.split("::")[0], paths)
    }
    for test_path in failing_tests:
        for target in _closure(index, test_path, depth=2):
            ranked[target].score += W_FAILING_TEST_IMPORT
            ranked[target].reasons.append(f"imported by failing test {test_path}")

    # 5. Down-weight files that rarely hold a fix: docs/config and pure re-export modules.
    for path, item in ranked.items():
        if not path.endswith(".py"):
            item.score *= NON_CODE_FACTOR
        elif PurePosixPath(path).name == "__init__.py" and not any(
            s.kind != "variable" for s in index.symbols_in(path)
        ):
            item.score *= REEXPORT_FACTOR

    # 6. Propagate a little relevance along imports from the strongest source files.
    base_scores = {p: r.score for p, r in ranked.items()}
    strongest = sorted(
        (p for p in paths if not ranked[p].is_test and base_scores[p] > 0),
        key=lambda p: -base_scores[p],
    )[:3]
    for src in strongest:
        for target in index.imports.get(src, ()):
            if ranked[target].is_test:
                continue
            bonus = W_IMPORT_PROPAGATION * base_scores[src]
            ranked[target].score += bonus
            ranked[target].reasons.append(f"imported by {src}")

    return sorted(ranked.values(), key=lambda r: (-r.score, r.path))


def source_ranking(ranked: list[RankedFile]) -> list[RankedFile]:
    return [r for r in ranked if not r.is_test and r.score > 0]


def rank_test_files(
    ranked: list[RankedFile], issue: ParsedIssue, index: RepoIndex
) -> list[RankedFile]:
    """Test files worth showing: named by the issue first, then those importing top sources."""
    sources = [r.path for r in source_ranking(ranked)[:3]]
    named = {
        p
        for tid in issue.test_ids
        for p in resolve_mention(tid.split("::")[0], index.snapshot.paths())
    }
    tests = [r for r in ranked if r.is_test and r.path.endswith(".py")]
    imports_top = {r.path: bool(_closure(index, r.path, depth=2) & set(sources)) for r in tests}

    def key(r: RankedFile) -> tuple:
        return (r.path not in named, not imports_top[r.path], -r.score, r.path)

    return [
        r for r in sorted(tests, key=key) if r.path in named or imports_top[r.path] or r.score > 0
    ]
