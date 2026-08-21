import numpy as np
import pytest

from autopsy.measure.stats import (hl_exact_ci, hodges_lehmann_ratio,
                                   required_n, verdict)


def test_identical_deterministic_values_are_identical():
    v = verdict([100.0] * 3, [100.0] * 3)
    assert v.verdict == "IDENTICAL"
    assert v.kind == "exact"
    assert v.p is None


def test_deterministic_difference_skips_inference_entirely():
    """A +1 difference on a zero-variance metric must not produce a p-value."""
    v = verdict([1_000_000.0], [1_000_001.0])
    assert v.kind == "exact"
    assert v.p is None, "hypothesis testing on a deterministic metric is invalid"
    assert v.verdict == "CHANGED_BELOW_THRESHOLD"


def test_large_deterministic_regression_is_confirmed():
    v = verdict([100.0], [130.0])
    assert v.verdict == "REGRESSION"
    assert v.kind == "exact"
    assert v.shift == pytest.approx(0.30)


def test_clear_sampled_regression_is_confirmed():
    rng = np.random.default_rng(7)
    a = rng.normal(100, 0.5, 30)
    b = rng.normal(110, 0.5, 30)
    v = verdict(list(a), list(b))
    assert v.verdict == "REGRESSION_CONFIRMED"
    assert v.kind == "sampled"
    assert v.ci[0] > 0.02


def test_noisy_data_is_inconclusive_not_negative():
    """The verdict the document's rule cannot express."""
    rng = np.random.default_rng(11)
    a = rng.normal(100, 15, 15)
    b = rng.normal(101, 15, 15)
    v = verdict(list(a), list(b))
    assert v.verdict == "INCONCLUSIVE_UNDERPOWERED"


def test_ci_is_asymmetric_and_stored_independently():
    rng = np.random.default_rng(3)
    a, b = rng.normal(100, 2, 20), rng.normal(104, 5, 20)
    lo, hi = hl_exact_ci(np.asarray(a), np.asarray(b))
    mid = hodges_lehmann_ratio(np.asarray(a), np.asarray(b))
    assert not np.isclose(mid - lo, hi - mid, rtol=1e-3), \
        "CI treated as symmetric; it is not"


def test_required_n_scales_with_noise():
    assert required_n(cv=0.001, mde=0.02) < 5
    assert required_n(cv=0.10, mde=0.02) > 300


def test_multiple_comparisons_tighten_the_bar():
    rng = np.random.default_rng(5)
    a, b = rng.normal(100, 1.0, 20), rng.normal(101.5, 1.0, 20)
    lone = verdict(list(a), list(b), m_tests=1)
    many = verdict(list(a), list(b), m_tests=50)
    assert (many.ci[1] - many.ci[0]) > (lone.ci[1] - lone.ci[0])
