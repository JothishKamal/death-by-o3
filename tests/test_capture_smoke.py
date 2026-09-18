def test_plugin_loads_and_announces(run_capture, fixture_dir):
    result = run_capture(fixture_dir / "gemm.c")
    assert result.returncode == 0, result.stderr
    assert "autopsy-plugin" in result.stderr
