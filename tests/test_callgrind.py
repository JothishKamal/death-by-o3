import subprocess

import pytest

from autopsy.measure.callgrind import run_callgrind
from autopsy.measure.toolchain import find_toolchain

pytestmark = pytest.mark.skipif(not find_toolchain().has_valgrind,
                                reason="valgrind not staged")


@pytest.fixture(scope="module")
def exe(tmp_path_factory, request):
    src = request.config.rootpath / "tests" / "fixtures" / "runnable.c"
    out = tmp_path_factory.mktemp("cg") / "bench"
    subprocess.run(["clang", "-O2", "-g", str(src), "-o", str(out)], check=True)
    return out


def test_callgrind_reports_a_positive_instruction_count(exe):
    r = run_callgrind(exe)
    assert r.total_ir > 100_000


def test_callgrind_is_bit_for_bit_deterministic(exe):
    """The whole metric hierarchy rests on this: zero variance means n=1."""
    counts = [run_callgrind(exe).total_ir for _ in range(3)]
    assert len(set(counts)) == 1, f"expected identical counts, got {counts}"


def test_per_function_costs_are_extracted(exe):
    r = run_callgrind(exe)
    assert r.per_function
    assert any(v > 1000 for v in r.per_function.values())


def test_per_function_costs_are_stable_across_env_sizes(exe):
    """Per-function costs are immune to env size; whole-program totals are not."""
    from autopsy.measure.launch import LaunchConfig
    a = run_callgrind(exe, cfg=LaunchConfig(env_bytes=2048))
    b = run_callgrind(exe, cfg=LaunchConfig(env_bytes=8192))
    common = set(a.per_function) & set(b.per_function)
    hot = [f for f in common if a.per_function[f] > 10_000]
    assert hot
    for f in hot:
        assert a.per_function[f] == b.per_function[f], f"{f} moved with env size"
