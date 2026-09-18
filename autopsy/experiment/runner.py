from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..capture import REQUIRED_FLAGS, capture
from ..model import Invocation, Run
from .prefix import PrefixReport, compare
from .verify import Equivalence


def address_of(inv: Invocation) -> str:
    """Serialise a decision address into the AUTOPSY_VETO wire form."""
    return "|".join([inv.pass_class, inv.kind, inv.unit_name, inv.func,
                     str(inv.occurrence), inv.guard])


@dataclass(frozen=True)
class Experiment:
    address: str
    tier: int
    guard_matched: bool
    prefix: PrefixReport
    baseline_run: Run
    variant_run: Run
    baseline_obj: Path
    variant_obj: Path
    reproduce_cmd: str
    equivalence: Equivalence | None = None

    @property
    def usable(self) -> bool:
        """An experiment is only reportable if the veto landed where intended."""
        return self.guard_matched and self.prefix.ok


def run_experiment(src, address: str, out_dir, benchmark=None) -> Experiment:
    """Tier 1: recompile from source with an occurrence-scoped gate.

    Tier 1 is the authority. Tiers 2 and 3 are optimisations that must be
    confirmed against this result before they are trusted (spec 5.5).
    """
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = capture(src, out_dir / "baseline")
    variant = capture(src, out_dir / "variant", env_extra={"AUTOPSY_VETO": address})

    skipped = [i for i in variant.invocations if i.status == "skipped"]
    guard_matched = len(skipped) == 1

    target_seq = skipped[0].seq if guard_matched else 0
    prefix = compare(baseline, variant, target_seq) if guard_matched else \
        PrefixReport(identical_records=0, target_reached=False, first_divergence=None)

    flags = " ".join(REQUIRED_FLAGS)
    cmd = (f"clang -O3 {flags} -fpass-plugin=<autopsy> "
           f"-c {src.name}   # AUTOPSY_VETO='{address}'")

    return Experiment(
        address=address, tier=1, guard_matched=guard_matched, prefix=prefix,
        baseline_run=baseline, variant_run=variant,
        baseline_obj=out_dir / "baseline" / (src.stem + ".o"),
        variant_obj=out_dir / "variant" / (src.stem + ".o"),
        reproduce_cmd=cmd,
    )
