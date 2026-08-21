from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .capture import capture


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autopsy")
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="record every pass invocation")
    cap.add_argument("source", type=Path)
    cap.add_argument("-o", "--out", type=Path, default=Path("autopsy-out"))
    cap.add_argument("-O", "--opt-level", default="-O3")

    args = parser.parse_args(argv)

    if args.command == "capture":
        run = capture(args.source, args.out, opt_level=args.opt_level)
        decisions = run.decisions()
        print(f"{len(run.invocations)} invocations, {len(decisions)} decisions")
        print(f"events: {args.out / 'events.jsonl'}")
        print(f"cas:    {args.out / 'cas'}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
