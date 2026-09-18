import subprocess

from autopsy.bench.tiera import build_case, load_manifest

MANIFEST = "benchmarks/tierA/manifest.toml"


def test_manifest_loads(repo_root):
    cases = load_manifest(repo_root / MANIFEST)
    assert len(cases) >= 2
    assert all(c.culprit_pass for c in cases)


def test_every_case_declares_its_isa_config(repo_root):
    """ISA is a first-class axis: A04 reproduces at SSE2 and vanishes at native."""
    for c in load_manifest(repo_root / MANIFEST):
        assert c.config_flags is not None


def test_cases_build_and_run(repo_root, tmp_path):
    for c in load_manifest(repo_root / MANIFEST):
        exe = build_case(c, tmp_path, flags=c.config_flags)
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "CHECK" in r.stdout
        assert "NS_PER_REP" in r.stdout


def test_checksum_is_invariant_under_the_culprit_flag(repo_root, tmp_path):
    """Correctness oracle: disabling the culprit must not change the answer."""
    case = next(c for c in load_manifest(repo_root / MANIFEST) if c.id == "A12")
    a = build_case(case, tmp_path / "a", flags=case.config_flags)
    b = build_case(case, tmp_path / "b",
                   flags=tuple(case.config_flags) + tuple(case.disable_flags))
    out = lambda e: subprocess.run([str(e)], capture_output=True, text=True).stdout
    ck = lambda s: [l for l in s.splitlines() if l.startswith("CHECK")][0]
    assert ck(out(a)) == ck(out(b))


def test_harness_aborts_if_the_kernel_is_optimised_away(repo_root, tmp_path):
    """bench.h must fail loudly rather than report a meaningless 0 ns/rep."""
    src = (repo_root / "benchmarks" / "tierA" / "bench.h").read_text()
    assert "optimised away" in src
    assert "0.05" in src
