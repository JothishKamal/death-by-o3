import shutil

import pytest

from autopsy.measure.toolchain import Toolchain, find_toolchain


def test_finds_tools_on_path_when_no_prefix(monkeypatch):
    monkeypatch.delenv("AUTOPSY_TOOL_PREFIX", raising=False)
    tc = find_toolchain(prefix=None)
    assert isinstance(tc, Toolchain)
    assert tc.has_valgrind == (shutil.which("valgrind") is not None)


def test_prefix_takes_priority_over_path(tmp_path):
    fake = tmp_path / "usr" / "bin"
    fake.mkdir(parents=True)
    (fake / "valgrind").write_text("#!/bin/sh\nexit 0\n")
    (fake / "valgrind").chmod(0o755)
    tc = find_toolchain(prefix=tmp_path)
    assert tc.has_valgrind
    assert tc.valgrind_bin == fake / "valgrind"


def test_callgrind_env_sets_valgrind_lib(tmp_path):
    fake = tmp_path / "usr" / "bin"
    fake.mkdir(parents=True)
    (fake / "valgrind").write_text("#!/bin/sh\nexit 0\n")
    (fake / "valgrind").chmod(0o755)
    env = find_toolchain(prefix=tmp_path).callgrind_env()
    assert env["VALGRIND_LIB"].endswith("lib/valgrind")
    assert str(tmp_path) in env["LD_LIBRARY_PATH"]


def test_missing_tools_are_reported_not_raised(tmp_path):
    tc = find_toolchain(prefix=tmp_path / "nonexistent")
    assert tc.valgrind_bin is None or tc.has_valgrind
