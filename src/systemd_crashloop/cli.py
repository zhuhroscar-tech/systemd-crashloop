"""systemd-crashloop CLI."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import diagnose_unit, list_failed_units, CAUSE_CLEAN_NOT_CRASHING, CAUSE_UNKNOWN


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="systemd-crashloop",
        description=(
            "Classify why a systemd service is crash-looping (OOM killed, "
            "start-limit-hit, missing dependency, timeout, config error, or "
            "plain nonzero exit) instead of manually reading journalctl. "
            "Strictly read-only: never restarts, resets, or reconfigures anything."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "units", nargs="*",
        help="Unit name(s) to diagnose (e.g. myapp.service). If omitted, all "
             "currently-failed units are diagnosed.",
    )
    p.add_argument(
        "--journal-lines", type=int, default=200,
        help="How many recent journal lines to inspect per unit (default: 200).",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return p


def _print_text(reports) -> None:
    for r in reports:
        print(f"\n{r.unit}: {r.cause}")
        print(f"  {r.explanation}")
        if r.state:
            print(
                f"  state: active={r.state.active_state} sub={r.state.sub_state} "
                f"result={r.state.result or '-'} n_restarts={r.state.n_restarts}"
            )
        if r.evidence:
            print("  recent journal lines:")
            for line in r.evidence:
                print(f"    {line}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    units = args.units or list_failed_units()
    reports = [diagnose_unit(u, journal_lines=args.journal_lines) for u in units]

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        if not reports:
            print("No failed units found and none were specified.")
        _print_text(reports)

    if not reports:
        return 0
    if any(r.cause == CAUSE_UNKNOWN for r in reports):
        return 1
    if all(r.cause == CAUSE_CLEAN_NOT_CRASHING for r in reports):
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
