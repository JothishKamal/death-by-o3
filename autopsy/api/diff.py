from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

# Unnamed SSA values and metadata ids renumber constantly. Canonicalise them or
# every renumbering pass produces a 100%-changed diff.
_UNNAMED_VALUE = re.compile(r"%(\d+)\b")
_METADATA_ID = re.compile(r"!(\d+)\b")


def normalise_ssa(text: str) -> str:
    """Canonicalise %<n> and !<n> so renumbering does not read as a change.

    Named values (%acc.0, %for.body) are left alone -- they carry meaning.
    """
    out = _UNNAMED_VALUE.sub("%N", text)
    return _METADATA_ID.sub("!N", out)


def char_changes(before: str, after: str) -> list[list[int]]:
    """Character-offset changes, in @codemirror/merge's Change[] shape.

    Uses `git diff --diff-algorithm=histogram` (17 ms at 11k lines). Python's
    difflib is NOT used: its default autojunk=True discards lines appearing in
    more than 1% of the file -- in LLVM IR that is `br label %...`, `}` and
    blanks -- producing a silently wrong diff.
    """
    if before == after:
        return []

    tmp = Path(tempfile.mkdtemp())
    a_path, b_path = tmp / "a.ll", tmp / "b.ll"
    a_path.write_text(before)
    b_path.write_text(after)

    result = subprocess.run(
        ["git", "diff", "--no-index", "--diff-algorithm=histogram",
         "-U0", "--no-color", str(a_path), str(b_path)],
        capture_output=True, text=True)

    a_starts, b_starts = _line_starts(before), _line_starts(after)
    changes = []
    hunk = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for line in result.stdout.splitlines():
        m = hunk.match(line)
        if not m:
            continue
        a_line = int(m.group(1))
        a_len = int(m.group(2) or 1)
        b_line = int(m.group(3))
        b_len = int(m.group(4) or 1)
        from_a = a_starts[min(max(a_line - 1, 0), len(a_starts) - 1)]
        to_a = a_starts[min(a_line - 1 + a_len, len(a_starts) - 1)]
        from_b = b_starts[min(max(b_line - 1, 0), len(b_starts) - 1)]
        to_b = b_starts[min(b_line - 1 + b_len, len(b_starts) - 1)]
        changes.append([from_a, to_a, from_b, to_b])
    return changes


def _line_starts(text: str) -> list[int]:
    starts, pos = [0], 0
    for line in text.splitlines(keepends=True):
        pos += len(line)
        starts.append(pos)
    return starts
