from __future__ import annotations

import re
import subprocess
from pathlib import Path


def pipeline_string(bc_path) -> str:
    """Dump the -O3 pipeline as a -passes= string.

    `opt -o` appends BitcodeWriterPass, which is not a real pass. On 22.1.8
    opt's own re-parse of its dump fails on that name and exits 1 -- after
    printing the full pipeline to stdout -- so we do not check the exit code;
    we take stdout, strip the writer pass, and let replay be the validation.
    """
    result = subprocess.run(
        ["opt", "-passes=default<O3>", "--print-pipeline-passes",
         str(Path(bc_path)), "-o", "/dev/null"],
        capture_output=True, text=True)
    s = result.stdout.strip()
    if not s:
        raise RuntimeError(f"empty pipeline dump: {result.stderr.strip()}")
    return re.sub(r",BitcodeWriterPass$", "", s)


def run_tier3(bc_path, pass_to_drop: str, out_bc) -> bool:
    """Remove every instance of a named pass from the pipeline string and replay.

    Narrowest applicability of the three tiers: it drops ALL occurrences, not
    one, so it answers a different question from Tier 1 and is only used as a
    fast pre-screen.
    """
    pipeline = pipeline_string(bc_path)
    # Also consume any <...> parameter block; one nesting level suffices for
    # real pipelines (e.g. "loop-unroll<O3>", "licm<allowspeculation>").
    param = r"(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?"
    edited = re.sub(
        rf"(?<![\w-]){re.escape(pass_to_drop)}(?![\w-]){param},?", "", pipeline)
    edited = re.sub(r",,+", ",", edited).strip(",")
    edited = re.sub(r"\(,", "(", edited)
    edited = re.sub(r",\)", ")", edited)
    if edited == pipeline:
        return False
    result = subprocess.run(
        ["opt", f"-passes={edited}", str(Path(bc_path)), "-o", str(Path(out_bc))],
        capture_output=True, text=True)
    return result.returncode == 0


def validate_against_tier1(tier3_obj, tier1_obj) -> bool:
    """Tier 3 is only trusted where it agrees with Tier 1 (spec 5.5)."""
    return Path(tier3_obj).read_bytes() == Path(tier1_obj).read_bytes()
