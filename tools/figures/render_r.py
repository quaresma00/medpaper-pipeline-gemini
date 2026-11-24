#!/usr/bin/env python3
"""Run one declared R figure in staging, inspect real output, then publish atomically."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from figures.r_audit import audit_svg
from wfcore.packagefreeze import _safe_path, _sha256
from wfcore.readiness import atomic_json
from wfcore.revision import guard_outputs, record_build, permits
from wfcore.dependencies import guard_build
from wfcore.state import State
import hashlib


def _sha256_json(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def render(project, figure_id, timeout=180):
    from wfcore.figurejobs import job
    with job(project.resolve(),figure_id,"R render"):
        return _render(project,figure_id,timeout)


def _render(project, figure_id, timeout=180):
    project = project.resolve()
    guard_build(project)
    state = State(project).load()
    journal_mode=state.current in {"S23_package","S24_package_human_review"} or permits(project,"S23_package")
    if journal_mode:
        from wfcore.journalcontext import guard
        guard(project)
    if state.current != "S11_figures" and not permits(project, "S11_figures") and not journal_mode:
        raise ValueError("Publication R figures run at S11 or an explicitly scoped S11 revision")
    plan_path = project / ("08_submission/integration/artifact_plan.json" if journal_mode else "01_protocol/artifact_plan.json")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    matches = [e for g in ("main_figures", "supp_figures") for e in plan.get(g, []) if e.get("id") == figure_id]
    if len(matches) != 1:
        raise ValueError("Figure must occur exactly once in the artifact plan")
    entry = matches[0]
    script_rel, script = _safe_path(project, entry["script"])
    if journal_mode and not script_rel.startswith("08_submission/integration/"):
        raise ValueError("Journal rendering needs a derived R script; never redraw the frozen scientific original")
    if script.suffix.casefold() != ".r" or not script.is_file():
        raise ValueError("The declared R plotting script is missing or has no .R extension")
    sources = {r: _safe_path(project, r)[1] for r in entry.get("source_results", [])}
    if not sources or any(not r.startswith("03_analysis/results/") or not p.is_file() for r, p in sources.items()):
        raise ValueError("Declare every actual executed result JSON input")
    rscript = shutil.which("Rscript")
    if not rscript:
        raise ValueError("Rscript is unavailable; restore R, do not silently substitute Python")
    png_rel, png = _safe_path(project, entry["file"])
    pdf_rel, pdf = _safe_path(project, entry.get("pdf", ""))
    if png.suffix.lower() != ".png" or pdf.suffix.lower() != ".pdf":
        raise ValueError("R publication entries must declare PNG and vector PDF")
    qc = project / ("08_submission/integration/figure_qc" if journal_mode else "05_figures/qc")
    extra = {".svg": qc / (png.stem + ".render.svg"), ".rmeta.json": qc / (png.stem + ".rmeta.json")}
    sidecar = qc / (png.stem + ".artist.json")
    destinations = {".png": png, ".pdf": pdf, **extra}
    if entry.get("tiff"):
        destinations[".tiff"] = _safe_path(project, entry["tiff"])[1]
    if journal_mode and any(not p.relative_to(project).as_posix().startswith("08_submission/") for p in destinations.values()):
        raise ValueError("Journal rendering may not overwrite frozen scientific figures")
    guard_outputs(project, list(destinations.values()) + [sidecar])
    helper = ROOT / "tools/figures/r_style.R"
    recipes = ROOT / "tools/figures/r_recipes.R"
    from wfcore.journalspec import load
    profile = load(project)
    from wfcore.clinicalpresentation import profile as production_profile,vocabulary
    production=production_profile(project,journal_mode)
    labels={}
    for row in vocabulary(project,journal_mode):
        labels[row["key"]]=row["label"]
    internal={}
    for row in vocabulary(project,journal_mode): internal.setdefault(row["internal"],set()).add(row["label"])
    labels.update({key:next(iter(values)) for key,values in internal.items() if len(values)==1})
    policy = {**production,"labels":labels,"spelling": profile.get("spelling") or State(project).config().get("targets", {}).get("spelling", ""), "number_format": profile.get("number_format") or production.get("number_format", {})}
    policy_sha = _sha256_json(policy)
    policy_files = [path for path in (project/"08_submission/target_journal.json", project/".wf/config.toml") if path.is_file()]
    from analysis.reproduce import renv_context
    context = renv_context(project)
    environment_files = [Path(context[key]) for key in ("activation", "lockfile") if context.get(key)]
    before = {str(p): _sha256(p) for p in [script, helper, recipes, plan_path, *sources.values(), *policy_files, *environment_files]}
    (project / "temp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="r-figure-", dir=project / "temp") as temporary:
        stem = Path(temporary) / png.stem
        env = {**os.environ, "MEDPAPER_ROOT": str(ROOT), "MEDPAPER_PROJECT": str(project),
               "MEDPAPER_RENDER_STEM": str(stem), "MEDPAPER_FIGURE_SCRIPT": str(script),
               "MEDPAPER_SOURCE_RESULTS": json.dumps(list(sources)), "MEDPAPER_LABEL_POLICY": json.dumps(policy),
               "MEDPAPER_RENV_CONTEXT": json.dumps(context), "MEDPAPER_RENV_ACTIVATE": context.get("activation", "")}
        if context["active"]:
            env["RENV_PROJECT"] = context["project"]
        else:
            env.pop("RENV_PROJECT", None)
        if os.name == "nt":
            env.update({"LC_ALL": "C", "LANG": "C"})
        expression = ("local({ a <- Sys.getenv('MEDPAPER_RENV_ACTIVATE'); "
                      "if(nzchar(a)) source(a, local=.GlobalEnv); options(warn=2); "
                      "sys.source(Sys.getenv('MEDPAPER_FIGURE_SCRIPT'), envir=.GlobalEnv) })")
        from wfcore.execution import run_logged
        process = run_logged([rscript,"--vanilla","--encoding=UTF-8","-e",expression],
                             project=project,cwd=ROOT,env=env,timeout=timeout)
        if process.returncode:
            raise ValueError("R render failed; prior output preserved: " + (process.stderr or process.stdout)[-2400:])
        if any(not Path(str(stem) + suffix).is_file() for suffix in destinations):
            raise ValueError("R helper did not produce every declared output; prior output preserved")
        metadata = json.loads(Path(str(stem) + ".rmeta.json").read_text(encoding="utf-8"))
        if metadata.get("width_class") != entry.get("width"):
            raise ValueError("R physical width differs from the artifact plan")
        report = audit_svg(Path(str(stem) + ".svg"), metadata)
        if context != renv_context(project) or any(not Path(p).is_file() or _sha256(Path(p)) != h for p, h in before.items()):
            raise ValueError("Source changed during rendering; prior output preserved")
        for suffix, destination in destinations.items():
            from wfcore.determinism import normalize
            if suffix in {".pdf", ".tiff"}: normalize(Path(str(stem) + suffix))
            destination.parent.mkdir(parents=True, exist_ok=True)
            Path(str(stem) + suffix).replace(destination)
        report["width_class"] = metadata.get("width_class")
        report["source_hashes"] = {r: before[str(p)] for r, p in sources.items()}
        report["script"] = script_rel
        report["script_sha256"] = before[str(script)]
        report["helper_sha256"] = before[str(helper)]
        report["recipes_sha256"] = before[str(recipes)]
        report["policy_sha256"] = policy_sha
        report["renv"] = context
        report["render_hashes"] = {p.relative_to(project).as_posix(): _sha256(p) for p in destinations.values()}
        atomic_json(sidecar, report)
        for output in [*destinations.values(), sidecar]:
            record_build(project, output, [script, helper, recipes, plan_path, *sources.values(), *policy_files, *environment_files,
                                          ROOT/"tools/wfcore/clinicalpresentation.py", ROOT/"tools/wfcore/determinism.py"], parameters={"label_policy":policy,"renv":context})
    return {"figure": figure_id, "engine": "R", "png": str(png), "pdf": str(pdf), "audit": str(sidecar)}


def is_up_to_date(project: Path, figure_id: str) -> bool:
    """Return True only when script, helpers, sources, policy, renv, and every rendered output match."""
    project = project.resolve()
    state = State(project).load()
    journal_mode = state.current in {"S23_package", "S24_package_human_review"} or permits(project, "S23_package")
    plan_path = project / ("08_submission/integration/artifact_plan.json" if journal_mode else "01_protocol/artifact_plan.json")
    if not plan_path.is_file():
        return False
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    matches = [e for g in ("main_figures", "supp_figures") for e in plan.get(g, []) if e.get("id") == figure_id]
    if len(matches) != 1:
        return False
    entry = matches[0]
    try:
        script_rel, script = _safe_path(project, entry.get("script", ""))
        png_rel, png = _safe_path(project, entry.get("file", ""))
        _, pdf = _safe_path(project, entry.get("pdf", ""))
    except (OSError, ValueError):
        return False
    if not script.is_file() or not png.is_file() or not pdf.is_file():
        return False
    qc_dir = project / ("08_submission/integration/figure_qc" if journal_mode else "05_figures/qc")
    sidecar = qc_dir / (png.stem + ".artist.json")
    if not sidecar.is_file():
        return False
    try:
        art = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if art.get("width_class") != entry.get("width") or art.get("script") != script_rel:
        return False
    if art.get("script_sha256") != _sha256(script):
        return False
    helper = ROOT / "tools/figures/r_style.R"
    recipes = ROOT / "tools/figures/r_recipes.R"
    if art.get("helper_sha256") != _sha256(helper) or art.get("recipes_sha256") != _sha256(recipes):
        return False
    declared_sources = entry.get("source_results", [])
    if set(art.get("source_hashes", {})) != set(declared_sources):
        return False
    for r in declared_sources:
        _, sp = _safe_path(project, r)
        if not sp.is_file() or art["source_hashes"].get(r) != _sha256(sp):
            return False
    from wfcore.journalspec import load as load_jspec
    from wfcore.clinicalpresentation import profile as production_profile, vocabulary
    profile = load_jspec(project)
    production = production_profile(project, journal_mode)
    labels = {row["key"]: row["label"] for row in vocabulary(project, journal_mode)}
    internal: dict[str, set[str]] = {}
    for row in vocabulary(project, journal_mode):
        internal.setdefault(row["internal"], set()).add(row["label"])
    labels.update({key: next(iter(vals)) for key, vals in internal.items() if len(vals) == 1})
    policy = {
        **production,
        "labels": labels,
        "spelling": profile.get("spelling") or state.config().get("targets", {}).get("spelling", ""),
        "number_format": profile.get("number_format") or production.get("number_format", {}),
    }
    if art.get("policy_sha256") != _sha256_json(policy):
        return False
    from analysis.reproduce import renv_context
    if art.get("renv") != renv_context(project):
        return False
    rhashes = art.get("render_hashes", {})
    if not rhashes or png_rel not in rhashes:
        return False
    for rel, expected in rhashes.items():
        _, out_p = _safe_path(project, rel)
        if not out_p.is_file() or _sha256(out_p) != expected:
            return False
    return True


def render_many(
    project: Path,
    figure_ids: list[str] | None = None,
    *,
    only_changed: bool = False,
    timeout: int = 180,
    jobs: int | None = None,
) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    project = project.resolve()
    state = State(project).load()
    journal_mode = state.current in {"S23_package", "S24_package_human_review"} or permits(project, "S23_package")
    plan_path = project / ("08_submission/integration/artifact_plan.json" if journal_mode else "01_protocol/artifact_plan.json")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if figure_ids:
        targets = list(figure_ids)
    else:
        targets = [
            str(e["id"])
            for g in ("main_figures", "supp_figures")
            for e in plan.get(g, [])
            if str(e.get("renderer", "R")).upper() == "R" and e.get("id")
        ]
    if not targets:
        raise ValueError("No R figures declared in artifact_plan.json")
    results_by_idx: dict[int, dict] = {}
    pending: list[tuple[int, str]] = []
    total = len(targets)
    for idx, fid in enumerate(targets, 1):
        if only_changed and is_up_to_date(project, fid):
            print(f"[R render {idx}/{total}] {fid} [SKIP unchanged]", flush=True)
            results_by_idx[idx] = {"figure": fid, "engine": "R", "skipped": True}
        else:
            pending.append((idx, fid))

    max_workers = max(1, int(jobs if jobs is not None else min(4, os.cpu_count() or 2)))
    if len(pending) <= 1 or max_workers == 1:
        for idx, fid in pending:
            print(f"[R render {idx}/{total}] {fid} ...", flush=True)
            results_by_idx[idx] = render(project, fid, timeout)
    else:
        workers = min(max_workers, len(pending))
        print(f"[R render] Rendering {len(pending)} figure(s) across {workers} parallel Rscript workers...", flush=True)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fut_map = {pool.submit(render, project, fid, timeout): (idx, fid) for idx, fid in pending}
            for fut in as_completed(fut_map):
                idx, fid = fut_map[fut]
                res = fut.result()
                print(f"[R render {idx}/{total}] {fid} [DONE]", flush=True)
                results_by_idx[idx] = res
    return [results_by_idx[idx] for idx in range(1, total + 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figure", action="append", default=[], help="figure id to render (repeatable)")
    parser.add_argument("--all", action="store_true", help="render all declared R figures")
    parser.add_argument("--changed", action="store_true", help="skip figures whose script, data, policy, and outputs are unchanged")
    parser.add_argument("--jobs", type=int, default=None, help="parallel Rscript worker count for multi-figure renders")
    parser.add_argument("--project", type=Path, default=ROOT / "project")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not args.all and not args.figure:
        parser.error("pass --figure <ID> or --all")
    try:
        if not args.all and not args.changed and len(args.figure) == 1:
            print(json.dumps(render(args.project, args.figure[0], args.timeout), ensure_ascii=False))
        else:
            results = render_many(
                args.project,
                figure_ids=args.figure if args.figure else None,
                only_changed=args.changed,
                timeout=args.timeout,
                jobs=args.jobs,
            )
            print(json.dumps({"figures": results}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"R figure: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
