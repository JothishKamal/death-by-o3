from autopsy.capture import capture
from autopsy.experiment.sweep import sweep


def object_size_score(exp):
    """Stand-in scorer: how much smaller is the variant's object file?"""
    base = exp.baseline_obj.stat().st_size
    var = exp.variant_obj.stat().st_size
    return (base - var) / base if base else 0.0


def test_sweep_runs_an_experiment_per_candidate(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions() if d.func == "kernel_gemm"][:4]
    results = sweep(fixture_dir / "gemm.c", tmp_path / "sweep", cands,
                    object_size_score)
    assert len(results) == len(cands)


def test_sweep_is_sorted_by_score_descending(fixture_dir, tmp_path):
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions() if d.func == "kernel_gemm"][:4]
    results = sweep(fixture_dir / "gemm.c", tmp_path / "sweep", cands,
                    object_size_score)
    scores = [r.score for r in results if r.usable]
    assert scores == sorted(scores, reverse=True)


def test_unusable_experiments_are_marked_not_dropped(fixture_dir, tmp_path):
    """A refused guard is a reportable outcome, not a silent omission."""
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions()][:2]
    results = sweep(fixture_dir / "gemm.c", tmp_path / "sweep", cands,
                    object_size_score)
    assert len(results) == 2
    assert all(hasattr(r, "usable") for r in results)


def test_vetoing_loop_unroll_shrinks_the_object(fixture_dir, tmp_path):
    """Ground truth: on this fixture, removing loop-unroll shrinks .text a lot."""
    run = capture(fixture_dir / "gemm.c", tmp_path / "base")
    cands = [d for d in run.decisions()
             if d.pass_name == "loop-unroll" and d.func == "kernel_gemm"]
    results = sweep(fixture_dir / "gemm.c", tmp_path / "sweep", cands,
                    object_size_score)
    assert results[0].usable
    assert results[0].score > 0.10, "expected a large size reduction"
