from autopsy.experiment.bisect import (bisect_range_excluding,
                                       bisect_range_excluding_open, calibrate)


def test_calibration_lists_gated_passes(fixture_dir):
    entries = calibrate(fixture_dir / "gemm.c")
    assert len(entries) > 400, f"expected 500+ gated passes, got {len(entries)}"
    assert entries[0].index == 1
    assert [e.index for e in entries] == list(range(1, len(entries) + 1))


def test_calibration_includes_backend_passes(fixture_dir):
    """The middle-end plugin cannot see these, which is why we parse instead."""
    names = {e.pass_name for e in calibrate(fixture_dir / "gemm.c")}
    assert any("isel" in n for n in names), "no backend passes in the listing"


def test_middle_end_prefix_precedes_codegen(fixture_dir):
    entries = calibrate(fixture_dir / "gemm.c")
    first_isel = next(e.index for e in entries if "isel" in e.pass_name)
    assert first_isel > 300, "codegen should follow the whole middle end"


def test_range_excluding_one_index():
    assert bisect_range_excluding(373, 441) == "1-372,374-441"
    assert bisect_range_excluding(1, 5) == "2-5"
    assert bisect_range_excluding(5, 5) == "1-4"


def test_range_actually_skips_that_pass(fixture_dir, tmp_path):
    """End-to-end: the emitted string must suppress exactly one pass.

    The tail uses an open-ended upper bound: with an active range LLVM gates a
    handful of trailing backend passes that the -1 listing never showed, and a
    tail capped at the calibrated total would suppress those too."""
    import subprocess
    entries = calibrate(fixture_dir / "gemm.c")
    target = next(e for e in entries if e.pass_name == "loop-unroll")
    rng = bisect_range_excluding_open(target.index)
    result = subprocess.run(
        ["clang", "-O3", "-fno-discard-value-names",
         "-mllvm", f"--opt-bisect={rng}", "-mllvm", "--opt-bisect-verbose",
         "-c", str(fixture_dir / "gemm.c"), "-o", str(tmp_path / "o.o")],
        capture_output=True, text=True)
    assert result.returncode == 0
    not_run = [l for l in result.stderr.splitlines() if "NOT running pass" in l]
    assert len(not_run) == 1, f"expected 1 suppressed pass, got {len(not_run)}"
    assert f"({target.index}) {target.pass_name}" in not_run[0]
