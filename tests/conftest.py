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
