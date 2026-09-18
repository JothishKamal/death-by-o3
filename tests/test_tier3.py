import subprocess

from autopsy.experiment.tier3 import pipeline_string, run_tier3


def make_bc(src, out, tmp_path):
    subprocess.run(["clang", "-O3", "-Xclang", "-disable-llvm-passes",
                    "-emit-llvm", "-c", str(src), "-o", str(out)], check=True)
    return out


def test_pipeline_string_is_extracted(fixture_dir, tmp_path):
    bc = make_bc(fixture_dir / "gemm.c", tmp_path / "in.bc", tmp_path)
    s = pipeline_string(bc)
    assert len(s) > 1000
    assert "BitcodeWriterPass" not in s, "trailing writer pass must be stripped"
    assert "simplifycfg" in s


def test_pipeline_string_round_trips_byte_identical(fixture_dir, tmp_path):
    bc = make_bc(fixture_dir / "gemm.c", tmp_path / "in.bc", tmp_path)
    ref, replay = tmp_path / "ref.bc", tmp_path / "replay.bc"
    subprocess.run(["opt", "-passes=default<O3>", str(bc), "-o", str(ref)], check=True)
    subprocess.run(["opt", f"-passes={pipeline_string(bc)}", str(bc), "-o", str(replay)],
                   check=True)
    assert ref.read_bytes() == replay.read_bytes()


def test_tier3_drops_a_named_pass(fixture_dir, tmp_path):
    bc = make_bc(fixture_dir / "gemm.c", tmp_path / "in.bc", tmp_path)
    out = tmp_path / "t3.bc"
    assert run_tier3(bc, "loop-unroll", out)
    assert out.exists()
    ref = tmp_path / "ref.bc"
    subprocess.run(["opt", "-passes=default<O3>", str(bc), "-o", str(ref)], check=True)
    assert out.read_bytes() != ref.read_bytes(), "dropping the pass had no effect"


def test_tier3_is_not_trusted_alone(fixture_dir, tmp_path):
    """opt-replay is a different pipeline from clang's; record the discrepancy."""
    bc = make_bc(fixture_dir / "gemm.c", tmp_path / "in.bc", tmp_path)
    s = pipeline_string(bc)
    assert s.count("simplifycfg") >= 4, "pipeline string looks truncated"
