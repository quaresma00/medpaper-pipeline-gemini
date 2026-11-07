#!/usr/bin/env python3
"""CLI for single-source author-block rendering and placement verification (v1.28+)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from wfcore import authorblock  # noqa: E402


def project_root() -> Path:
    raw = os.environ.get("MEDPAPER_PROJECT")
    return Path(raw).resolve() if raw else ROOT / "project"


def cmd_show(args: argparse.Namespace) -> int:
    project = args.project.resolve() if args.project else project_root()
    ms_has_authors, needs_sep, policy_problems = authorblock.title_page_policy(project)
    print(f"blinded_main_manuscript: {authorblock.is_blinded(project)}")
    print(f"manuscript_page1_authors: {ms_has_authors}")
    print(f"separate_title_page_required: {needs_sep}")
    if policy_problems:
        for problem in policy_problems:
            print(f"policy error: {problem}", file=sys.stderr)
        return 2
    author_path = project / authorblock.AUTHOR_REL
    if not author_path.is_file():
        print(f"{authorblock.AUTHOR_REL}: not created yet")
        return 0
    facts = json.loads(author_path.read_text(encoding="utf-8"))
    errors = authorblock.validate_author_info(facts, strict=True)
    if errors:
        for err in errors:
            print(f"author_info error: {err}", file=sys.stderr)
        return 2
    title = authorblock.resolve_manuscript_title(project)
    print(f"Title: {title}")
    for line in authorblock.render_author_lines(project):
        print(line)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    project = args.project.resolve() if args.project else project_root()
    author_path = project / authorblock.AUTHOR_REL
    if not author_path.is_file():
        print(f"author_block sync: missing {authorblock.AUTHOR_REL}", file=sys.stderr)
        return 2
    facts = json.loads(author_path.read_text(encoding="utf-8"))
    errors = authorblock.validate_author_info(facts, strict=True)
    if errors:
        for err in errors:
            print(f"author_block sync: {err}", file=sys.stderr)
        return 2
    try:
        written = authorblock.sync_title_page_markdown(project, force=args.force)
    except (OSError, ValueError) as exc:
        print(f"author_block sync failed: {exc}", file=sys.stderr)
        return 2
    if written is None:
        print(
            "author_block sync: non-blinded journal without an explicit separate-title-page rule; "
            "author block will be rendered directly onto page 1 of manuscript.docx (no separate title_page.md needed)"
        )
    else:
        print(f"author_block sync: wrote single-source {written.relative_to(project).as_posix()}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    project = args.project.resolve() if args.project else project_root()
    problems = authorblock.verify_author_placement(project, args.stage)
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 2
    print(f"PASS: author placement and single-source consistency verified for {args.stage}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="render and verify single-source author information for manuscript page 1 and optional title page"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show", help="display active placement policy and rendered single-source author lines")
    p_show.add_argument("--project", type=Path, default=None)
    p_show.set_defaults(fn=cmd_show)

    p_sync = sub.add_parser("sync", help="generate or clean 08_submission/integration/title_page.md from author_info.json")
    p_sync.add_argument("--project", type=Path, default=None)
    p_sync.add_argument("--force", action="store_true", help="write title_page.md even when policy does not require one")
    p_sync.set_defaults(fn=cmd_sync)

    p_check = sub.add_parser("check", help="verify author_info.json and stage placement rules")
    p_check.add_argument("--project", type=Path, default=None)
    p_check.add_argument("--stage", default="S23_package")
    p_check.set_defaults(fn=cmd_check)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
