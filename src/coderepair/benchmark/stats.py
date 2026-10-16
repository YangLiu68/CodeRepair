"""Small-sample statistics for the comparative benchmark.

With a few dozen tasks and resolve rates near zero, point estimates mislead, so
every rate is reported with a Wilson score interval and every pair of agents is
compared on the *same* tasks with an exact McNemar test (a two-sided sign test
on the tasks where exactly one of the two agents succeeded). No dependencies:
the binomial tail is computed exactly with integers.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations


def wilson_interval(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion (0..1)."""
    if n <= 0:
        return (0.0, 1.0)
    if not 0 <= successes <= n:
        raise ValueError("successes must be between 0 and n")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return (lo, hi)


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts."""
    if only_a < 0 or only_b < 0:
        raise ValueError("counts must be non-negative")
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1))
    return min(1.0, 2 * tail / 2**n)


@dataclass(frozen=True)
class PairedComparison:
    a: str
    b: str
    tasks: int  # tasks both agents were run on
    both: int
    only_a: int
    only_b: int
    neither: int
    p_value: float

    @property
    def difference(self) -> int:
        """Resolved by ``a`` minus resolved by ``b`` on the shared tasks."""
        return self.only_a - self.only_b


def paired_comparisons(
    outcomes: dict[str, dict[str, bool]], agents: Iterable[str]
) -> list[PairedComparison]:
    """Compare every pair of agents on the tasks both were scored on.

    ``outcomes[agent][unit]`` is whether ``agent`` resolved ``unit`` (a task, or
    a (model, task) pair when several runs are pooled).
    """
    out = []
    for a, b in combinations(list(agents), 2):
        shared = sorted(set(outcomes.get(a, {})) & set(outcomes.get(b, {})))
        both = sum(outcomes[a][u] and outcomes[b][u] for u in shared)
        only_a = sum(outcomes[a][u] and not outcomes[b][u] for u in shared)
        only_b = sum(outcomes[b][u] and not outcomes[a][u] for u in shared)
        out.append(
            PairedComparison(
                a=a,
                b=b,
                tasks=len(shared),
                both=both,
                only_a=only_a,
                only_b=only_b,
                neither=len(shared) - both - only_a - only_b,
                p_value=mcnemar_exact(only_a, only_b),
            )
        )
    return out


def sign_flip_test(differences: Iterable[int]) -> float:
    """Exact two-sided paired permutation (sign-flip) test on per-task differences.

    Each task contributes one integer: (runs agent A resolved) - (runs agent B
    resolved), summed over every run of that task (several models or seeds).
    Under the null hypothesis each task's difference is equally likely to have
    either sign. Runs of the same task stay in one unit, so correlated runs do
    not inflate significance (duplicating every run leaves the p-value unchanged).
    With one run per task this is exactly McNemar's test.
    """
    values = [d for d in differences if d]
    if not values:
        return 1.0
    observed = abs(sum(values))
    nonzero = [abs(d) for d in values]
    counts: dict[int, int] = {0: 1}
    for d in nonzero:
        step: dict[int, int] = {}
        for total, ways in counts.items():
            step[total + d] = step.get(total + d, 0) + ways
            step[total - d] = step.get(total - d, 0) + ways
        counts = step
    extreme = sum(ways for total, ways in counts.items() if abs(total) >= observed)
    return min(1.0, extreme / 2 ** len(nonzero))


def format_p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"
