#!/usr/bin/env python3
"""Scaffold, lock, and verify the isolated Discussion brief & 6-part outline (v1.28+)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from wfcore import discussion  # noqa: E402


def project_root() -> Path:
    raw = os.environ.get("MEDPAPER_PROJECT")
    return Path(raw).resolve() if raw else ROOT / "project"


def _build_brief_markdown(project: Path) -> str:
    """Assemble an initial table-free, callout-free brief from prose & deep-read notes only."""
    # Never read 04_tables/ or 01_protocol/artifact_plan.json.
    facts_path = project / "01_protocol/study_facts.json"
    facts = {}
    if facts_path.is_file():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            facts = {}

    principal_parts: list[str] = []
    for key in ("clinical_question", "main_finding", "clinical_relevance"):
        val = str(facts.get(key, "")).strip()
        if val:
            principal_parts.append(discussion.strip_display_callouts(val))
    results_path = project / discussion.RESULTS_REL
    if results_path.is_file():
        raw_res = results_path.read_text(encoding="utf-8", errors="replace")
        cleaned_res = discussion.strip_display_callouts(re.sub(r"(?m)^#+\s+.*$", "", raw_res))
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned_res) if len(s.strip()) > 25]
        if sentences:
            principal_parts.append(
                "Synthesize the direction and clinical magnitude of the primary and sensitivity findings in plain prose "
                "(do not copy Results sentences or cite table/figure numbers)."
            )
    if not principal_parts:
        principal_parts.append(
            "Summarize the primary clinical finding and key secondary patterns in plain text without table or figure numbers."
        )

    deepread_parts: list[str] = []
    idx_path = project / "06_refs/deepread/deepread_index.json"
    if idx_path.is_file():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            idx = {}
        for item in idx.get("selected", []):
            ck = str(item.get("citekey", "")).strip()
            reason = discussion.strip_display_callouts(str(item.get("reason", "")).strip())
            notes_rel = str(item.get("notes", "")).strip()
            excerpt = ""
            if notes_rel and (project / notes_rel).is_file():
                notes_txt = (project / notes_rel).read_text(encoding="utf-8", errors="replace")
                lines = [
                    discussion.strip_display_callouts(line.lstrip("-*# ").strip())
                    for line in notes_txt.splitlines()
                    if len(line.strip()) > 30 and not line.strip().startswith("#")
                ]
                if lines:
                    excerpt = " " + lines[0][:220]
            if ck:
                deepread_parts.append(f"- [@{ck}]: {reason}.{excerpt}".strip())
    if not deepread_parts:
        deepread_parts.append(
            "- Summarize concordant and discordant findings from deep-read full texts and the methodological or population reasons for differences."
        )

    mech_parts: list[str] = [
        "Outline plausible biological, pathophysiological, or care-pathway explanations grounded in cited deep-read literature, clearly framed as hypotheses rather than proven causal mechanisms."
    ]

    lim_parts: list[str] = []
    cannot_claim = str(facts.get("cannot_claim", "")).strip()
    if cannot_claim:
        lim_parts.append(discussion.strip_display_callouts(cannot_claim))
    for rel in ("01_protocol/protocol_diff.md", "03_analysis/notes.md"):
        p = project / rel
        if p.is_file():
            txt = discussion.strip_display_callouts(re.sub(r"(?m)^#+\s+.*$", "", p.read_text(encoding="utf-8", errors="replace")))
            if len(txt) >= 30:
                lim_parts.append(txt[:300])
    if not lim_parts:
        lim_parts.append(
            "Document design constraints, residual confounding, measurement error, generalizability boundaries, and the expected direction of bias (toward or away from the null)."
        )

    sections = [
        "# Discussion writing brief",
        f"## {discussion.BRIEF_SECTIONS[0]}\n\n" + "\n\n".join(principal_parts),
        f"## {discussion.BRIEF_SECTIONS[1]}\n\n" + "\n".join(deepread_parts),
        f"## {discussion.BRIEF_SECTIONS[2]}\n\n" + "\n\n".join(mech_parts),
        f"## {discussion.BRIEF_SECTIONS[3]}\n\n" + "\n\n".join(lim_parts),
    ]
    return "\n\n".join(sections).rstrip() + "\n"


def cmd_scaffold(args: argparse.Namespace) -> int:
    project = args.project.resolve() if args.project else project_root()
    brief_path = project / discussion.BRIEF_REL
    if brief_path.is_file() and not args.overwrite:
        print(f"discussion_brief scaffold: {discussion.BRIEF_REL} already exists (use --overwrite to regenerate)", file=sys.stderr)
        return 2
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(_build_brief_markdown(project), encoding="utf-8")
    print(f"wrote isolated brief -> {discussion.BRIEF_REL}")
    outline_path = project / discussion.OUTLINE_REL
    if not outline_path.is_file():
        print(
            f"next: author concise 6-part {discussion.OUTLINE_REL}, then run "
            "'uv run python tools/manuscript/discussion_brief.py lock-outline' BEFORE drafting 07_manuscript/discussion.md"
        )
    return 0


def cmd_lock(args: argparse.Namespace) -> int:
    project = args.project.resolve() if args.project else project_root()
    try:
        payload = discussion.lock_outline(project, reset_draft=args.reset_draft)
    except ValueError as exc:
        print(f"lock-outline failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"locked Discussion brief + 6-part outline at {payload['locked_at']} "
        f"(outline_sha256={payload['outline_sha256'][:12]}...); ready to draft {discussion.DISCUSSION_REL}"
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    project = args.project.resolve() if args.project else project_root()
    problems: list[str] = []
    if args.workflow:
        problems.extend(discussion.validate_discussion_workflow(project))
    problems.extend(
        discussion.validate_discussion_discipline(
            project,
            args.path,
            supp_max=args.supp_max,
            main_max=args.main_max,
        )
    )
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 2
    print(f"PASS: Discussion checks clean for {args.path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="prepare and verify table-free Discussion brief, 6-part outline lock, and anti-restatement discipline"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scaf = sub.add_parser("scaffold", help="generate table-free, callout-free 07_manuscript/discussion_brief.md")
    p_scaf.add_argument("--project", type=Path, default=None)
    p_scaf.add_argument("--overwrite", action="store_true")
    p_scaf.set_defaults(fn=cmd_scaffold)

    p_lock = sub.add_parser("lock-outline", help="validate brief + 6-part outline and lock pre-draft receipt")
    p_lock.add_argument("--project", type=Path, default=None)
    p_lock.add_argument("--reset-draft", action="store_true", help="remove an existing discussion.md draft before locking")
    p_lock.set_defaults(fn=cmd_lock)

    p_chk = sub.add_parser("check", help="run Discussion workflow and prose discipline checks")
    p_chk.add_argument("--project", type=Path, default=None)
    p_chk.add_argument("--path", default=discussion.DISCUSSION_REL)
    p_chk.add_argument("--workflow", action="store_true", help="also validate brief, outline, and lock receipt")
    p_chk.add_argument("--supp-max", type=int, default=1)
    p_chk.add_argument("--main-max", type=int, default=2)
    p_chk.set_defaults(fn=cmd_check)

    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
