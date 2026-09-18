import subprocess

from autopsy.experiment.verify import verify_equivalence, verify_module


def build(src, out, flags=()):
    subprocess.run(["clang", "-O3", "-fno-discard-value-names", *flags,
                    str(src), "-o", str(out)], check=True)
    return out


def test_identical_builds_are_equivalent(fixture_dir, tmp_path):
    a = build(fixture_dir / "runnable.c", tmp_path / "a")
    b = build(fixture_dir / "runnable.c", tmp_path / "b")
    eq = verify_equivalence(a, b)
    assert eq.stdout_identical and eq.exit_code_identical
    assert not eq.diverged


def test_semantics_preserving_flag_change_is_equivalent(fixture_dir, tmp_path):
    """Disabling a pass must not change the program's output."""
    a = build(fixture_dir / "runnable.c", tmp_path / "a")
    b = build(fixture_dir / "runnable.c", tmp_path / "b", flags=["-fno-vectorize"])
    eq = verify_equivalence(a, b)
    assert not eq.diverged, eq.detail


def test_genuinely_different_programs_diverge(fixture_dir, tmp_path):
    a = build(fixture_dir / "runnable.c", tmp_path / "a")
    altered = tmp_path / "altered.c"
    altered.write_text(
        (fixture_dir / "runnable.c").read_text().replace("s += C[i][i];", "s += C[i][i] + 1;"))
    b = build(altered, tmp_path / "b")
    eq = verify_equivalence(a, b)
    assert eq.diverged
    assert not eq.stdout_identical


def test_module_verifier_accepts_valid_ir(fixture_dir, tmp_path):
    ir = tmp_path / "m.ll"
    subprocess.run(["clang", "-O3", "-S", "-emit-llvm",
                    str(fixture_dir / "runnable.c"), "-o", str(ir)], check=True)
    assert verify_module(ir)


def test_module_verifier_rejects_broken_ir(tmp_path):
    bad = tmp_path / "bad.ll"
    bad.write_text("define i32 @f() {\nentry:\n  ret i64 0\n}\n")
    assert not verify_module(bad)
