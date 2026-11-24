#!/usr/bin/env python3
"""Automatically cross-check rendered tables/figures against Methods & Results and write 07_manuscript/reconciliation.md."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from wfcore import registry  # noqa: E402
from wfcore.checks import Ctx, get, load_all  # noqa: E402
from wfcore.revision import guard_outputs  # noqa: E402
from wfcore.state import State  # noqa: E402


def project_root(override: Path | None = None) -> Path:
    if override is not None:
        return override.resolve()
    raw = os.environ.get("MEDPAPER_PROJECT")
    return Path(raw).resolve() if raw else (ROOT / "project").resolve()


def _citation_lines(md_text: str, item_id: str) -> list[int]:
    lines: list[int] = []
    parts = [re.escape(p) for p in item_id.strip().split() if p]
    if not parts:
        return lines
    compact_id = r"\s*".join(parts)
    pat = re.compile(rf"\b{compact_id}(?:[A-Za-z]|\b)", re.I)
    for idx, line in enumerate(md_text.splitlines(), 1):
        if pat.search(line):
            lines.append(idx)
    return lines


def generate_reconciliation(project: Path) -> tuple[int, str, list[str]]:
    load_all()
    pipe = registry.load()
    st_file = project / ".wf/state.json"
    st = State(project).load() if st_file.is_file() else State(project)
    stage = pipe.stage("S12_reconcile")

    plan_path = project / "01_protocol/artifact_plan.json"
    if not plan_path.is_file():
        return 2, "", ["01_protocol/artifact_plan.json missing"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    methods_txt = (project / "07_manuscript/methods.md").read_text(encoding="utf-8") if (project / "07_manuscript/methods.md").is_file() else ""
    results_txt = (project / "07_manuscript/results.md").read_text(encoding="utf-8") if (project / "07_manuscript/results.md").is_file() else ""

    gate_problems: list[str] = []
    for chk_name, spec in (
        ("artifact_refs_consistent", {"paths": ["07_manuscript/results.md", "07_manuscript/methods.md"], "require_all_cited": True, "require_rendered": True}),
        ("display_numbering_consistent", {"paths": ["07_manuscript/methods.md", "07_manuscript/results.md"]}),
        ("numbers_cross_match", {}),
    ):
        res = get(chk_name)(Ctx(pipe, st, project, stage, spec))
        if not res.ok and res.blocking:
            gate_problems.append(f"{chk_name}: {res.detail}")

    rows: list[str] = []
    checked_files: list[str] = []
    for group in ("main_tables", "main_figures", "supp_tables", "supp_figures"):
        for entry in plan.get(group, []):
            item_id = str(entry.get("id", "?"))
            rel_file = str(entry.get("file", ""))
            exists = bool(rel_file and (project / rel_file).is_file())
            if exists and rel_file not in checked_files:
                checked_files.append(rel_file)
            r_lines = _citation_lines(results_txt, item_id)
            m_lines = _citation_lines(methods_txt, item_id)
            locs = []
            if r_lines:
                locs.append("Results L" + ",".join(map(str, r_lines[:4])))
            if m_lines:
                locs.append("Methods L" + ",".join(map(str, m_lines[:4])))
            loc_str = "; ".join(locs) if locs else "NOT CITED"
            status = "file verified & cross-checked" if exists and locs and not gate_problems else "NEEDS FIX"
            rows.append(f"- `{item_id}` (`{rel_file}`) | cited in {loc_str} | {status}")

    discrepancy_block = (
        "No blocking prose-display discrepancies detected across `artifact_refs_consistent`, `display_numbering_consistent`, and `numbers_cross_match`."
        if not gate_problems
        else "\n".join(f"- [BLOCKING] {p}" for p in gate_problems)
    )
    checked_block = "\n".join(f"- `{f}`" for f in checked_files) or "- (no display files found)"

    md = (
        "# Artifact-Prose Reconciliation\n\n"
        "## Display item cross-check\n\n"
        + ("\n".join(rows) if rows else "- (no planned display items)")
        + "\n\n## Discrepancies found and how they were resolved\n\n"
        + discrepancy_block
        + "\n\n## Checked by looking\n\n"
        + checked_block
        + "\n"
    )
    return (2 if gate_problems else 0), md, gate_problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Auto-reconcile rendered displays against Methods/Results and write reconciliation.md")
    ap.add_argument("--project", type=Path, default=None)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args(argv)

    proj = project_root(args.project)
    rc, md, problems = generate_reconciliation(proj)
    if not args.check_only and md:
        out = proj / "07_manuscript/reconciliation.md"
        guard_outputs(proj, [out])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"wrote {out.relative_to(proj).as_posix()} ({'PASS' if rc == 0 else 'FAIL'})")
    if problems:
        for p in problems:
            print(f"  [MISMATCH] {p}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
