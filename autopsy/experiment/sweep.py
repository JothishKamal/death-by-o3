from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..model import Invocation
from .runner import Experiment, address_of, run_experiment


@dataclass
class SweepResult:
    address: str
    decision: Invocation
    experiment: Experiment
    score: float
    usable: bool


def sweep(src, out_dir, candidates: list[Invocation], score_fn) -> list[SweepResult]:
    """Run one counterfactual per candidate and rank by score.

    Single-veto ablation is necessary but NOT sufficient: a regression masked by
    another pass is invisible here and ranks last. See pairwise() (Task 9).
    """
    src, out_dir = Path(src), Path(out_dir)
    results = []
    for n, decision in enumerate(candidates):
        addr = address_of(decision)
        exp = run_experiment(src, addr, out_dir / f"exp{n:04d}")
        score = score_fn(exp) if exp.usable else float("-inf")
        results.append(SweepResult(address=addr, decision=decision,
                                   experiment=exp, score=score,
                                   usable=exp.usable))
    results.sort(key=lambda r: r.score, reverse=True)
    return results
