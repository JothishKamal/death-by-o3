from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import stats as _st


@dataclass(frozen=True)
class Verdict:
    verdict: str
    shift: float
    kind: str                 # "exact" | "sampled"
    ci: tuple | None = None
    p: float | None = None
    method: str | None = None
    note: str = ""

    @property
    def ci_width(self) -> float | None:
        return None if self.ci is None else self.ci[1] - self.ci[0]


def hodges_lehmann_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """Median of all pairwise differences, as a fraction of the baseline median.

    This is exactly the estimator Mann-Whitney implicitly tests, so estimate and
    test stay consistent. It differs from the naive median-difference.
    """
    d = (b[:, None] - a[None, :]).ravel()
    return float(np.median(d) / np.median(a))


def hl_exact_ci(a: np.ndarray, b: np.ndarray, alpha: float = 0.05) -> tuple:
    """Distribution-free CI for the HL shift, from rank-sum order statistics.

    Better calibrated at small n than bootstrapping a median, which takes few
    distinct values and is badly behaved.
    """
    m, n = len(a), len(b)
    d = np.sort((b[:, None] - a[None, :]).ravel())
    z = _st.norm.ppf(1 - alpha / 2)
    k = int(np.floor(max(m * n / 2 - z * np.sqrt(m * n * (m + n + 1) / 12) - 0.5, 0)))
    med = float(np.median(a))
    return d[k] / med, d[len(d) - 1 - k] / med


def required_n(cv: float, mde: float, alpha: float = 0.05,
               power: float = 0.80) -> int:
    """Samples per group for Mann-Whitney (ARE 0.955 vs the t-test).

    Run this BEFORE collecting. Rule of thumb it encodes: at n=15 the minimum
    detectable effect is about 1.11 x CV.
    """
    z_a = _st.norm.ppf(1 - alpha / 2)
    z_b = _st.norm.ppf(power)
    return max(1, int(np.ceil(2 * ((z_a + z_b) * cv / mde) ** 2 / 0.955)))


def verdict(a, b, threshold: float = 0.02, alpha: float = 0.05,
            m_tests: int = 1) -> Verdict:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    alpha_c = alpha / max(1, m_tests)

    # Deterministic fast path: Callgrind, llvm-size, IR counts, llvm-mca.
    # Hypothesis testing here is a category error -- there is no sampling
    # distribution, and a +1 difference would read as p = 8.3e-8.
    if np.ptp(a) == 0 and np.ptp(b) == 0:
        if b[0] == a[0]:
            return Verdict("IDENTICAL", 0.0, "exact", ci=(0.0, 0.0),
                           note="exact difference; no inference performed")
        d = (b[0] - a[0]) / a[0]
        name = ("REGRESSION" if d > threshold else
                "IMPROVEMENT" if d < -threshold else "CHANGED_BELOW_THRESHOLD")
        return Verdict(name, float(d), "exact", ci=(float(d), float(d)),
                       note="exact difference; no inference performed")

    ties = len(np.unique(np.concatenate([a, b]))) < len(a) + len(b)
    method = "asymptotic" if ties else "exact"   # never leave this on "auto"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = float(_st.mannwhitneyu(a, b, alternative="two-sided",
                                   method=method).pvalue)
    hl = hodges_lehmann_ratio(a, b)
    lo, hi = hl_exact_ci(a, b, alpha_c)
    sig = p < alpha_c

    if lo > threshold:
        name = "REGRESSION_CONFIRMED"
    elif hi < -threshold:
        name = "IMPROVEMENT_CONFIRMED"
    elif sig and hl > threshold:
        name = "REGRESSION_LIKELY"
    elif sig and hl < -threshold:
        name = "IMPROVEMENT_LIKELY"
    elif not sig and (hi - lo) > 2 * threshold:
        name = "INCONCLUSIVE_UNDERPOWERED"
    elif abs(hi) < threshold and abs(lo) < threshold:
        name = "NO_CHANGE_RULED_OUT"
    else:
        name = "CHANGED_BELOW_THRESHOLD"

    return Verdict(name, hl, "sampled", ci=(lo, hi), p=p, method=method)
