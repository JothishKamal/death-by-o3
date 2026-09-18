import hashlib
import subprocess


def test_metrics_present_on_changed_invocations(capture_events, fixture_dir):
    recs = capture_events(fixture_dir / "gemm.c")
    changed = [r for r in recs if r["changed"] and r["kind"] == "function"]
    assert changed
    for r in changed:
        for side in ("metrics_before", "metrics_after"):
            m = r[side]
            assert m["instructions"] > 0
            assert m["blocks"] > 0
            assert set(m["by_class"]) == {
                "mem", "arith", "float", "vector", "control",
                "call", "cast", "phi", "other"}


def test_loop_structure_is_measured(capture_events, fixture_dir):
    """kernel_gemm has a 3-deep loop nest."""
    recs = capture_events(fixture_dir / "gemm.c")
    gemm = [r for r in recs
            if r["func"] == "kernel_gemm" and r["kind"] == "function" and r["changed"]]
    assert gemm
    assert max(r["metrics_before"]["max_loop_depth"] for r in gemm) >= 3
    assert max(r["metrics_before"]["loops"] for r in gemm) >= 3


def test_opcode_classes_sum_to_instruction_count(capture_events, fixture_dir):
    for r in capture_events(fixture_dir / "gemm.c"):
        for side in ("metrics_before", "metrics_after"):
            m = r.get(side)
            if m and m["instructions"]:
                assert sum(m["by_class"].values()) == m["instructions"]


def test_plugin_does_not_perturb_codegen(autopsy_plugin, fixture_dir, tmp_path):
    """THE load-bearing test: measuring must not change what is measured."""
    src = fixture_dir / "gemm.c"
    base = tmp_path / "base.o"
    inst = tmp_path / "inst.o"
    common = ["clang", "-O3", "-fno-discard-value-names", "-c", str(src), "-o"]
    subprocess.run(common + [str(base)], check=True)
    env = dict(PATH="/usr/bin:/bin", AUTOPSY_OUT=str(tmp_path / "e.jsonl"))
    subprocess.run(
        ["clang", "-O3", "-fno-discard-value-names",
         f"-fpass-plugin={autopsy_plugin}", "-c", str(src), "-o", str(inst)],
        check=True, env=env)
    assert hashlib.sha256(base.read_bytes()).hexdigest() == \
           hashlib.sha256(inst.read_bytes()).hexdigest(), \
           "plugin perturbed codegen -- it is touching the AnalysisManager"
