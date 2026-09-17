"""Data-acquisition completeness, anti-truncation, and full-census audit gate."""
from __future__ import annotations

from pathlib import Path
from .. import dataproof
from . import Ctx, Result, check
from .data_integrity import scan_code_for_truncation


@check("data_acquisition_complete")
def data_acquisition_complete(ctx: Ctx) -> Result:
    outcome = dataproof.validate(ctx.project, ctx.state)
    if not outcome.ok:
        return Result(
            False,
            "data_acquisition_complete",
            "; ".join(outcome.problems[:8]),
            [
                "Run uv run python tools/data_manifest.py sync after acquiring every page/file, then re-run this gate.",
                "Do not use LIMIT, head(), sample(), a fixed page count, or a first-N slice to save time or compute.",
                "If the external source truly blocks full access, ask the user before recording partial_data_authorized=YES.",
            ],
        )

    # Secondary static scan for rogue truncation in analysis and acquisition code
    code_issues = []
    code_dirs = [ctx.p("02_data/acquisition"), ctx.p("03_analysis/code")]
    for cdir in code_dirs:
        if cdir.is_dir():
            for script in sorted(cdir.rglob("*")):
                if script.is_file() and script.suffix.lower() in {".py", ".r", ".sql", ".sh", ".ps1"}:
                    # Let dataproof allow approved annotations if present
                    text = script.read_text(encoding="utf-8", errors="replace")
                    if "MEDPAPER_PILOT_ONLY" in text or "MEDPAPER_PROTOCOL_SAMPLING" in text:
                        continue
                    issues = scan_code_for_truncation(script)
                    code_issues.extend(issues)

    if code_issues:
        return Result(
            False,
            "data_acquisition_complete",
            f"code-level truncation or sampling detected: {'; '.join(code_issues[:5])}",
            [
                "Acquire the complete protocol-defined universe; do not truncate via nrows=, head(), sample() or loop break.",
                "If using a non-analytic schema pilot or protocol-level sampling, use explicit approved annotations.",
            ],
        )

    return Result(
        True,
        "data_acquisition_complete",
        f"{outcome.sources} source(s), {outcome.records_received} received record(s), "
        f"{outcome.raw_files} hashed raw file(s); total-count and terminal-page evidence verified",
    )
