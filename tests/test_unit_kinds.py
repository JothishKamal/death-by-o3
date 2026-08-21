import json


def test_all_four_ir_unit_kinds_resolve(capture_events, fixture_dir):
    """gemm.c has a module, functions, a recursive SCC, and nested loops.
    All four must resolve, and nothing may be unresolved."""
    recs = capture_events(fixture_dir / "gemm.c")
    kinds = {r["kind"] for r in recs}
    assert kinds >= {"module", "function", "scc", "loop"}, sorted(kinds)
    assert "unresolved" not in kinds


def test_loop_names_are_real_not_placeholder(capture_events, fixture_dir):
    """-fno-discard-value-names must be in effect: loops carry real names."""
    recs = capture_events(fixture_dir / "gemm.c")
    assert "<unnamed loop>" not in {r["unit_name"] for r in recs}


def test_loops_collapse_without_value_names(capture_events, run_capture,
                                            fixture_dir, tmp_path):
    """Regression guard for spec C3: prove the flag is load-bearing."""
    out = tmp_path / "discard.jsonl"
    result = run_capture(fixture_dir / "gemm.c",
                         extra_flags=["-fdiscard-value-names"],
                         env={"AUTOPSY_OUT": str(out)})
    assert result.returncode == 0
    names = {r["unit_name"] for r in
             (json.loads(l) for l in out.read_text().splitlines() if l.strip())}
    assert "<unnamed loop>" in names
