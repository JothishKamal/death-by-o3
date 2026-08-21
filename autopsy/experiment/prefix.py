from __future__ import annotations

from dataclasses import dataclass

from ..model import Invocation, Run

# Fields that must match for two invocations to be considered identical.
# wall_ns is excluded: it is a timing measurement, not part of the pipeline.
_IDENTITY_FIELDS = (
    "seq", "parent_seq", "depth", "pass_class", "pass_name", "role", "kind",
    "unit_name", "func", "occurrence", "required", "status", "changed",
    "hash_before", "hash_after",
)


def _key(inv: Invocation) -> tuple:
    return tuple(getattr(inv, f, None) for f in _IDENTITY_FIELDS
                 if f not in ("hash_before", "hash_after")) + (inv.guard,)


@dataclass(frozen=True)
class PrefixReport:
    identical_records: int
    target_reached: bool
    first_divergence: int | None

    @property
    def ok(self) -> bool:
        return self.target_reached and self.first_divergence is not None


def compare(baseline: Run, variant: Run, target_seq: int) -> PrefixReport:
    """Verify the variant matches the baseline on every record before target_seq."""
    identical = 0
    first_div = None
    for b, v in zip(baseline.invocations, variant.invocations):
        if _key(b) == _key(v):
            identical += 1
        else:
            first_div = b.seq
            break

    target_reached = identical == target_seq - 1 and first_div == target_seq
    if first_div is None:
        # No divergence at all -- the runs are identical.
        return PrefixReport(identical_records=identical,
                            target_reached=False, first_divergence=None)
    return PrefixReport(identical_records=identical,
                        target_reached=target_reached,
                        first_divergence=first_div)
