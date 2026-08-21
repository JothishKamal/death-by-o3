import numpy as np

from autopsy.measure.sampler import interleaved


def make_pair(seed, mean_a, mean_b, sd):
    rng = np.random.default_rng(seed)
    return (lambda: float(rng.normal(mean_a, sd)),
            lambda: float(rng.normal(mean_b, sd)))


def test_low_noise_stops_early():
    a, b = make_pair(1, 100, 110, 0.05)
    s = interleaved(a, b)
    assert s.n <= 12
    assert not s.capped


def test_high_noise_collects_many_more():
    a, b = make_pair(2, 100, 101, 12.0)
    s = interleaved(a, b, cap=60)
    assert s.n >= 40


def test_cap_is_reported_not_hidden():
    a, b = make_pair(3, 100, 100.5, 20.0)
    s = interleaved(a, b, cap=20)
    assert s.capped
    assert s.n == 20


def test_floor_is_respected_for_ranking():
    a, b = make_pair(4, 100, 200, 0.001)
    s = interleaved(a, b, floor=8)
    assert s.n >= 8, "n < 8 cannot survive multiple-comparisons correction"


def test_samples_are_collected_in_alternating_order():
    order = []
    a = lambda: (order.append("a"), 1.0)[1]
    b = lambda: (order.append("b"), 1.0)[1]
    interleaved(a, b, pilot=3, cap=6, floor=3)
    assert order[:6] == ["a", "b", "a", "b", "a", "b"], \
        "runs must alternate; batching flips verdicts"


def test_equal_counts_for_both_variants():
    a, b = make_pair(6, 100, 105, 1.0)
    s = interleaved(a, b)
    assert len(s.a) == len(s.b) == s.n
