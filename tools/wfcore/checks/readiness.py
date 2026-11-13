"""Writing, prototype, feedback and final-file gates."""
from . import Ctx, Result, check
from ..readiness import verify_writing, verify_displays


def _evidence_result(name, run, success):
    try:
        problems = run()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        problems = [str(exc)]  # Expected missing/invalid evidence is a normal failed gate.
    return Result(not problems, name, "; ".join(problems[:8]) or success)


@check("medical_benchmark")
def medical_benchmark(ctx: Ctx) -> Result:
    from ..benchmark import verify_benchmark, display_fit
    layer = ctx.spec.get("layer", "science")
    return _evidence_result("medical_benchmark", lambda: verify_benchmark(ctx.project, layer) + display_fit(ctx.project, layer),
                            "registered close full texts constrain project structure, evidence roles and nonredundant displays; counts are advisory")


@check("literature_coverage")
def literature_coverage(ctx: Ctx) -> Result:
    from ..benchmark import coverage
    return _evidence_result("literature_coverage", lambda: coverage(ctx.project, ctx.spec.get("section"), library_only=ctx.spec.get("library_only", False)),
                            "planned arguments bind their real source keys/passages; semantic support still requires reading")


@check("executor_acceptance")
def executor_acceptance(ctx: Ctx) -> Result:
    from ..benchmark import verify_acceptance
    return _evidence_result("executor_acceptance", lambda: verify_acceptance(ctx.project, ctx.spec.get("layer", "science"), final=ctx.spec.get("final", False)),
                            "executor findings bind actual current manuscript/displays; not an independent or human verdict")


@check("reader_review_coverage")
def reader_review_coverage(ctx: Ctx) -> Result:
    from ..readiness import verify_reader_review
    problems = verify_reader_review(ctx.project)
    return Result(not problems, "reader_review_coverage", "; ".join(problems[:8]) or
                  "independent reader report binds actual prose, tables and rendered figures; semantic judgment remains with the reviewer")


@check("writing_ready")
def writing_ready(ctx: Ctx) -> Result:
    problems = verify_writing(ctx.project,validate_analysis=not ctx.spec.get("reuse_analysis",False))
    return Result(not problems, "writing_ready", "; ".join(problems[:8]) or
                  "analysis contract and clinical story match the S06 freeze")


@check("display_prototypes_reviewed")
def display_prototypes_reviewed(ctx: Ctx) -> Result:
    problems = verify_displays(ctx.project)
    return Result(not problems, "display_prototypes_reviewed", "; ".join(problems[:8]) or
                  "all planned displays have source-bound previews and reader explanations")


@check("feedback_batch_sealed")
def feedback_batch_sealed(ctx: Ctx) -> Result:
    import json
    active = ctx.state.data.get("active_revision_round")
    if active:
        doc = json.loads((ctx.state.dir / "revisions" / f"{active}.json").read_text(encoding="utf-8"))
        if doc.get("status") == "collecting":
            return Result(False, "feedback_batch_sealed",
                          f"{active}: feedback collection is open; wait for the user's end-of-batch instruction")
    return Result(True, "feedback_batch_sealed", "no open feedback collection")


@check("portal_fields_current")
def portal_fields_current(ctx: Ctx) -> Result:
    from ..submission import verify_portal
    problems = verify_portal(ctx.project)
    return Result(not problems, "portal_fields_current", "; ".join(problems[:8]) or
                  "portal fields were computed from the current final DOCX and administrative facts")


@check("benchmark_display_sufficiency")
def benchmark_display_sufficiency(ctx: Ctx) -> Result:
    """Require >=5 recent (<=5y) SCIE comparators and benchmark-aligned figure count/types."""
    if ctx.state.pin_excludes(ctx.stage.id, ctx.spec.get("since")):
        return Result(True, "benchmark_display_sufficiency", "comparator sufficiency gate not retroactive to pinned completed stage")
    from datetime import datetime, timezone
    import statistics
    from ..readiness import load
    layer = ctx.spec.get("layer", "science")
    bench_rel = "01_protocol/artifact_benchmark.json" if layer == "science" else "08_submission/integration/artifact_benchmark.json"
    plan_rel = "01_protocol/artifact_plan.json" if layer == "science" else "08_submission/integration/artifact_plan.json"
    try:
        bench = load(ctx.project, bench_rel)
        plan = load(ctx.project, plan_rel)
    except (OSError, ValueError) as exc:
        return Result(False, "benchmark_display_sufficiency", str(exc))
    lib_years: dict[str, int] = {}
    lib_path = ctx.p("06_refs/library.json")
    if lib_path.is_file():
        try:
            for e in load(ctx.project, "06_refs/library.json").get("entries", []):
                if e.get("citekey") and str(e.get("year", "")).isdigit():
                    lib_years[e["citekey"]] = int(e["year"])
        except (OSError, ValueError, TypeError):
            pass
    rows = bench.get("comparators", [])
    min_comp = int(ctx.target("min_comparators", 5))
    recency_years = int(ctx.target("comparator_recency_years", 5))
    min_year = datetime.now(timezone.utc).year - recency_years
    problems = []
    if len(rows) < min_comp:
        problems.append(f"need at least {min_comp} recent (5-10 recommended) close SCIE Original Article full-text comparators (found {len(rows)})")
    comp_figs = []
    recent_count = 0
    for row in rows:
        key = row.get("citekey", "?")
        obs = row.get("observations", {})
        year_val = row.get("year") or obs.get("year") or lib_years.get(key)
        try:
            y_int = int(year_val)
        except (TypeError, ValueError):
            y_int = None
        if y_int is None:
            problems.append(f"{key}: record comparator publication year (year or observations.year) to prove recent SCIE status")
        elif y_int >= min_year:
            recent_count += 1
        mf = obs.get("main_figures")
        if not isinstance(mf, int) or mf <= 0:
            problems.append(f"{key}: record integer observations.main_figures from the real full text")
        else:
            comp_figs.append(mf)
        ftypes = obs.get("figure_types") or obs.get("display_archetypes")
        if not ftypes or (isinstance(ftypes, str) and len(ftypes.strip()) < 8):
            problems.append(f"{key}: record observations.figure_types / display_archetypes used in that SCIE paper")
    recency_exc = str(bench.get("recency_exception") or (bench.get("adaptation") or {}).get("recency_exception") or "").strip()
    if len(rows) >= min_comp and recent_count < min_comp and len(recency_exc) < 40:
        problems.append(
            f"only {recent_count}/{len(rows)} comparators were published in the last {recency_years} years (>={min_year}); "
            "use 5-10 recent SCIE articles instead of outdated papers (or record a substantive >=40-char recency_exception)"
        )
    main_figs = plan.get("main_figures", [])
    floor = int(ctx.target("min_main_figures_floor", 4))
    ratio = float(ctx.target("min_figure_ratio_to_benchmark", 0.7))
    expected_min = floor
    if comp_figs:
        expected_min = max(3, min(floor, round(statistics.median(comp_figs) * ratio)))
        if statistics.median(comp_figs) >= 5:
            expected_min = max(expected_min, 4)
    rationale = str((bench.get("adaptation") or {}).get("displays", {}).get("figure_count_rationale") or plan.get("figure_count_rationale") or "").strip()
    sparse_exc = str(plan.get("sparse_figure_justification") or (bench.get("adaptation") or {}).get("displays", {}).get("sparse_figure_justification") or "").strip()
    if len(rationale) < 30:
        problems.append("record adaptation.displays.figure_count_rationale (>=30 chars) synthesizing how comparator figure counts/types map to this study")
    if len(main_figs) < expected_min and len(sparse_exc) < 50:
        problems.append(
            f"main_figures count ({len(main_figs)}) is thin relative to SCIE comparators (target >= {expected_min}, comparator median={statistics.median(comp_figs) if comp_figs else 'n/a'}); "
            "expand figures with comparator-matched archetypes or provide substantive clinical sparse_figure_justification (>=50 chars)"
        )
    return Result(not problems, "benchmark_display_sufficiency", "; ".join(problems[:6]) or
                  f"{len(rows)} SCIE comparators and {len(main_figs)} planned main figure(s) satisfy benchmark display sufficiency")


@check("literature_sufficiency")
def literature_sufficiency(ctx: Ctx) -> Result:
    """Enforce configurable non-zero reference-pool and manuscript/section citation floors."""
    if ctx.state.pin_excludes(ctx.stage.id, ctx.spec.get("since")):
        return Result(True, "literature_sufficiency", "literature sufficiency gate not retroactive to pinned completed stage")
    from ..readiness import load
    from .refs import citekeys
    mode = ctx.spec.get("mode", "library")
    problems = []
    try:
        lib = load(ctx.project, "06_refs/library.json")
    except (OSError, ValueError) as exc:
        return Result(False, "literature_sufficiency", str(exc))
    entries = {e.get("citekey"): e for e in lib.get("entries", []) if e.get("citekey")}

    if mode == "library":
        floor = int(ctx.spec.get("min_entries") or ctx.target("min_reflib_entries", 40))
        if len(entries) < floor:
            problems.append(f"06_refs/library.json has {len(entries)} entries, below required reference pool minimum ({floor})")
        return Result(not problems, "literature_sufficiency", "; ".join(problems) or
                      f"reference pool size ({len(entries)} >= {floor}) meets sufficiency floor")

    rel = ctx.spec.get("path", "07_manuscript/full_manuscript.md")
    if not ctx.p(rel).is_file():
        return Result(False, "literature_sufficiency", f"missing {rel}")
    used = {k for k in citekeys(ctx.read(rel)) if k in entries}
    if mode == "section":
        sec_key = "min_intro_refs" if "introduction" in rel else "min_discussion_refs"
        default_val = 10 if "introduction" in rel else 18
        floor = int(ctx.spec.get("min_refs") or ctx.target(sec_key, default_val))
        if len(used) < floor:
            problems.append(f"{rel} cites {len(used)} verified unique reference(s), below required minimum ({floor})")
    else:
        floor = int(ctx.spec.get("min_refs") or ctx.target("min_manuscript_refs", 30))
        bench_path = ctx.p("01_protocol/artifact_benchmark.json")
        if bench_path.is_file():
            import statistics
            bench = load(ctx.project, "01_protocol/artifact_benchmark.json")
            comp_refs = [r.get("observations", {}).get("references") for r in bench.get("comparators", [])
                         if isinstance(r.get("observations", {}).get("references"), int) and r["observations"]["references"] > 0]
            if comp_refs:
                derived = round(statistics.median(comp_refs) * 0.65)
                if not str((bench.get("adaptation") or {}).get("references_rationale", "")).strip():
                    floor = max(floor, min(derived, floor + 15))
        if len(used) < floor:
            problems.append(f"{rel} cites {len(used)} unique reference(s), below required manuscript floor ({floor})")
    return Result(not problems, "literature_sufficiency", "; ".join(problems) or
                  f"{rel}: {len(used)} verified unique citations meet minimum floor")
