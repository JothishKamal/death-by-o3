from autopsy.capture import capture
from autopsy.experiment.pairwise import LOOP_CLUSTER, pairwise
from autopsy.experiment.runner import address_of, run_experiment


def size_score(exp):
    base = exp.baseline_obj.stat().st_size
    return (base - exp.variant_obj.stat().st_size) / base if base else 0.0


def test_multiple_addresses_suppress_multiple_invocations(capture_events, fixture_dir):
    from tests.test_veto_basic import veto_arg
    base = capture_events(fixture_dir / "gemm.c")
    targets = [r for r in base
               if r["func"] == "kernel_gemm" and r["changed"] and not r["required"]][:2]
    arg = ";".join(veto_arg(t) for t in targets)
    after = capture_events(fixture_dir / "gemm.c", env={"AUTOPSY_VETO": arg})
    skipped = [r for r in after if r["status"] == "skipped"]
    assert len(skipped) == 1, (
        "only the first address can apply: after the first veto the pipeline "
        "diverges, so later guards legitimately fail")


def test_loop_cluster_is_the_documented_set():
    assert LOOP_CLUSTER == {
        "loop-vectorize", "slp-vectorizer", "loop-unroll", "loop-unroll-full",
        "licm", "simple-loop-unswitch", "indvars", "loop-idiom",
    }


def test_pairwise_only_pairs_within_the_cluster(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions() if d.func == "kernel_gemm"]
    results = pairwise(fixture_dir / "gemm.c", tmp_path / "pw", cands, size_score)
    for r in results:
        for d in r.decisions:
            assert d.pass_name in LOOP_CLUSTER


def test_pairwise_returns_empty_when_no_cluster_members(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions() if d.pass_name == "sroa"]
    assert pairwise(fixture_dir / "gemm.c", tmp_path / "pw", cands, size_score) == []
