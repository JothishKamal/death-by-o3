import subprocess

from autopsy.measure.launch import LaunchConfig, build_command, normalised_env


def test_command_pins_and_disables_aslr():
    cmd = build_command(["/bin/true"], LaunchConfig(cpu=3))
    assert cmd[:2] == ["taskset", "-c"]
    assert cmd[2] == "3"
    assert "setarch" in cmd and "-R" in cmd


def test_env_block_is_exactly_the_requested_size():
    env = normalised_env(LaunchConfig(env_bytes=4096))
    total = sum(len(k) + len(v) + 2 for k, v in env.items())
    assert total == 4096, f"env block is {total} bytes, expected 4096"


def test_env_block_size_is_stable_regardless_of_ambient(monkeypatch):
    a = normalised_env(LaunchConfig(env_bytes=4096))
    monkeypatch.setenv("SOME_LONG_UNRELATED_VARIABLE", "x" * 3000)
    b = normalised_env(LaunchConfig(env_bytes=4096))
    size = lambda e: sum(len(k) + len(v) + 2 for k, v in e.items())
    assert size(a) == size(b) == 4096


def test_wrapper_actually_runs_a_program():
    cmd = build_command(["/bin/echo", "hello"], LaunchConfig(cpu=0))
    result = subprocess.run(cmd, capture_output=True, text=True,
                            env=normalised_env(LaunchConfig()))
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_pinning_to_an_even_cpu_is_the_default():
    """Siblings are (0,1) (2,3) ...; pin to one thread of a distinct core."""
    assert LaunchConfig().cpu % 2 == 0


def test_too_small_env_budget_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        normalised_env(LaunchConfig(env_bytes=8))
