"""Gate runner: turns declarative gate specs into pass/fail results."""
from __future__ import annotations

from pathlib import Path

from . import checks
from .checks import Ctx, Result


def run_stage(
    pipeline,
    state,
    project: Path,
    stage,
    *,
    reuse: bool = False,
    record: bool = False,
    break_on_blocker: bool = True,
    only: str | None = None,
    verbose: bool = False,
) -> list[Result]:
    checks.load_all()
    results: list[Result] = []
    from .gatecache import Receipts
    # Focused single-artifact runs bypass cache reads/writes so partial checks never poison stage receipts.
    effective_reuse = reuse and not only and not verbose
    effective_record = record and not only and not verbose
    receipts = Receipts(project, pipeline, state) if (effective_reuse or effective_record) else None
    if state.data.get("active_revision_round"):
        guard = checks.get("feedback_batch_sealed")
        result = guard(Ctx(pipeline, state, project, stage, {}))
        if not result.ok:
            return [result]
    if not stage.gate:
        results.append(Result(True, "-", "stage declares no gate"))
        return results
    cascade_blockers = {
        "outputs_exist", "writing_ready", "feedback_batch_sealed", "medical_benchmark", "literature_coverage",
        "executor_acceptance", "medical_display_story", "medical_display_production",
        "journal_requirements_current", "display_labels_clinical",
    }
    saw_cascade_blocker = False
    for spec in stage.gate:
        name = spec.get("check")
        if spec.get("since") and state.pin_excludes(stage.id, spec.get("since")):
            results.append(Result(True, name, "new presentation/quality gate not retroactive to this pinned completed stage; wf migrate opts in"))
            continue
        fn = checks.get(name)
        if fn is None:
            results.append(
                Result(False, name or "<missing>", f"unknown check '{name}' - not in the registry",
                       [f"Known checks: {', '.join(checks.known())}"])
            )
            continue
        call_spec = dict(spec)
        if only:
            call_spec["_only"] = only
        if verbose:
            call_spec["_verbose"] = True
        ctx = Ctx(pipeline=pipeline, state=state, project=project, stage=stage, spec=call_spec)
        try:
            identity = receipts.identity(stage, spec) if receipts else None
            res = receipts.get(identity) if receipts and effective_reuse else None
            if res is None:
                res = fn(ctx)
                # Pure checks must not change the very inputs they certify.
                if receipts and identity and identity == receipts.identity(stage, spec):
                    receipts.put(identity, res)
        except Exception as exc:  # noqa: BLE001 - a broken check must not brick the pipeline
            res = Result(False, name, f"check raised {type(exc).__name__}: {exc}")
        if "severity" in spec and not res.ok:
            res.severity = spec["severity"]
        results.append(res)
        if res.blocking and name in cascade_blockers:
            if break_on_blocker:
                results.append(Result(False, "dependent_checks_pending", "Required inputs failed; dependent gates were not executed and cannot be forced."))
                break  # Fix missing inputs before costly dependent checks; never mark them passed.
            saw_cascade_blocker = True
    if not break_on_blocker and saw_cascade_blocker:
        results.append(Result(False, "dependent_checks_pending", "Upstream prerequisite failed; remaining gates were also evaluated because --all-checks was active (fix all before advance)."))
    if receipts:
        receipts.save()
        state.data["check_reuse"] = {"stage": stage.id, "reused": receipts.reused,
                                     "executed": len(results) - receipts.reused}
    return results


def summarize(results: list[Result]) -> tuple[bool, int, int]:
    blocking = sum(1 for r in results if r.blocking)
    warned = sum(1 for r in results if (not r.ok) and r.severity == "warn")
    return blocking == 0, blocking, warned
