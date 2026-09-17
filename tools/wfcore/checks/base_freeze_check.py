"""Checks enforcing Base Manuscript Freeze and read-only protection of canonical assets."""
from __future__ import annotations

from pathlib import Path
from ..basefreeze import BASE_FREEZE_REL, verify_base_freeze
from . import Ctx, Result, check


@check("base_manuscript_frozen")
def base_manuscript_frozen(ctx: Ctx) -> Result:
    """Ensure the canonical base manuscript has been cryptographically frozen at S17."""
    freeze_file = ctx.p(BASE_FREEZE_REL)
    if not freeze_file.exists():
        return Result(
            False,
            "base_manuscript_frozen",
            f"Missing base manuscript freeze manifest: {BASE_FREEZE_REL}",
            [
                "Run 'uv run python tools/freeze_base.py freeze --project project' to seal the canonical manuscript before journal selection."
            ]
        )

    ok, problems, count = verify_base_freeze(ctx.project, freeze_file)
    if not ok:
        return Result(
            False,
            "base_manuscript_frozen",
            f"Base manuscript freeze verification failed: {'; '.join(problems[:3])}",
            ["Ensure all mandatory manuscript files exist in 07_manuscript/ and re-run freeze."]
        )

    return Result(
        True,
        "base_manuscript_frozen",
        f"Base manuscript freeze active: {count} foundational files locked and verified"
    )


@check("base_manuscript_untouched")
def base_manuscript_untouched(ctx: Ctx) -> Result:
    """Enforce absolute read-only protection on 01_protocol/ through 07_manuscript/.

    Guarantees that journal selection (S18), polish/adaptation (S19), and bundle packaging (S20)
    never mutate or pollute the canonical base manuscript.
    All journal-specific changes MUST be isolated inside 08_submission/.
    """
    freeze_file = ctx.p(BASE_FREEZE_REL)
    if not freeze_file.exists():
        return Result(
            False,
            "base_manuscript_untouched",
            f"Base freeze manifest {BASE_FREEZE_REL} is missing! Base manuscript must be frozen before journal adaptation.",
            ["Revert to S17 and execute base freeze."]
        )

    ok, problems, count = verify_base_freeze(ctx.project, freeze_file)
    if not ok:
        return Result(
            False,
            "base_manuscript_untouched",
            f"FATAL ARCHITECTURAL VIOLATION: Base manuscript was modified after freeze: {'; '.join(problems[:3])}",
            [
                "DO NOT modify files under 07_manuscript/ or 01-06 core folders for specific journal requirements.",
                "Place all journal-adapted text, word-count reductions, and custom sections into 08_submission/adapted_manuscript/ or 08_submission/bundle/.",
                "Restore modified 07_manuscript/ files to their frozen state."
            ]
        )

    return Result(
        True,
        "base_manuscript_untouched",
        f"Verified {count} frozen base files: 100% untouched; journal adaptation properly isolated in 08_submission/"
    )
