#!/usr/bin/env python3
"""CLI tool to freeze and verify the canonical base manuscript before journal adaptation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore.basefreeze import BASE_FREEZE_REL, verify_base_freeze, write_base_freeze  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze or verify the canonical base manuscript before journal adaptation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--project", type=Path, default=Path("project"))
        cmd.add_argument("--freeze", type=Path)
    args = parser.parse_args()

    project = args.project.resolve()
    freeze_path = args.freeze.resolve() if args.freeze else project / Path(BASE_FREEZE_REL)

    try:
        if args.command == "freeze":
            out = write_base_freeze(project, freeze_path)
            ok, problems, count = verify_base_freeze(project, out)
            if not ok:
                raise ValueError("; ".join(problems))
            print(f"Successfully frozen {count} base research & manuscript files -> {out}")
            return 0
        
        ok, problems, count = verify_base_freeze(project, freeze_path)
        if not ok:
            print("CRITICAL VIOLATION: Canonical base manuscript modified after freeze:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 2
        print(f"Verified {count} frozen base manuscript files: strictly untouched and unpolluted")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Base freeze error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
