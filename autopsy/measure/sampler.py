from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .stats import required_n


@dataclass
class Sample:
    a: list = field(default_factory=list)
    b: list = field(default_factory=list)
    cv: float = 0.0
    capped: bool = False

    @property
    def n(self) -> int:
        return len(self.a)


def interleaved(run_a, run_b, threshold: float = 0.02, pilot: int = 5,
                cap: int = 200, floor: int = 8) -> Sample:
    """Alternate A/B/A/B and grow the sample until it can answer the question.

    Batched min-of-N lies: it attributes between-process drift to the variant.
    Alternating makes drift common-mode.
    """
    s = Sample()
    for _ in range(pilot):
        s.a.append(run_a())
        s.b.append(run_b())

    arr = np.asarray(s.a, dtype=float)
    mean = float(np.mean(arr))
    s.cv = float(np.std(arr, ddof=1) / mean) if mean and len(arr) > 1 else 0.0

    target = max(floor, required_n(s.cv, threshold)) if s.cv > 0 else floor
    target = min(target, cap)

    while s.n < target:
        s.a.append(run_a())
        s.b.append(run_b())

    s.capped = s.n >= cap
    return s
