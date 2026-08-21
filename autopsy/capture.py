from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .model import Invocation, Run

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "build" / "plugin" / "AutopsyPlugin.so"

# Mandatory: without this every loop reports as <unnamed loop> and the
# addressing scheme collapses (spec C3). It is free -- object is identical.
REQUIRED_FLAGS = ["-fno-discard-value-names"]


def capture(src, out_dir, opt_level: str = "-O3", extra_flags=None,
            env_extra=None) -> Run:
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    events = out_dir / "events.jsonl"
    cas = out_dir / "cas"

    if not PLUGIN.exists():
        raise FileNotFoundError(f"plugin not built at {PLUGIN}; run `make build`")

    cmd = ["clang", opt_level, *REQUIRED_FLAGS, f"-fpass-plugin={PLUGIN}",
           "-c", str(src), "-o", str(out_dir / (src.stem + ".o"))]
    if extra_flags:
        cmd.extend(extra_flags)

    env = dict(os.environ, AUTOPSY_OUT=str(events), AUTOPSY_CAS=str(cas))
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"capture failed:\n{result.stderr}")

    invocations = [
        Invocation.from_json(json.loads(line))
        for line in events.read_text().splitlines()
        if line.strip()
    ]
    return Run(invocations=invocations, cas_dir=cas)
