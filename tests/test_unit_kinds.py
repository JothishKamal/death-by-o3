import re

KIND_RE = re.compile(r"\bkind=(\w+)\b")


def test_all_four_ir_unit_kinds_resolve(run_capture, fixture_dir):
    """gemm.c has a module, functions, a recursive SCC, and nested loops.
    All four must resolve, and nothing may be unresolved."""
    result = run_capture(fixture_dir / "gemm.c")
    assert result.returncode == 0, result.stderr
    kinds = KIND_RE.findall(result.stderr)
    assert set(kinds) >= {"module", "function", "scc", "loop"}, sorted(set(kinds))
    assert "unresolved" not in kinds


def test_loop_names_are_real_not_placeholder(run_capture, fixture_dir):
    """-fno-discard-value-names must be in effect: loops carry real names."""
    result = run_capture(fixture_dir / "gemm.c")
    assert "<unnamed loop>" not in result.stderr


def test_loops_collapse_without_value_names(run_capture, fixture_dir):
    """Regression guard for spec C3: prove the flag is load-bearing."""
    result = run_capture(fixture_dir / "gemm.c",
                         extra_flags=["-fdiscard-value-names"])
    assert "<unnamed loop>" in result.stderr
