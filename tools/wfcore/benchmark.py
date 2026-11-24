"""Source-bound project benchmarks and executor acceptance, not universal quotas."""
from __future__ import annotations

from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .packagefreeze import _safe_path, _sha256
from .readiness import atomic_json, load

SCIENCE = "01_protocol/artifact_benchmark.md"
JOURNAL = "08_submission/integration/journal_benchmark.md"
SECTIONS = ("introduction", "methods", "discussion", "supplementary")
DIMENSIONS = ("methods_logic", "literature_coverage", "display_completeness", "discussion_flow",
              "declarations", "legends_and_crossrefs", "reader_comprehension")
RETIRED_TARGETS = {"reflib_min", "reflib_max", "deepread_count", "intro_words_min", "intro_words_max",
                   "intro_refs_min", "intro_refs_max", "discussion_words_min", "discussion_words_max",
                   "discussion_refs_min", "discussion_refs_max", "main_figures_max", "main_tables_max"}


def substantive(value):
    return isinstance(value, str) and len(value.strip()) >= 20 and value.strip().casefold() not in {"todo", "pending"}


def dossier(project: Path, layer="science") -> dict:
    path = project / (SCIENCE if layer == "science" else JOURNAL)
    blocks = [json.loads(text) for text in re.findall(r"```json\s*\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)]
    selected = [row for row in blocks if isinstance(row, dict) and row.get("benchmark_version") == 1]
    if len(selected) != 1:
        raise ValueError(f"{path.name}: exactly one benchmark_version=1 object is required")
    return selected[0]


_FULLTEXT_MEM_CACHE: dict[str, str] = {}


def text_of(path: Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in {".xml", ".html", ".htm", ".pdf"}:
        raise ValueError("Comparator must be registered XML/HTML/PDF full text, not notes or an abstract")
    digest = _sha256(path)
    if digest in _FULLTEXT_MEM_CACHE:
        return _FULLTEXT_MEM_CACHE[digest]
    cache_txt_path: Path | None = None
    if suffix == ".pdf" and path.parent.name == "fulltext" and path.parent.parent.name == "06_refs":
        cache_dir = path.parent.parent / "cache"
        if cache_dir.is_dir():
            cache_txt_path = cache_dir / f"fulltext_text_{digest[:24].lower()}.txt"
            if cache_txt_path.is_file():
                cached_text = cache_txt_path.read_text(encoding="utf-8", errors="replace")
                _FULLTEXT_MEM_CACHE[digest] = cached_text
                return cached_text
    if suffix == ".xml":
        extracted = " ".join(ET.fromstring(path.read_bytes()).itertext())
    elif suffix in {".html", ".htm"}:
        class Text(HTMLParser):
            def __init__(self): super().__init__(); self.parts = []
            def handle_data(self, data): self.parts.append(data)
        parser = Text(); parser.feed(path.read_text(encoding="utf-8")); extracted = " ".join(parser.parts)
    else:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("PDF comparator needs pypdf in the verified venv, or a registered XML/HTML full text; never substitute an abstract") from exc
        extracted = " ".join(page.extract_text() or "" for page in PdfReader(path).pages)
    _FULLTEXT_MEM_CACHE[digest] = extracted
    if cache_txt_path is not None:
        try:
            tmp = cache_txt_path.with_suffix(".txt.tmp")
            tmp.write_text(extracted, encoding="utf-8")
            tmp.replace(cache_txt_path)
        except OSError:
            pass
    return extracted


def _norm(text): return re.sub(r"\s+", " ", text).strip().casefold()


def protected_plan(doc):
    """Fix prewriting rationale/ranges; later evidence mappings may be completed without a reset."""
    adaptation = doc.get("adaptation", {})
    references = adaptation.get("references", {})
    return {"comparators": [{k: row.get(k) for k in ("citekey", "fulltext", "sha256", "relevance", "observations", "evidence")} for row in doc.get("comparators", [])],
            "structure": adaptation.get("structure"), "displays": adaptation.get("displays"),
            "references": {"ranges": references.get("ranges"), "basis": references.get("basis"),
                           "roles": [{k: row.get(k) for k in ("id", "section", "claim", "source_type", "required")} for row in references.get("roles", [])]}}


def plan_hash(doc): return hashlib.sha256(json.dumps(protected_plan(doc), sort_keys=True).encode()).hexdigest()


def verify_benchmark(project: Path, layer="science", *, require_lock=True) -> list[str]:
    from pubmed.identity import errors
    from .refproof import validate_local_proof
    doc = dossier(project, layer); problems = []
    if layer == "science":
        ok, defects, _ = validate_local_proof(project)
        if not ok: return ["Benchmark reference identity: " + "; ".join(defects[:3])]
    entries = {e["citekey"]: e for e in load(project, "06_refs/library.json").get("entries", [])}
    records = {r["citekey"]: r for r in load(project, "06_refs/fulltext/retrieval_manifest.json").get("retrievals", [])}
    rows = doc.get("comparators", [])
    if len(rows) < 2 or len({row.get("citekey") for row in rows}) != len(rows):
        problems.append("Use multiple distinct close full-text comparators; duplicated records are not independent examples")
    if not substantive(doc.get("adequacy_rationale")): problems.append("Explain comparator fit and evidence/access limitations")
    for row in rows:
        key = row.get("citekey"); entry = entries.get(key); record = records.get(key, {})
        if not entry and layer == "journal":
            from pubmed.eutils import parse_pubmed_xml
            rel, metadata = _safe_path(project, record.get("metadata_cache", ""))
            if (not re.fullmatch(r"06_refs/cache/benchmark_efetch_pubmed_[A-Za-z0-9_.-]+\.xml", rel) or
                    not metadata.is_file() or str(record.get("metadata_sha256", "")).upper() != _sha256(metadata)):
                problems.append(f"{key}: comparator-only fresh PubMed payload missing/changed"); continue
            entry = next((e for e in parse_pubmed_xml(metadata.read_text(encoding="utf-8")) if e["pmid"] == record.get("pmid")), None)
        if entry and layer == "journal" and key in entries:
            ok, defects, _ = validate_local_proof(project, required_keys={key})
            if not ok: problems.append(f"{key}: formal reference proof invalid: " + "; ".join(defects[:2]))
        if not entry: problems.append(f"{key}: absent from genuine PubMed source records"); continue
        if any("RETRACT" in flag or "CONCERN" in flag for flag in entry.get("flags", [])):
            problems.append(f"{key}: retracted/concern-flagged paper is not a credible comparator")
        rel, path = _safe_path(project, row.get("fulltext", ""))
        if (not rel.startswith("06_refs/fulltext/") or not path.is_file() or record.get("fulltext") != rel or
                record.get("access") not in {"oa", "authorized"} or record.get("sha256", "").upper() != _sha256(path) or
                str(row.get("sha256", "")).upper() != _sha256(path)):
            problems.append(f"{key}: full-text retrieval/hash/access evidence missing or changed"); continue
        problems.extend(f"{key}: {error}" for error in errors(entry, path, record))
        relevance = row.get("relevance", {})
        for field in ("topic", "design", "analysis"):
            if not substantive(relevance.get(field)): problems.append(f"{key}: concrete {field} comparability needed")
        if layer == "journal":
            target = load(project, "08_submission/target_journal.json")
            same_issn = target.get("issn") and str(target["issn"]) in str(entry.get("issn", ""))
            if not same_issn and _norm(entry.get("journal", "")) != _norm(target.get("journal", "")):
                problems.append(f"{key}: comparator is not from the selected journal")
        observations = row.get("observations", {})
        for field in ("methods_outline", "discussion_structure", "reference_roles", "display_roles"):
            if not substantive(observations.get(field)): problems.append(f"{key}: substantive observations.{field} needed")
        for field in ("main_figures", "main_tables", "supp_figures", "supp_tables"):
            if type(observations.get(field)) is not int or observations[field] < 0: problems.append(f"{key}: observed {field} count needed")
        citations = observations.get("citations", {})
        if any(type(citations.get(section)) is not int or citations[section] < 0 for section in SECTIONS):
            problems.append(f"{key}: separate observed section/supplement citation counts needed")
        if "section_words" in observations and observations["section_words"] is not None:
            sw = observations["section_words"]
            if not isinstance(sw, dict) or any(type(v) is not int or v < 0 for v in sw.values()):
                problems.append(f"{key}: observations.section_words must map section names to nonnegative integers")
        excerpts = row.get("evidence", [])
        if not {"methods", "discussion", "display"}.issubset({e.get("kind") for e in excerpts}):
            problems.append(f"{key}: methods/discussion/display full-text locators needed")
        actual = _norm(text_of(path))
        for evidence in excerpts:
            if not evidence.get("locator") or not substantive(evidence.get("quote")) or _norm(evidence["quote"]) not in actual:
                problems.append(f"{key}: excerpt not found in registered full text; never backfill quotations")
    adaptation = doc.get("adaptation", {}); structure = adaptation.get("structure", {})
    for field in ("methods", "discussion", "main_vs_supplement", "declarations"):
        if not substantive(structure.get(field)): problems.append(f"project structure.{field}: explain actual adaptation")
    refs = adaptation.get("references", {})
    if not substantive(refs.get("basis")): problems.append("Project reference range needs comparator/project basis, not a green-gate target")
    for section in (*SECTIONS, "library", "main_total"):
        value = refs.get("ranges", {}).get(section)
        if not isinstance(value, list) or len(value) != 2 or any(type(v) is not int or v < 0 for v in value) or value[0] > value[1]:
            problems.append(f"{section}: evidence-based expected range required (advisory, not a quota)")
    roles = refs.get("roles", [])
    if not roles or len({r.get("id") for r in roles}) != len(roles): problems.append("Unique project-specific literature argument roles required")
    for role in roles:
        if not role.get("id") or role.get("section") not in SECTIONS or type(role.get("required")) is not bool or not substantive(role.get("claim")) or not role.get("source_type"):
            problems.append("Invalid literature argument role")
    displays = adaptation.get("displays", {})
    for field in ("inventory_rationale", "essential_questions", "omissions"):
        if not substantive(displays.get(field)): problems.append(f"Display adaptation.{field} needs a study-specific account")
    if layer == "journal":
        expected = {rel: _sha256(project / rel) for rel in ("08_submission/target_journal.json", "08_submission/submission_requirements.json")}
        if doc.get("target_hashes") != expected: problems.append("Journal benchmark does not match selected journal/article-type requirements")
    if require_lock:
        lock = load(project, f".wf/benchmark_{layer}_lock.json")
        if lock.get("plan_hash") != plan_hash(doc): problems.append("Prewriting benchmark plan changed: do not lower ranges/reset evidence to pass; use scoped, justified replan")
    return problems


def seal(project: Path, layer="science"):
    from .state import State
    from .revision import permits, guard_outputs
    owner = "S07_artifacts" if layer == "science" else "S20_journal"
    state = State(project).load()
    if state.current != owner and not permits(project, owner): raise ValueError(f"Benchmark plan belongs to {owner}; no late untracked reset")
    problems = verify_benchmark(project, layer, require_lock=False)
    if layer == "science" and not state.pin_excludes(owner,"1.22.0"):
        from .state import version_tuple
        if version_tuple(str(state.data.get("pipeline_version","0"))) >= (1,22,0):
            from .displayquality import story_problems
            problems += story_problems(load(project,"01_protocol/artifact_plan.json"),dossier(project))
    if problems: raise ValueError("; ".join(problems[:8]))
    path = project / f".wf/benchmark_{layer}_lock.json"; doc = dossier(project, layer)
    if path.is_file() and load(project, path.relative_to(project).as_posix()).get("plan_hash") != plan_hash(doc):
        revision = __import__("wfcore.revision", fromlist=["active"]).active(project)
        if not revision or revision.get("status") != "active": raise ValueError("Changed sealed plan requires an explicit scoped feedback replan, never a pass-seeking reset")
    guard_outputs(project, [path]); atomic_json(path, {"plan_hash": plan_hash(doc), "owner": owner})


WORD_SECTIONS = ("introduction", "methods", "results", "discussion")
_SECTION_BOUNDARY_RE = re.compile(
    r"(?:^|\n|\s{2,})(?:\d+(?:\.\d+)*\.?\s+)?"
    r"(introduction|background|aims?|objectives?|"
    r"(?:materials?\s+and\s+|patients?\s+and\s+|statistical\s+)?methods?|"
    r"ethics\s+approval|results?|discussion|conclusions?|"
    r"references|declarations(?:\s+and\s+statements)?|acknowledg(?:e)?ments?|funding|supplementary\s+information)"
    r"(?:\s*[:.\n]|\s{2,})",
    re.I,
)


def extract_section_words(raw_text: str) -> dict[str, int]:
    """Estimate IMRAD section word counts from a registered comparator full text."""
    if not raw_text or not raw_text.strip():
        return {}
    canonical_map = {
        "introduction": "introduction",
        "background": "introduction",
        "aim": "introduction",
        "aims": "introduction",
        "objective": "introduction",
        "objectives": "introduction",
        "method": "methods",
        "methods": "methods",
        "materials and methods": "methods",
        "material and methods": "methods",
        "patients and methods": "methods",
        "patient and methods": "methods",
        "statistical methods": "methods",
        "ethics approval": "methods",
        "result": "results",
        "results": "results",
        "discussion": "discussion",
        "conclusion": "discussion",
        "conclusions": "discussion",
        "references": "_stop",
        "declarations": "_stop",
        "declarations and statements": "_stop",
        "acknowledgments": "_stop",
        "acknowledgements": "_stop",
        "funding": "_stop",
        "supplementary information": "_stop",
    }
    hits: list[tuple[int, int, str]] = []
    for m in _SECTION_BOUNDARY_RE.finditer(raw_text):
        norm_key = re.sub(r"\s+", " ", m.group(1).strip().casefold())
        mapped = canonical_map.get(norm_key)
        if mapped:
            hits.append((m.start(), m.end(), mapped))
    if not hits:
        return {}
    # Find the main IMRAD sequence (prefer the last 'introduction' that precedes 'methods'/'results').
    intro_candidates = [i for i, (_, _, role) in enumerate(hits) if role == "introduction"]
    start_idx = 0
    for idx in intro_candidates:
        later_roles = {role for _, _, role in hits[idx + 1:]}
        if {"methods", "results"} & later_roles:
            start_idx = idx
            break
    counts = {sec: 0 for sec in WORD_SECTIONS}
    for i in range(start_idx, len(hits)):
        _, body_start, role = hits[i]
        if role == "_stop":
            break
        body_end = hits[i + 1][0] if i + 1 < len(hits) else len(raw_text)
        chunk = raw_text[body_start:body_end]
        counts[role] += len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", chunk))
    return {k: v for k, v in counts.items() if v > 0}


def comparator_section_baselines(project: Path, layer: str = "science") -> dict:
    """Summarize comparator section word counts & Introduction citation medians."""
    import statistics
    doc = None
    try:
        doc = dossier(project, layer)
    except (OSError, ValueError, json.JSONDecodeError):
        json_rel = "01_protocol/artifact_benchmark.json" if layer == "science" else "08_submission/integration/artifact_benchmark.json"
        if (project / json_rel).is_file():
            try:
                doc = load(project, json_rel)
            except (OSError, ValueError, json.JSONDecodeError):
                doc = None
    if not isinstance(doc, dict):
        return {"layer": layer, "n_comparators": 0, "sections": {}, "intro_share_median": None, "intro_citations_median": None}

    per_sec: dict[str, list[int]] = {s: [] for s in WORD_SECTIONS}
    intro_shares: list[float] = []
    intro_cites: list[int] = []
    rows = doc.get("comparators", [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        obs = row.get("observations", {}) or {}
        cites = obs.get("citations", {}) or {}
        if isinstance(cites.get("introduction"), int) and cites["introduction"] > 0:
            intro_cites.append(cites["introduction"])
        sw = obs.get("section_words")
        if not isinstance(sw, dict) or not any(isinstance(v, int) and v > 0 for v in sw.values()):
            ft_rel = row.get("fulltext", "")
            if ft_rel:
                try:
                    _, ft_path = _safe_path(project, ft_rel)
                    if ft_path.is_file():
                        sw = extract_section_words(text_of(ft_path))
                except (OSError, ValueError):
                    sw = {}
        if isinstance(sw, dict):
            row_vals: dict[str, int] = {}
            for s in WORD_SECTIONS:
                val = sw.get(s)
                if isinstance(val, int) and val > 0:
                    per_sec[s].append(val)
                    row_vals[s] = val
            # Merge optional 'aim' into introduction share when recorded separately.
            aim_val = sw.get("aim") if isinstance(sw.get("aim"), int) and sw.get("aim") > 0 else 0
            if aim_val and "introduction" in row_vals:
                per_sec["introduction"][-1] = row_vals["introduction"] + aim_val
                row_vals["introduction"] += aim_val
            total_row = sum(row_vals.values())
            if total_row > 0 and "introduction" in row_vals and len(row_vals) >= 3:
                intro_shares.append(row_vals["introduction"] / total_row)

    summary = {}
    for s, vals in per_sec.items():
        if vals:
            summary[s] = {
                "n": len(vals),
                "min": min(vals),
                "median": round(statistics.median(vals)),
                "max": max(vals),
            }
    return {
        "layer": layer,
        "n_comparators": len(rows),
        "sections": summary,
        "intro_share_median": round(statistics.median(intro_shares), 4) if intro_shares else None,
        "intro_citations_median": round(statistics.median(intro_cites)) if intro_cites else None,
    }


def citation_metrics(project):
    from .checks.refs import citekeys
    metrics = {}; union = set()
    for section in SECTIONS:
        rel = "07_manuscript/" + ("supplementary_methods" if section == "supplementary" else section) + ".md"
        path = project / rel; keys = set(citekeys(path.read_text(encoding="utf-8"))) if path.is_file() else set()
        metrics[section] = len(keys)
        if section != "supplementary": union.update(keys)
    # Results/abstract may also contain legitimate citations; they belong to main_total.
    for name in ("results", "abstract"):
        path = project / f"07_manuscript/{name}.md"
        if path.is_file(): union.update(citekeys(path.read_text(encoding="utf-8")))
    assembled = project / "07_manuscript/full_manuscript.md"
    if assembled.is_file(): union = set(citekeys(assembled.read_text(encoding="utf-8")))
    metrics["main_total"] = len(union); metrics["library"] = len(load(project, "06_refs/library.json").get("entries", []))
    return metrics


def coverage(project: Path, section=None, *, library_only=False, layer="science") -> list[str]:
    from .checks.refs import citekeys
    refs = dossier(project, layer)["adaptation"]["references"]
    keys = {e["citekey"] for e in load(project, "06_refs/library.json").get("entries", [])}; problems = []
    for role in refs["roles"]:
        if section and role["section"] != section: continue
        chosen = role.get("citekeys", [])
        if role["required"] and not chosen: problems.append(f"{role['id']}: missing literature basis for {role['claim']}")
        if any(key not in keys for key in chosen): problems.append(f"{role['id']}: selected source absent from library")
        if library_only or not chosen: continue
        name = "supplementary_methods" if role["section"] == "supplementary" else role["section"]
        rel = f"07_manuscript/{name}.md" if layer == "science" else "08_submission/integration/" + ("supplementary_methods.md" if name == "supplementary_methods" else "full_manuscript.md")
        path = project / rel
        if not path.is_file():
            problems.append(f"{role['id']}: target manuscript file {rel} missing")
            continue
        sec_text = path.read_text(encoding="utf-8")
        passage = str(role.get("passage", "") or "").strip()
        if passage and passage in sec_text and set(chosen).issubset(set(citekeys(passage))):
            continue
        # Direct verification without forcing reverse copy-paste of edited prose into benchmark JSON:
        actual_keys = set(citekeys(sec_text))
        if not set(chosen).issubset(actual_keys) or not substantive(sec_text):
            problems.append(f"{role['id']}: section {rel} does not cite its declared supporting sources {chosen}")
    return problems


def display_fit(project: Path, layer="science"):
    plan_rel = "01_protocol/artifact_plan.json" if layer == "science" else "08_submission/integration/artifact_plan.json"
    plan = load(project, plan_rel); problems = []; purposes = {}
    from .clinicalpresentation import verify_plan
    problems.extend(verify_plan(project,layer=="journal"))
    for group in ("main_figures", "main_tables", "supp_figures", "supp_tables"):
        for entry in plan.get(group, []):
            key = entry["id"]; contract = entry.get("reader_contract", {})
            for field in ("question", "placement_reason", "nonredundancy", "misinterpretation_risk"):
                if not substantive(contract.get(field)): problems.append(f"{key}: specific reader_contract.{field} needed")
            purpose = _norm(str(contract.get("question", "")) + " " + str(contract.get("placement_reason", "")))
            if purpose in purposes: problems.append(f"{key} and {purposes[purpose]} reuse the same purpose/placement; explain their actual distinct contribution")
            purposes[purpose] = key
    return problems


def acceptance_rel(layer, final=False):
    suffix = "science" if layer == "science" else "journal_final" if final else "journal_pre"
    return f".wf/executor_acceptance_{suffix}.json"


def contract_hash(entry):
    return hashlib.sha256(json.dumps(entry.get("reader_contract", {}), sort_keys=True).encode()).hexdigest()


def display_source(project, entry, layer, final):
    candidates = [entry.get("file")]
    if layer == "journal" and not final:
        candidates = [entry.get("preview"), entry.get("source_file"), entry.get("file")]
    for rel in candidates:
        if rel and _safe_path(project, rel)[1].is_file(): return rel
    raise ValueError(f"{entry['id']}: actual render or explicit preproduction preview/source_file required; no guessed role source")


def acceptance_inputs(project, layer="science", *, final=False, report=None):
    from .readiness import reader_inputs
    if layer == "science": files = set(reader_inputs(project)) | {SCIENCE}
    else:
        files = {JOURNAL, "08_submission/target_journal.json", "08_submission/submission_requirements.json"}
        files.update(p.relative_to(project).as_posix() for p in (project / "08_submission/integration").glob("*.md"))
        files.add("08_submission/integration/artifact_plan.json")
        for group in ("main_figures", "main_tables", "supp_figures", "supp_tables"):
            for entry in load(project, "08_submission/integration/artifact_plan.json").get(group, []):
                files.add(display_source(project, entry, layer, final))
        if final:
            manifest = load(project, "08_submission/bundle/manifest.json")
            files.add("08_submission/bundle/manifest.json"); files.update(item["file"] for item in manifest["items"])
    files.update({"06_refs/library.json", "06_refs/refs.bib"})
    files.update(row["fulltext"] for row in dossier(project, layer)["comparators"])
    result={rel: _sha256(_safe_path(project, rel)[1]) for rel in sorted(files)}
    if report is None and (project/acceptance_rel(layer,final)).is_file():
        report=load(project,acceptance_rel(layer,final))
    if report and final:
        from .medicalstyle import layout_inputs
        result.update(layout_inputs(project,report))
    return result


def verify_acceptance(project, layer="science", *, final=False, report=None):
    report = load(project, acceptance_rel(layer, final)) if report is None else report
    problems = []
    problems.extend(coverage(project, layer=layer))
    problems.extend(display_fit(project, layer))
    expected = acceptance_inputs(project, layer, final=final,report=report)
    if report.get("inputs") != expected or report.get("final_outputs") is not final: problems.append("Executor acceptance is missing/stale for actual current outputs")
    if not substantive(report.get("reviewer")): problems.append("Identify actual executor review; do not claim a human or independent reviewer")
    for dimension in DIMENSIONS:
        row = report.get("findings", {}).get(dimension, {})
        if row.get("verdict") != "PASS" or not substantive(row.get("observation")): problems.append(f"Executor must resolve and describe {dimension}, not merely label PASS")
    if report.get("unresolved") != []: problems.append("Unresolved routine defects prevent delivery")
    plan = load(project, "01_protocol/artifact_plan.json" if layer == "science" else "08_submission/integration/artifact_plan.json")
    if layer == "journal":
        from .journalrules import display_limits, compare
        counts = {group: len(plan.get(group, [])) for group in ("main_figures", "main_tables", "supp_figures", "supp_tables")}
        counts["main_display_items"] = counts["main_figures"] + counts["main_tables"]
        problems.extend(compare(counts, display_limits(project)))
    if load(project, f".wf/benchmark_{layer}_lock.json").get("plan_hash") != plan_hash(dossier(project, layer)):
        problems.append("Sealed project benchmark changed; acceptance cannot bless an untracked replan")
    displays = [entry for group in ("main_figures", "main_tables", "supp_figures", "supp_tables") for entry in plan.get(group, [])]
    findings = report.get("display_findings", {}); unique = set()
    if set(findings) != {entry["id"] for entry in displays}: problems.append("Executor findings must cover each actual figure/table once")
    for entry in displays:
        row = findings.get(entry["id"], {})
        if row.get("reviewed_file") != display_source(project, entry, layer, final):
            problems.append(f"{entry['id']}: finding must identify the actual inspected display file")
        if row.get("contract_hash") != contract_hash(entry): problems.append(f"{entry['id']}: reader finding does not bind its current specific contract")
        observation = row.get("observation", "")
        if not substantive(observation) or _norm(observation) in unique: problems.append(f"{entry['id']}: concrete non-copied rendered-display observation required")
        unique.add(_norm(observation))
    deviations = report.get("range_deviations", {})
    if layer == "science":
        metrics = citation_metrics(project); ranges = dossier(project)["adaptation"]["references"]["ranges"]
        for key, actual in metrics.items():
            if not ranges[key][0] <= actual <= ranges[key][1] and not substantive(deviations.get(key)):
                problems.append(f"{key} observed {actual}, benchmark range {ranges[key]}: justify coverage, never pad or lower the locked range")
    from .medicalstyle import verify as verify_medical_style
    problems.extend(verify_medical_style(project,report,layer,final))
    return problems
