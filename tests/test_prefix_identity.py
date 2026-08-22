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


def test_ancestor_records_do_not_count_as_divergence(capture_run, fixture_dir):
    """A module-level ancestor of the target pops AFTER the target runs, so its
    after-hash and blobs legitimately differ once the veto fires. Its input --
    identity plus guard -- must still match exactly (measured on the Tier A
    A12 case: vetoing loop-unroll on `chain` used to flag a module PassManager
    ~90 records earlier as a divergence)."""
    from autopsy.experiment.runner import address_of

    src = fixture_dir.parent.parent / "benchmarks" / "tierA" / "A12_simplifycfg_cmov.c"
    if not src.exists():
        pytest.skip("Tier A corpus not present")
    base = capture_run(src)
    target = next(d for d in base.decisions()
                  if d.pass_name == "loop-unroll" and d.func == "chain")
    variant = capture_run(src, env={"AUTOPSY_VETO": address_of(target)})
    report = compare(base, variant, target.seq)
    assert report.ok
    assert report.first_divergence == target.seq
    assert report.identical_records == target.seq - 1
