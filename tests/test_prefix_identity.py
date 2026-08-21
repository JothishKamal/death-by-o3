import pytest

from autopsy.experiment.prefix import compare
from tests.test_veto_basic import find_target, veto_arg


@pytest.fixture
def pair(capture_run, fixture_dir):
    base = capture_run(fixture_dir / "gemm.c")
    target = find_target([r.__dict__ for r in base.invocations])
    variant = capture_run(fixture_dir / "gemm.c",
                          env={"AUTOPSY_VETO": veto_arg(target)})
    return base, variant, target


def test_prefix_is_identical_up_to_the_target(pair):
    base, variant, target = pair
    report = compare(base, variant, target["seq"])
    assert report.ok
    assert report.identical_records == target["seq"] - 1
    assert report.target_reached


def test_divergence_begins_at_the_target(pair):
    base, variant, target = pair
    report = compare(base, variant, target["seq"])
    assert report.first_divergence == target["seq"]


def test_identical_runs_have_no_divergence(capture_run, fixture_dir):
    a = capture_run(fixture_dir / "gemm.c")
    b = capture_run(fixture_dir / "gemm.c")
    report = compare(a, b, target_seq=len(a.invocations) + 1)
    assert report.first_divergence is None
    assert report.identical_records == len(a.invocations)
