from autopsy.capture import capture
from autopsy.rank.ranker import WEIGHTS, rank, score


def test_weights_are_public_and_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "weights must be a partition"
    assert set(WEIGHTS) == {"ir_delta", "hot_function", "size_delta",
                            "pass_prior", "drift_depth"}


def test_score_exposes_every_component(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    d = next(iter(run.decisions()))
    s = score(d, run)
    assert set(s.components) == set(WEIGHTS)
    assert 0.0 <= s.total <= 1.0


def test_hot_function_decisions_outrank_others(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    in_hot = [d for d in run.decisions() if d.func == "kernel_gemm"]
    out_hot = [d for d in run.decisions() if d.func == "recurse_b"]
    assert in_hot and out_hot
    best_in = max(score(d, run, hot_function="kernel_gemm").total for d in in_hot)
    best_out = max(score(d, run, hot_function="kernel_gemm").total for d in out_hot)
    assert best_in > best_out


def test_vectorizers_and_unrollers_carry_a_prior(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    unroll = [d for d in run.decisions() if d.pass_name == "loop-unroll"]
    other = [d for d in run.decisions() if d.pass_name == "sroa"]
    assert unroll and other
    assert (score(unroll[0], run).components["pass_prior"]
            > score(other[0], run).components["pass_prior"])


def test_scaffolding_is_never_ranked(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    report = rank(run)
    assert all(s.decision.role == "transform" for s in report.suspects)


def test_required_passes_are_never_ranked(fixture_dir, tmp_path):
    """A Required decision has no counterfactual, so it cannot be a suspect."""
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    assert all(not s.decision.required for s in rank(run).suspects)


def test_no_culprit_when_top_candidate_is_a_no_op(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    stripped = type(run)(invocations=[i for i in run.invocations if not i.changed],
                         cas_dir=run.cas_dir)
    assert rank(stripped).verdict == "NO_CULPRIT_FOUND"


def test_limit_is_respected(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "c")
    assert len(rank(run, limit=3).suspects) <= 3
