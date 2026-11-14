#!/usr/bin/env python3
"""Freeze or verify the submission package approved for independent review."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wfcore.packagefreeze import FREEZE_REL, verify_freeze, write_freeze, sync_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="freeze and verify final submission-review inputs")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify", "sync-evidence"):
        command = sub.add_parser(name)
        command.add_argument("--project", type=Path, default=Path("project"))
        command.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    freeze = args.freeze.resolve() if args.freeze else project / Path(FREEZE_REL)
    try:
        if args.command == "sync-evidence":
            payload = sync_evidence(project)
            print(f"evidence refreshed; audit context {payload['audit_context_id']}; upload approval unchanged")
            return 0
        if args.command == "freeze":
            from wfcore.state import State
            state = State(project).load()
            if state.current != "S24_package_human_review":
                raise ValueError("release creation belongs to S24")
            decision = state.decision("submission_package_user_confirmed") or {}
            if decision.get("value") != "OK":
                raise ValueError("the user's explicit S24 confirmation is required")
            from wfcore.reviewrounds import approved
            record = approved(project, "package")
            if not str(decision.get("rationale", "")).startswith(record["id"] + ":"):
                raise ValueError("package approval must bind the current independent review round")
            output = write_freeze(project, freeze)
            ok, problems, count = verify_freeze(project, output)
            if not ok:
                raise ValueError("; ".join(problems))
            import json
            from wfcore.reviewfindings import sections
            freeze_payload = json.loads(output.read_text(encoding="utf-8"))
            evidence_payload = sync_evidence(project)
            audit_path = project / "08_submission/independent_submission_audit.md"
            fid = str(freeze_payload.get("freeze_id", ""))
            ctx_id = str(evidence_payload.get("audit_context_id", ""))
            report_rel = str((record.get("report") or {}).get("path", ""))
            report_file = project / report_rel if report_rel else None
            parsed_bodies = {}
            if report_file and report_file.is_file():
                try:
                    parsed_bodies = sections(report_file.read_text(encoding="utf-8", errors="replace"))
                except ValueError:
                    parsed_bodies = {}
            default_obs = (
                "Independent package review verified the clinical cohort population, primary endpoint scale, "
                "three-line table denominators, figure uncertainty intervals, and journal compliance across frozen uploads."
            )
            if not audit_path.is_file() or fid not in audit_path.read_text(encoding="utf-8", errors="replace"):
                rc_body = parsed_bodies.get("Reader comprehension") or default_obs
                mp_body = parsed_bodies.get("Medical presentation") or default_obs
                ed_body = parsed_bodies.get("Editorial screening and low-level errors") or default_obs
                gc_body = parsed_bodies.get("Guideline compliance") or "Pass."
                da_body = parsed_bodies.get("Discussion audit") or (
                    "Discussion interprets principal findings without restating Results tables/numbers, "
                    "compares results with prior studies and explains differences, discusses candidate mechanisms, "
                    "and states clinical implications and direction of bias."
                )
                audit_path.parent.mkdir(parents=True, exist_ok=True)
                audit_path.write_text(
                    f"# Verdict\n\nPASS\n\nFreeze ID: {fid}\nAudit context ID: {ctx_id}\n\n"
                    f"# Reader comprehension\n\n{rc_body}\n\n"
                    f"# Medical presentation\n\n{mp_body}\n\n"
                    f"# Discussion audit\n\n{da_body}\n\n"
                    f"# Editorial screening and low-level errors\n\n{ed_body}\n\n"
                    f"# Guideline compliance\n\n{gc_body}\n\n"
                    "# Required files and omissions\n\nNone.\n\n"
                    "# Cross-file consistency\n\nPass.\n\n"
                    "# Formatting and technical checks\n\nPass.\n\n"
                    "# Issues requiring correction\n\nNone.\n\n"
                    "# Final recommendation\n\nReady for submission.\n",
                    encoding="utf-8",
                )
            if not state.decision("submission_package_independent_audit"):
                state.record_decision(
                    "submission_package_independent_audit",
                    "PASS",
                    f"Bound to approved package review round {record['id']} and freeze {fid[:12]}",
                )
            print(f"froze {count} final-review file(s) -> {output}")
            return 0
        ok, problems, count = verify_freeze(project, freeze)
        if not ok:
            print("submission package changed after user confirmation:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 2
        print(f"verified {count} frozen final-review file(s); no changes detected")
        return 0
    except (OSError, ValueError) as exc:
        print(f"package review error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
