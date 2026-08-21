from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..capture import REQUIRED_FLAGS

_LINE = re.compile(r"BISECT: running pass \((\d+)\) (.+?) on (.+)$")


@dataclass(frozen=True)
class BisectEntry:
    index: int
    pass_name: str
    unit: str


def calibrate(src, opt_level: str = "-O3") -> list[BisectEntry]:
    """Enumerate every gated pass, using LLVM's own numbering.

    Our shouldRun counter cannot be used: it is middle-end only, and LLVM also
    gates backend passes running under a different pass manager.
    """
    result = subprocess.run(
        ["clang", opt_level, *REQUIRED_FLAGS,
         "-mllvm", "--opt-bisect=-1", "-c", str(Path(src)), "-o", "/dev/null"],
        capture_output=True, text=True)
    entries = []
    for line in result.stderr.splitlines():
        m = _LINE.match(line.strip())
        if m:
            entries.append(BisectEntry(index=int(m.group(1)),
                                       pass_name=m.group(2).strip(),
                                       unit=m.group(3).strip()))
    return entries


def bisect_range_excluding(index: int, total: int) -> str:
    """Build an --opt-bisect range list that runs everything except `index`."""
    parts = []
    if index > 1:
        parts.append(f"1-{index - 1}")
    if index < total:
        parts.append(f"{index + 1}-{total}")
    return ",".join(parts)


# Measured: with an ACTIVE range LLVM gates ~6 more trailing backend passes
# than the --opt-bisect=-1 listing shows (they only consult the bisector when
# it is enabled). A tail capped at the calibrated total would suppress them
# too, so the reproducibility string uses an open-ended upper bound instead.
UPPER_BOUND = 100_000


def bisect_range_excluding_open(index: int, upper: int = UPPER_BOUND) -> str:
    """Like bisect_range_excluding, but the tail extends to `upper`.

    This is what the reproduce command emits: it suppresses exactly one pass
    regardless of how many unlisted backend passes LLVM gates.
    """
    parts = []
    if index > 1:
        parts.append(f"1-{index - 1}")
    parts.append(f"{index + 1}-{upper}")
    return ",".join(parts)
