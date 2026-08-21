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

    vet = sub.add_parser("veto", help="build a counterfactual with one decision removed")
    vet.add_argument("source", type=Path)
    vet.add_argument("--pass-name", required=True)
    vet.add_argument("--function", required=True)
    vet.add_argument("--occurrence", type=int, default=1)
    vet.add_argument("-o", "--out", type=Path, default=Path("autopsy-veto"))

    args = parser.parse_args(argv)

    if args.command == "capture":
        run = capture(args.source, args.out, opt_level=args.opt_level)
        decisions = run.decisions()
        print(f"{len(run.invocations)} invocations, {len(decisions)} decisions")
        print(f"events: {args.out / 'events.jsonl'}")
        print(f"cas:    {args.out / 'cas'}")
        return 0

    if args.command == "veto":
        from .experiment.runner import address_of, run_experiment
        probe = capture(args.source, args.out / "probe")
        candidates = [d for d in probe.decisions()
                      if d.pass_name == args.pass_name and d.func == args.function
                      and d.occurrence == args.occurrence]
        if not candidates:
            print(f"no decision matching {args.pass_name} on {args.function} "
                  f"occurrence {args.occurrence}", file=sys.stderr)
            return 2
        exp = run_experiment(args.source, address_of(candidates[0]), args.out)
        print(f"tier            {exp.tier}")
        print(f"guard matched   {exp.guard_matched}")
        print(f"prefix ok       {exp.prefix.ok} "
              f"({exp.prefix.identical_records} identical records)")
        print(f"reproduce       {exp.reproduce_cmd}")
        return 0 if exp.usable else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
