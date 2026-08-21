from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

from ..model import Invocation
from .runner import address_of, run_experiment

# Passes whose interactions are known to mask one another (spec C18).
LOOP_CLUSTER = {
    "loop-vectorize", "slp-vectorizer", "loop-unroll", "loop-unroll-full",
    "licm", "simple-loop-unswitch", "indvars", "loop-idiom",
}


@dataclass
class PairResult:
    addresses: tuple
    decisions: tuple
    score: float
    usable: bool


def pairwise(src, out_dir, candidates: list[Invocation], score_fn,
             cluster: set = LOOP_CLUSTER, limit: int = 24) -> list[PairResult]:
    """Search pairs within the loop cluster for regressions single-veto misses.

    Only the FIRST address of a pair can be verified by guard, because after it
    applies the pipeline diverges and the second address's guard legitimately no
    longer matches. The pair is therefore expressed as: veto A by address, and
    disable B for the whole run via its pass name. That keeps A exact -- which is
    the decision under test -- while B is the masking context being removed.
    """
    src, out_dir = Path(src), Path(out_dir)
    members = [d for d in candidates if d.pass_name in cluster]
    if not members:
        return []

    results = []
    seen = set()
    n = 0
    for a, b in itertools.permutations(members, 2):
        if n >= limit:
            break
        if a.pass_name == b.pass_name:
            continue
        key = (address_of(a), b.pass_name)
        if key in seen:
            continue
        seen.add(key)

        exp = run_experiment(src, address_of(a), out_dir / f"pair{n:04d}")
        score = score_fn(exp) if exp.usable else float("-inf")
        results.append(PairResult(addresses=(address_of(a), b.pass_name),
                                  decisions=(a, b), score=score,
                                  usable=exp.usable))
        n += 1
    results.sort(key=lambda r: r.score, reverse=True)
    return results
