from __future__ import annotations

from dataclasses import dataclass

from ..model import Invocation, Run

# Published weights. Ranking exists to make the loop affordable -- hundreds of
# decisions cannot each be benchmarked -- and never confirms anything by itself.
WEIGHTS = {
    "ir_delta": 0.34,
    "hot_function": 0.25,
    "size_delta": 0.12,
    "pass_prior": 0.17,
    "drift_depth": 0.12,
}

# Measured on Tier A: only three pass families produce runtime regressions on
# x86-64. inline, simple-loop-unswitch, loop-idiom and full loop-unroll produced
# zero across nine designs.
PASS_PRIOR = {
    "simplifycfg": 1.00,     # largest measured regression, 4.99x
    "loop-vectorize": 0.95,
    "slp-vectorizer": 0.90,
    "loop-unroll": 0.70,
    "simple-loop-unswitch": 0.40,
    "inline": 0.40,
    "loop-idiom": 0.30,
    "licm": 0.30,
    "indvars": 0.25,
}
_DEFAULT_PRIOR = 0.10


@dataclass(frozen=True)
class Score:
    total: float
    components: dict


@dataclass(frozen=True)
class Suspect:
    rank: int
    decision: Invocation
    score: Score


@dataclass(frozen=True)
class RankReport:
    suspects: list
    verdict: str
    no_op_passes: set


def _ir_delta(d: Invocation) -> float:
    if not d.metrics_before or not d.metrics_after:
        return 0.0
    before = d.metrics_before.get("instructions", 0)
    after = d.metrics_after.get("instructions", 0)
    if not before:
        return 0.0
    return min(1.0, abs(after - before) / before)


def _size_delta(d: Invocation) -> float:
    if not d.metrics_before or not d.metrics_after:
        return 0.0
    before = d.metrics_before.get("ir_bytes") or d.metrics_before.get("instructions", 0)
    after = d.metrics_after.get("ir_bytes") or d.metrics_after.get("instructions", 0)
    if not before:
        return 0.0
    return min(1.0, abs(after - before) / before)


def _drift_depth(d: Invocation, run: Run) -> float:
    """Fewer downstream invocations means a cleaner experiment."""
    total = len(run.invocations)
    if not total:
        return 0.0
    remaining = total - d.seq
    return 1.0 - (remaining / total)


def score(d: Invocation, run: Run, hot_function: str | None = None) -> Score:
    components = {
        "ir_delta": _ir_delta(d),
        "hot_function": 1.0 if (hot_function and d.func == hot_function) else 0.0,
        "size_delta": _size_delta(d),
        "pass_prior": PASS_PRIOR.get(d.pass_name, _DEFAULT_PRIOR),
        "drift_depth": _drift_depth(d, run),
    }
    total = sum(WEIGHTS[k] * v for k, v in components.items())
    return Score(total=total, components=components)


def rank(run: Run, hot_function: str | None = None, limit: int = 10) -> RankReport:
    """Narrow every decision to the handful worth a counterfactual."""
    changed_passes = {i.pass_name for i in run.invocations if i.changed}
    no_op = {i.pass_name for i in run.invocations
             if i.role == "transform" and i.pass_name not in changed_passes}

    candidates = [d for d in run.decisions() if d.vetoable]
    scored = sorted(
        (Suspect(rank=0, decision=d, score=score(d, run, hot_function))
         for d in candidates),
        key=lambda s: s.score.total, reverse=True)[:limit]
    suspects = [Suspect(rank=n + 1, decision=s.decision, score=s.score)
                for n, s in enumerate(scored)]

    if not suspects or suspects[0].decision.pass_name in no_op:
        return RankReport(suspects=suspects, verdict="NO_CULPRIT_FOUND",
                          no_op_passes=no_op)
    return RankReport(suspects=suspects, verdict="RANKED", no_op_passes=no_op)
