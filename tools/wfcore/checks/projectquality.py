"""Concrete early contracts and assembly diagnostics, not extra review reports."""
import csv
import json
import re
from . import Ctx,Result,check
from ..readiness import load
from ..packagefreeze import _safe_path,_sha256

@check("journal_requirements_current")
def journal_requirements_current(ctx):
    from .. import journalcontext as jc
    if not jc.enabled(ctx.project) and ctx.state.pin_excludes("S20_journal","1.24.0"):
        return Result(True,"journal_requirements_current","Completed legacy journal attempt remains historical; begin a new context at the next journal switch")
    problems=jc.problems(ctx.project)
    if not problems and ctx.spec.get("final"):
        from ..submissionqc import verify
        problems=verify(ctx.project)
    return Result(not problems,"journal_requirements_current","; ".join(problems[:8]) or "Current journal/article/stage, actual official sources and configured/final-file rule checks agree")

@check("medical_display_story")
def medical_display_story(ctx):
    from ..displayquality import story_problems
    from ..benchmark import dossier
    try:
        problems=story_problems(load(ctx.project,"01_protocol/artifact_plan.json"),dossier(ctx.project))
    except (OSError,ValueError,KeyError,TypeError) as exc: problems=[str(exc)]
    return Result(not problems,"medical_display_story","; ".join(problems[:8]) or "Core medical reader tasks mapped to actual main/supplement displays and comparator decisions")

@check("medical_display_production")
def medical_display_production(ctx):
    from ..displayquality import production_problems
    try:
        problems=production_problems(ctx.project,ctx.spec["kind"],only=ctx.spec.get("_only"))
    except (OSError,ValueError,KeyError,TypeError) as exc: problems=[str(exc)]
    limit = len(problems) if ctx.spec.get("_verbose") else 8
    return Result(not problems,"medical_display_production","; ".join(problems[:limit]) or "Actual production renders bound to medical reading; structural checks do not certify scientific understanding")

@check("research_context_known")
def research_context_known(ctx):
    try:
        idea=load(ctx.project,"01_protocol/idea.json"); sources=idea.get("research_context",{}).get("sources",[])
        if not idea.get("design") or not sources or any(not row.get("name") or not row.get("type") for row in sources):
            raise ValueError("At intake establish the actual design and every data-source type; ask only these missing facts")
    except (OSError,ValueError,TypeError) as exc: return Result(False,"research_context_known",str(exc))
    return Result(True,"research_context_known","Actual study design and source types established at intake")

@check("study_governance")
def study_governance(ctx):
    from ..studypolicy import assess,REPORT
    try:
        actual=assess(ctx.project); saved=load(ctx.project,REPORT)
        problems=actual["unresolved"]+([] if actual==saved else ["Governance assessment stale; run tools/study_policy.py"])
    except (OSError,ValueError,KeyError) as exc: problems=[str(exc)]
    return Result(not problems,"study_governance","; ".join(problems) or "Design/source-specific assessment supported; no invented institutional decisions")

@check("variable_definitions")
def variable_definitions(ctx):
    try:
        plan=load(ctx.project,"01_protocol/analysis_contract.json")
        from ..readiness import contract_problems
        problems=contract_problems(ctx.project,plan)
        if problems: raise ValueError("; ".join(problems[:6]))
        rows=plan.get("variable_definitions",[]); needed={"role","source_field","definition","unit","coding","time_window","missing_rule","source_locator"}
        if not rows: raise ValueError("Before analysis, record the variable-definition crosswalk in analysis_contract.json")
        if any(any(not str(r.get(k,"")).strip() for k in needed) for r in rows): raise ValueError("Each crosswalk row needs role, field, definition, units, coding, time, missing rule and actual source locator")
        if not {"eligibility","outcome"}.issubset({r["role"] for r in rows}): raise ValueError("Crosswalk must include eligibility and outcome definitions; explicitly address exposure/comparator applicability")
    except (OSError,ValueError,TypeError) as exc: return Result(False,"variable_definitions",str(exc))
    return Result(True,"variable_definitions",f"{len(rows)} explicit variable definitions; executor must compare each against source documentation")

@check("statistical_reporting_plan")
def statistical_reporting_plan(ctx):
    try:
        row=load(ctx.project,"01_protocol/analysis_contract.json").get("statistical_reporting",{})
        if type(row.get("primary_comparisons")) is not int or row["primary_comparisons"]<0: raise ValueError("Specify how many primary comparisons before analysis (zero needs a justified descriptive-only plan)")
        for field in ("multiplicity","effect_measures","intervals","exploratory_labeling"):
            if len(str(row.get(field,"")))<12: raise ValueError(f"Specify {field}, with rationale when adjustment is not appropriate")
        if row["primary_comparisons"]==0 and len(str(row.get("descriptive_only_reason","")))<20: raise ValueError("Explain why the study is descriptive-only without primary comparisons")
    except (OSError,ValueError,TypeError) as exc: return Result(False,"statistical_reporting_plan",str(exc))
    return Result(True,"statistical_reporting_plan","Primary comparison family, multiplicity and effect/interval reporting explicit")

@check("source_record_spotcheck")
def source_record_spotcheck(ctx):
    try:
        rows=load(ctx.project,"03_analysis/results/dataset_summary.json").get("source_record_check",{})
        population=rows.get("eligible_records"); cases=rows.get("cases",[])
        if type(population) is not int or population<1: raise ValueError("Record the eligible source-record count")
        if len(cases)!=min(10,population) or len({r.get("record_locator") for r in cases})!=len(cases): raise ValueError("Trace ten distinct cases (all when fewer) to source; this is QC, never analysis sampling")
        if len(str(rows.get("selection_basis","")))<20: raise ValueError("State reproducible case selection covering outcome/groups and edge cases, not convenient matching records")
        digests={}
        for case in cases:
            for field in ("record_locator","source_file","source_sha256","derived_file","derived_sha256","comparisons"):
                if not case.get(field): raise ValueError(f"Spotcheck needs actual {field}")
            for prefix in ("source","derived"):
                from ..datasources import input_path
                path=input_path(ctx.project,case[prefix+"_file"]) if prefix=="source" else _safe_path(ctx.project,case[prefix+"_file"])[1]
                if not path.is_file(): raise ValueError("Source/derived record-check file missing")
                if path not in digests: digests[path]=_sha256(path)
                if digests[path].casefold()!=case[prefix+"_sha256"].casefold(): raise ValueError("Source/derived record-check evidence drifted")
            if not isinstance(case["comparisons"],list) or not case["comparisons"]: raise ValueError("Actually compare source fields and derived fields, not an empty checklist")
            if any(not item.get("variable") or "source_value" not in item or "derived_value" not in item for item in case["comparisons"]): raise ValueError("Each comparison needs the actual variable and both observed values, including explicit nulls")
            if any(item.get("source_value")!=item.get("derived_value") and len(str(item.get("resolved_by","")))<20 for item in case["comparisons"]): raise ValueError("Unresolved source/derived discrepancy; correct producer and affected results")
        if not rows.get("reviewer") or not rows.get("checked_at"): raise ValueError("Record who actually checked the source records and when")
    except (OSError,ValueError,KeyError,TypeError) as exc: return Result(False,"source_record_spotcheck",str(exc))
    return Result(True,"source_record_spotcheck","Ten-case/all-small-cohort source trace recorded and bound; not certification of every clinical record")

@check("reference_usage")
def reference_usage(ctx):
    from .refs import citekeys
    try:
        library=load(ctx.project,"06_refs/library.json"); entries={r["citekey"]:r for r in library["entries"]}
        cited=set()
        for name in ("introduction","methods","results","discussion","abstract","supplementary_methods"):
            path=ctx.project/f"07_manuscript/{name}.md"
            if path.is_file(): cited.update(citekeys(path.read_text(encoding="utf-8")))
        usage=ctx.project/"06_refs/usage.json"
        reasons=json.loads(usage.read_text(encoding="utf-8")).get("uncited_reasons",{}) if usage.is_file() else {}
        absent=[
            key for key in entries.keys()-cited
            if entries[key].get("pool_role")!="candidate" and len(str(reasons.get(key,"")))<20
        ]
        if absent:
            return Result(
                False,
                "reference_usage",
                "Unused non-candidate library entries (run `uv run python tools/pubmed/build_library.py --archive-uncited` to archive candidate pool): "
                + ", ".join(sorted(absent)[:10]),
                severity="warn",
            )
    except (OSError,ValueError,KeyError) as exc: return Result(False,"reference_usage",str(exc))
    return Result(True,"reference_usage",f"library={len(entries)}, actually cited={len(cited)}, unused/candidate accounted={len(entries.keys()-cited)}; never pad citations")

@check("manuscript_size_health")
def manuscript_size_health(ctx):
    from .refs import citekeys
    from .readiness import _resolve_genre_profile
    try:
        genre_name, genre_prof, _ = _resolve_genre_profile(ctx)
        text=ctx.read("07_manuscript/full_manuscript.md"); count=len(set(citekeys(text)))
        words=len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b",text))
        lo, hi = ((12, 30) if genre_name in {"brief_report", "short_communication"}
                  else (5, 12) if genre_name == "research_letter"
                  else (45, 60))
        return Result(lo<=count<=hi,"manuscript_size_health",f"Advisory assembly health ({genre_name}): {count} cited sources ({lo}–{hi} reference band, not a quota), {words} words incl. all sections. Explain project/benchmark fit; never add irrelevant papers.",severity="warn")
    except OSError as exc: return Result(False,"manuscript_size_health",str(exc))


@check("section_balance_health")
def section_balance_health(ctx: Ctx) -> Result:
    """Advisory section-balance & Introduction-depth guard against top-light manuscripts and S22 over-trimming."""
    if ctx.state.pin_excludes(ctx.stage.id, ctx.spec.get("since")):
        return Result(True, "section_balance_health", "section balance check not retroactive to pinned completed stage")
    from ..benchmark import comparator_section_baselines
    from .polish import _canonical_section_counts
    from .readiness import _resolve_genre_profile
    from .text import _wordcount

    genre_name, _, _ = _resolve_genre_profile(ctx)
    layer = ctx.spec.get("layer") or ("journal" if ctx.stage.id.startswith(("S20_", "S21_", "S22_", "S23_", "S24_", "S25_")) else "science")
    mode = ctx.spec.get("mode", "full")
    if genre_name in {"brief_report", "short_communication"}:
        intro_floor = 200
    elif genre_name == "research_letter":
        intro_floor = 100
    else:
        intro_floor = 350 if layer == "journal" else 400

    baselines = comparator_section_baselines(ctx.project, layer)
    if layer == "journal" and not baselines.get("sections"):
        baselines = comparator_section_baselines(ctx.project, "science")
    comp_intro_med = (baselines.get("sections", {}).get("introduction") or {}).get("median")

    advisories: list[str] = []
    if mode == "intro":
        rel = ctx.spec.get("path", "07_manuscript/introduction.md")
        if not ctx.p(rel).is_file():
            return Result(False, "section_balance_health", f"{rel} missing", severity="warn")
        intro_words = _wordcount(ctx.read(rel))
        if intro_words < intro_floor:
            advisories.append(
                f"{rel}: Introduction is thin ({intro_words} words < advisory {intro_floor} words for {genre_name}); "
                "verify clinical burden, mechanistic rationale, and explicit literature-gap depth"
            )
        if comp_intro_med and intro_words < round(comp_intro_med * 0.50):
            advisories.append(
                f"{rel}: Introduction ({intro_words} words) is under 50% of registered comparator median ({comp_intro_med} words)"
            )
        detail = "; ".join(advisories) or (
            f"Introduction depth healthy ({intro_words} words; {genre_name}"
            + (f"; comparator median {comp_intro_med}" if comp_intro_med else "")
            + ")"
        )
        return Result(not advisories, "section_balance_health", detail, severity="warn")

    rel = ctx.spec.get("path") or (
        "08_submission/integration/full_manuscript.md" if layer == "journal" else "07_manuscript/full_manuscript.md"
    )
    if not ctx.p(rel).is_file():
        return Result(False, "section_balance_health", f"{rel} missing", severity="warn")
    sec_counts = _canonical_section_counts(ctx.read(rel))
    intro_words = sec_counts.get("introduction", 0) + sec_counts.get("aim", 0)
    body_keys = ("introduction", "aim", "methods", "ethics approval", "results", "discussion", "conclusion")
    main_words = sum(sec_counts.get(k, 0) for k in body_keys)
    intro_share = (intro_words / main_words * 100.0) if main_words > 0 else 0.0

    if intro_words < intro_floor:
        advisories.append(
            f"{rel}: Introduction (+Aim) is {intro_words} words (< advisory {intro_floor} words for {genre_name})"
        )
    if main_words > 0 and intro_share < 10.0:
        advisories.append(
            f"{rel}: Introduction accounts for only {intro_share:.1f}% of main text ({intro_words}/{main_words} words; < 10% balance floor)"
        )
    if comp_intro_med and intro_words < round(comp_intro_med * 0.50):
        advisories.append(
            f"{rel}: Introduction ({intro_words} words) is < 50% of comparator median ({comp_intro_med} words)"
        )
    if layer == "journal" and ctx.p("07_manuscript/full_manuscript.md").is_file():
        sci_counts = _canonical_section_counts(ctx.read("07_manuscript/full_manuscript.md"))
        sci_intro = sci_counts.get("introduction", 0) + sci_counts.get("aim", 0)
        if sci_intro >= 150 and intro_words < sci_intro * 0.70:
            drop_pct = (1.0 - intro_words / sci_intro) * 100.0
            advisories.append(
                f"{rel}: Introduction shrank by {drop_pct:.1f}% vs S19 scientific master ({sci_intro} -> {intro_words} words); "
                "prioritize moving redundant Methods/Results detail to Supplementary Methods / Online Resources instead of stripping Introduction"
            )
    breakdown = ", ".join(f"{k}={sec_counts[k]}" for k in body_keys if sec_counts.get(k, 0) > 0)
    detail = "; ".join(advisories) or (
        f"Section balance healthy ({genre_name}; main={main_words} words, intro={intro_words} [{intro_share:.1f}%]; {breakdown})"
    )
    return Result(not advisories, "section_balance_health", detail, severity="warn")

@check("journal_display_fit")
def journal_display_fit(ctx):
    from ..journalrules import display_limits,compare
    from ..packagefreeze import _sha256
    try:
        plan_rel="08_submission/integration/artifact_plan.json"
        plan=load(ctx.project,plan_rel)
        counts={k:len(plan.get(k,[])) for k in ("main_figures","main_tables","supp_figures","supp_tables")}
        counts["main_display_items"]=counts["main_figures"]+counts["main_tables"]
        rules=display_limits(ctx.project)
        cap_problems=compare(counts,rules)
        req_path=ctx.project/"08_submission/submission_requirements.json"
        req_doc=load(ctx.project,"08_submission/submission_requirements.json") if req_path.is_file() else {}
        reason=str(plan.get("journal_adaptation_reason") or req_doc.get("journal_adaptation_reason") or "").strip()
        sci_plan_path=ctx.project/"01_protocol/artifact_plan.json"
        plan_is_pristine=False
        inventory_changed=False
        if sci_plan_path.is_file() and (ctx.project/plan_rel).is_file():
            plan_is_pristine=_sha256(sci_plan_path)==_sha256(ctx.project/plan_rel)
            try:
                sci_plan=load(ctx.project,"01_protocol/artifact_plan.json")
                for k in ("main_figures","main_tables","supp_figures","supp_tables"):
                    if [x.get("id") for x in sci_plan.get(k,[])]!=[x.get("id") for x in plan.get(k,[])]:
                        inventory_changed=True
            except Exception:
                pass
        has_required_cap=any(isinstance(r,dict) and r.get("status")=="required" and r.get("value") is not None for r in rules.values())
        if ctx.stage.id=="S20_journal" and plan_is_pristine and not reason:
            # S20_journal.md permits keeping 08_submission/integration/artifact_plan.json pristine
            # at S20 and applying display caps to the derived plan at S22 before Word production.
            problems=[]
        else:
            problems=list(cap_problems)
            if (inventory_changed or has_required_cap) and len(reason)<30:
                problems.append("At journal choice, justify actual retain/combine/move decisions before adapting text; keep scientific inventory unchanged")
    except (OSError,ValueError,TypeError) as exc: problems=[str(exc)]
    return Result(not problems,"journal_display_fit","; ".join(problems) or "Journal display inventory checked before production")


@check("legend_length_advice")
def legend_length_advice(ctx):
    from ..qualitylimits import check_limit
    from .artifacts import _split_blocks
    rel=ctx.spec.get("path","05_figures/legends.md")
    if not ctx.p(rel).is_file(): return Result(False,"legend_length_advice",f"missing {rel}")
    cap=check_limit(ctx)
    advisory=int(ctx.target("figure_legend_words_max",180)); long=[]
    for key,value in _split_blocks(ctx.read(rel)).items():
        count=len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b",value))
        if count>(cap or advisory): long.append(f"{key}: {count} words")
    return Result(not long,"legend_length_advice","; ".join(long) or "Legend length checked without discarding necessary decoding",
                  severity="fail" if cap is not None else "warn")

@check("display_labels_clinical")
def display_labels_clinical(ctx: Ctx) -> Result:
    kind = ctx.spec.get("kind", "all")
    from ..state import version_tuple
    pin_ver = str(ctx.state.data.get("engine_pin", ctx.state.data.get("pipeline_version", "0")))
    since_ver = ctx.spec.get("since", "1.29.0")
    if since_ver and version_tuple(pin_ver) < version_tuple(since_ver):
        return Result(True, "display_labels_clinical", "pinned historical project exempt from 1.29.0 display label check")
    if ctx.state.pin_excludes(ctx.stage.id, ctx.spec.get("since")):
        return Result(True, "display_labels_clinical", "pinned completed stage exempt from 1.29.0 display label check")
    from ..displaylabels import collect_project_issues
    layer = "journal" if ctx.stage.id.startswith(("S20_", "S21_", "S22_", "S23_", "S24_", "S25_")) else "science"
    final = bool(ctx.spec.get("final")) or ctx.stage.id in {"S23_package", "S24_package_human_review", "S25_submission_audit"}
    issues = collect_project_issues(ctx.project, kind=kind, layer=layer, final=final, only=ctx.spec.get("_only"))
    if issues:
        limit = len(issues) if ctx.spec.get("_verbose") else 6
        summary = "; ".join(f"{iss["path"]} {iss["locator"]}: {iss["message"]}" for iss in issues[:limit])
        return Result(
            False,
            "display_labels_clinical",
            summary,
            [
                "Replace raw variable names, code identifiers, boolean/numeric codes, or statistical package dump labels with self-explanatory medical terms.",
                "Ensure artifact_plan.json display_dictionary maps all contract variables and that table/figure titles describe clinical subjects, not analytics outputs.",
            ],
        )
    return Result(True, "display_labels_clinical", f"all {kind} internal labels and display text conform to medical-reader standards")
