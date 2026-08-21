import pytest

from autopsy.capture import capture
from autopsy.experiment.runner import address_of, run_experiment


@pytest.fixture(scope="module")
def baseline(tmp_path_factory, request):
    fixtures = request.config.rootpath / "tests" / "fixtures"
    return capture(fixtures / "gemm.c", tmp_path_factory.mktemp("base")), fixtures


def test_experiment_applies_the_veto(baseline, tmp_path):
    run, fixtures = baseline
    target = next(d for d in run.decisions()
                  if d.pass_name == "loop-unroll" and d.func == "kernel_gemm")
    exp = run_experiment(fixtures / "gemm.c", address_of(target), tmp_path)
    assert exp.guard_matched
    assert exp.tier == 1


def test_experiment_verifies_the_prefix(baseline, tmp_path):
    run, fixtures = baseline
    target = next(d for d in run.decisions()
                  if d.pass_name == "loop-unroll" and d.func == "kernel_gemm")
    exp = run_experiment(fixtures / "gemm.c", address_of(target), tmp_path)
    assert exp.prefix.ok
    assert exp.prefix.first_divergence == target.seq


def test_experiment_refuses_a_stale_address(baseline, tmp_path):
    run, fixtures = baseline
    target = next(iter(run.decisions()))
    stale = address_of(target).rsplit("|", 1)[0] + "|0xdeadbeefdeadbeef"
    exp = run_experiment(fixtures / "gemm.c", stale, tmp_path)
    assert not exp.guard_matched
    assert exp.prefix.first_divergence is None


def test_reproduce_command_is_emitted(baseline, tmp_path):
    run, fixtures = baseline
    target = next(iter(run.decisions()))
    exp = run_experiment(fixtures / "gemm.c", address_of(target), tmp_path)
    assert "clang" in exp.reproduce_cmd
    assert "-fno-discard-value-names" in exp.reproduce_cmd
