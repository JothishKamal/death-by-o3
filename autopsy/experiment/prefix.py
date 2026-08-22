from __future__ import annotations

from dataclasses import dataclass

from ..model import Invocation, Run

# Fields that must match for two invocations to be considered identical.
# wall_ns is excluded: it is a timing measurement, not part of the pipeline.
_IDENTITY_FIELDS = (
    "seq", "parent_seq", "depth", "pass_class", "pass_name", "role", "kind",
    "unit_name", "func", "occurrence", "required", "status",
)

# Output fields of a record: what a pass's window OBSERVED. For strict
# ancestors of the veto target these may legitimately differ between baseline
# and variant -- an ancestor pops only after the target runs, so its change
# flag and snapshots include the vetoed child's work. Identity + guard (the
# input) must still match exactly.
_OUTPUT_FIELDS = ("changed", "blobs_after")


def _key(inv: Invocation) -> tuple:
    return tuple(getattr(inv, f, None) for f in _IDENTITY_FIELDS) + (inv.guard,)


def _output(inv: Invocation) -> tuple:
    return tuple(tuple(getattr(inv, f)) if isinstance(getattr(inv, f), tuple)
                 else getattr(inv, f) for f in _OUTPUT_FIELDS)


@dataclass(frozen=True)
class PrefixReport:
    identical_records: int
    target_reached: bool
    first_divergence: int | None

    @property
    def ok(self) -> bool:
        return self.target_reached and self.first_divergence is not None


def compare(baseline: Run, variant: Run, target_seq: int) -> PrefixReport:
    """Verify the variant matches the baseline on every record before target_seq.

    A record's identity (which pass ran, where, on which unit) and its guard
    hash (the IR it was given) must match exactly. Its OUTPUT fields may
    differ when the record is a strict ancestor of the target: the ancestor's
    observation window closes after the target runs, so it legitimately sees
    the vetoed invocation's effect. Any other difference is a real divergence.
    """
    by_seq = {i.seq: i for i in baseline.invocations}
    ancestors: set[int] = set()
    p = by_seq.get(target_seq).parent_seq if target_seq in by_seq else None
    while p is not None and p > 0:
        ancestors.add(p)
        p = by_seq[p].parent_seq if p in by_seq else None

    identical = 0
    first_div: int | None = None
    reached_target = False
    for b, v in zip(baseline.invocations, variant.invocations):
        if b.seq >= target_seq:
            reached_target = True
            break
        same_input = _key(b) == _key(v)
        is_ancestor = b.seq in ancestors
        same_output = _output(b) == _output(v)
        if same_input and (same_output or is_ancestor):
            identical += 1
        else:
            first_div = b.seq
            break

    if first_div is None and reached_target and identical == target_seq - 1:
        # Every pre-target record verified; the divergence begins AT the target.
        return PrefixReport(identical_records=identical,
                            target_reached=True, first_divergence=target_seq)
    if first_div is None:
        # The streams are identical throughout -- nothing diverged at all.
        return PrefixReport(identical_records=identical,
                            target_reached=False, first_divergence=None)
    return PrefixReport(identical_records=identical,
                        target_reached=False, first_divergence=first_div)
