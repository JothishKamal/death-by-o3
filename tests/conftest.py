import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def autopsy_plugin() -> Path:
    so = REPO / "build" / "plugin" / "AutopsyPlugin.so"
    if not so.exists():
        pytest.fail(f"plugin not built at {so}; run `make build`")
    return so


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return REPO / "tests" / "fixtures"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture
def run_capture(autopsy_plugin, tmp_path):
    """Compile `src` with the plugin loaded. Returns CompletedProcess."""

    def _run(src: Path, extra_flags=None, env=None):
        cmd = [
            "clang", "-O3", "-fno-discard-value-names",
            f"-fpass-plugin={autopsy_plugin}",
            "-c", str(src), "-o", str(tmp_path / "out.o"),
        ]
        if extra_flags:
            cmd.extend(extra_flags)
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run(cmd, capture_output=True, text=True, env=full_env)

    return _run


@pytest.fixture
def capture_events(run_capture, tmp_path):
    """Run a capture and return the parsed JSONL records."""

    def _run(src, extra_flags=None, env=None):
        out = tmp_path / "events.jsonl"
        e = {"AUTOPSY_OUT": str(out)}
        if env:
            e.update(env)
        result = run_capture(src, extra_flags=extra_flags, env=e)
        assert result.returncode == 0, result.stderr
        return [json.loads(l) for l in out.read_text().splitlines() if l.strip()]

    return _run


@pytest.fixture
def capture_run(tmp_path):
    """Capture into a fresh directory and return a Run."""
    from autopsy.capture import capture

    counter = {"n": 0}

    def _run(src, env=None):
        counter["n"] += 1
        out = tmp_path / f"run{counter['n']}"
        return capture(src, out, env_extra=env)

    return _run
