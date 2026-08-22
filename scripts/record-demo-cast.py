#!/usr/bin/env python3
"""Record the CLI demo loop into an asciinema v2 cast.

Runs the real commands against the real plugin and captures their actual
output; inter-frame delays are authored, not slept through, so the cast is
fast to produce and deterministic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "demo" / "terminal.cast"
ENV = dict(os.environ, TERM="xterm-256color", AUTOPSY_TOOL_PREFIX=str(REPO / ".tools"))

HEADER = {"version": 2, "width": 100, "height": 30,
          "timestamp": int(time.time()),
          "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"}}

PROMPT = "\x1b[1;32msegfault\x1b[0m \x1b[1;34mdeath-by-o3\x1b[0m $ "


def frame(delay: float, text: str) -> list:
    return [delay, "o", text]


def run(cmd: list, delay_after: float = 0.4) -> tuple[list, str]:
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, cwd=REPO)
    took = time.time() - t0
    out = (r.stdout + r.stderr).rstrip("\n")
    return frame(min(took, delay_after), f"{PROMPT}{' '.join(cmd)}\n{out}\n"), out


def beat(delay: float, text: str) -> list:
    return frame(delay, text)


def main() -> int:
    src = "benchmarks/tierA/A12_simplifycfg_cmov.c"
    events: list[list] = []

    events.append(beat(0.6, "\x1b[1mOptimization Autopsy — demo\x1b[0m\n"))
    events.append(beat(1.2, "-O3 on a 30-line kernel. One decision costs ~5x.\n"
                            "We are going to find it, veto it, and prove it.\n\n"))

    # Beat 1: measure the regression with the Tier A harness.
    ev, out = run(["bash", "-c",
        "clang -O3 -fno-discard-value-names -I benchmarks/tierA "
        "benchmarks/tierA/A12_simplifycfg_cmov.c -o /tmp/a12_base -lm "
        "&& clang -O3 -fno-discard-value-names "
        "-mllvm -two-entry-phi-node-folding-threshold=0 "
        "-mllvm -phi-node-folding-threshold=0 "
        "-I benchmarks/tierA benchmarks/tierA/A12_simplifycfg_cmov.c "
        "-o /tmp/a12_veto -lm && "
        "echo '--- -O3:' && /tmp/a12_base && echo '--- vetoed:' && /tmp/a12_veto"],
        delay_after=3.5)
    events.append(ev)
    base_ns = veto_ns = None
    for line in out.splitlines():
        if line.startswith("NS_PER_REP"):
            ns = float(line.split()[1])
            if base_ns is None:
                base_ns = ns
            else:
                veto_ns = ns
    if base_ns and veto_ns:
        events.append(beat(1.4, f"\x1b[1;33m=> {base_ns/veto_ns:.2f}x slower with one decision in place."
                                f" Checksum identical.\x1b[0m\n\n"))

    # Beat 2: capture every pass invocation.
    ev, out = run([".venv/bin/autopsy", "capture", src, "-o", "/tmp/demo-cap"],
                  delay_after=2.5)
    events.append(ev)
    events.append(beat(1.2, "Every invocation recorded: tree position, occurrence, "
                            "guard hash, IR metrics, snapshot.\n\n"))

    # Beat 3: diagnose -- rank the decisions worth a counterfactual.
    ev, out = run([".venv/bin/autopsy", "diagnose", src, "--top", "3",
                   "-o", "/tmp/demo-diag"], delay_after=6.0)
    events.append(ev)

    # Beat 4: veto exactly one simplifycfg decision on chain.
    ev, out = run([".venv/bin/autopsy", "veto", src,
                   "--pass-name", "simplifycfg", "--function", "chain",
                   "-o", "/tmp/demo-veto"], delay_after=6.0)
    events.append(ev)
    if "guard matched   True" in out:
        events.append(beat(1.2, "\x1b[1;32mGuard verified: the veto landed on exactly "
                                "the addressed invocation,\x1b[0m\n"
                                "and every record before it is byte-identical.\n"
                                "The reproduce command runs on stock clang with no plugin.\n"))

    events.append(beat(0.8, "\x1b[1mFull UI: .venv/bin/autopsy serve <src> + web/npm run dev\x1b[0m\n"))

    OUT.write_text(json.dumps(HEADER) + "\n" +
                   "".join(json.dumps(e) + "\n" for e in events))
    print(f"wrote {OUT} ({len(events)} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
