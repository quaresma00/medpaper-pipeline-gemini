"""Bootstrap study_facts.json and scaffold unambiguous table/prose claim_bindings.json.

Safety principles:
1. Never fabricates numbers, clinical populations, endpoints, models, or executor read-back prose.
2. Missing context fields in bootstrapped study_facts.json are explicitly marked
   "PENDING_CLINICAL_CONTEXT" so the S06 gate blocks until genuine clinical context is supplied.
3. Ambiguous multi-fact matches in tables or prose are never guessed; they emit
   fact_ids=["AMBIGUOUS_SELECT_ONE"] with _candidates for explicit verification.
"""
from __future__ import annotations

import copy
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from pathlib import Path

from . import claims, xlsxlite
from .checks.numbers import NUM_RE, _norm, _offenders, _scrub
from .clinicalpresentation import label as clinical_label
from .readiness import atomic_json
from .revision import guard_outputs

PENDING_CTX = "PENDING_CLINICAL_CONTEXT"
AMBIGUOUS_SENTINEL = "AMBIGUOUS_SELECT_ONE"
REQUIRED_CTX_ORDER = ("outcome", "population", "comparison", "model", "timepoint", "unit", "denominator")
PCT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%")


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return cleaned or "item"


def _is_scalar_number(val: object) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _discover_result_nodes(obj: object, pointer: str = "") -> list[tuple[str, dict, dict]]:
    """Yield (json_pointer, raw_context_dict, numeric_values_dict) from a result JSON."""
    found: list[tuple[str, dict, dict]] = []
    if not isinstance(obj, dict):
        return found

    vals = obj.get("values")
    if isinstance(vals, dict) and any(_is_scalar_number(v) for v in vals.values()):
        ctx = obj.get("context") if isinstance(obj.get("context"), dict) else {}
        num_vals = {k: v for k, v in vals.items() if _is_scalar_number(v)}
        found.append((pointer or "/", ctx, num_vals))
        return found

    direct_nums = {
        k: v for k, v in obj.items()
        if k != "environment" and _is_scalar_number(v)
    }
    child_dicts = {
        k: v for k, v in obj.items()
        if k != "environment" and isinstance(v, dict)
    }
    if direct_nums and not child_dicts:
        ctx = obj.get("context") if isinstance(obj.get("context"), dict) else {}
        found.append((pointer or "/", ctx, direct_nums))
        return found

    if direct_nums and pointer == "":
        found.append(("/", {}, direct_nums))

    for key, sub in child_dicts.items():
        if key == "context":
            continue
        esc = key.replace("~", "~0").replace("/", "~1")
        found.extend(_discover_result_nodes(sub, f"{pointer}/{esc}"))
    return found


def bootstrap_study_facts(project: Path, *, dry_run: bool = False) -> tuple[int, dict]:
    """Scan 03_analysis/results/*.json and populate/merge 01_protocol/study_facts.json."""
    results_dir = project / "03_analysis/results"
    facts_path = project / "01_protocol/study_facts.json"
    if not results_dir.is_dir():
        return 2, {"error": "03_analysis/results directory not found"}

    existing: dict = {}
    if facts_path.is_file():
        try:
            existing = json.loads(facts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return 2, {"error": f"invalid existing study_facts.json: {exc}"}

    out = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    num_facts = out.setdefault("numeric_facts", {})
    if not isinstance(num_facts, dict):
        return 2, {"error": "study_facts.json numeric_facts must be an object"}

    existing_targets = {
        (str(v.get("source", "")), str(v.get("pointer", "/")))
        for v in num_facts.values()
        if isinstance(v, dict)
    }

    added = 0
    pending_ctx_ids: list[str] = []
    ready_ids: list[str] = []

    for rfile in sorted(results_dir.glob("*.json")):
        rel_src = rfile.relative_to(project).as_posix()
        try:
            data = json.loads(rfile.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for ptr, raw_ctx, _ in _discover_result_nodes(data):
            if (rel_src, ptr) in existing_targets:
                continue
            base_id = _slug(f"{rfile.stem}_{ptr.strip('/') or 'root'}")
            fid = base_id
            seq = 2
            while fid in num_facts:
                fid = f"{base_id}_{seq}"
                seq += 1
            merged_ctx: dict[str, object] = {}
            missing_any = False
            for k in REQUIRED_CTX_ORDER:
                v = raw_ctx.get(k)
                if isinstance(v, str) and v.strip():
                    merged_ctx[k] = v.strip()
                else:
                    merged_ctx[k] = PENDING_CTX
                    missing_any = True
            for extra_k in ("percentage_basis", "interval_level"):
                if extra_k in raw_ctx and raw_ctx[extra_k] not in (None, ""):
                    merged_ctx[extra_k] = raw_ctx[extra_k]
            num_facts[fid] = {
                "source": rel_src,
                "pointer": ptr,
                "context": merged_ctx,
            }
            existing_targets.add((rel_src, ptr))
            added += 1
            if missing_any:
                pending_ctx_ids.append(fid)
            else:
                ready_ids.append(fid)

    # Also report pre-existing facts still carrying PENDING_CLINICAL_CONTEXT
    for fid, entry in num_facts.items():
        if fid in pending_ctx_ids or not isinstance(entry, dict):
            continue
        ctx = entry.get("context", {})
        if isinstance(ctx, dict) and any(str(ctx.get(k, "")).strip() in {"", PENDING_CTX} for k in REQUIRED_CTX_ORDER):
            pending_ctx_ids.append(fid)

    if not dry_run and (added > 0 or not facts_path.is_file()):
        facts_path.parent.mkdir(parents=True, exist_ok=True)
        guard_outputs(project, [facts_path])
        atomic_json(facts_path, out)

    return 0, {
        "study_facts_file": "01_protocol/study_facts.json",
        "facts_added": added,
        "facts_total": len(num_facts),
        "ready_new_facts": ready_ids,
        "pending_context_facts": pending_ctx_ids,
    }


def _word_set(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").casefold()) if len(w) >= 2}


def _fact_pool(fid: str, fact: dict, project: Path) -> tuple[set, set, set]:
    outcome_lbl = str(fact.get("context", {}).get("outcome", ""))
    return claims.claim_values(
        {"fact_ids": [fid], "_project": project},
        {fid: fact},
        f"{outcome_lbl} {clinical_label(outcome_lbl, project)}",
    )


def _infer_proportions(text: str, fids: list[str], catalog: dict) -> tuple[list[dict], bool]:
    """Infer unambiguous part-whole numerator/denominator keys for reported percentages."""
    pcts = [m.group(1) for m in PCT_RE.finditer(text or "")]
    if not pcts:
        return [], False
    # Ignore confidence-interval labels like "95% CI"
    filtered_pcts: list[str] = []
    for m in PCT_RE.finditer(text or ""):
        tail = (text or "")[m.end() : m.end() + 18]
        if re.match(r"^\s*(?:CI\b|confidence\s+interval\b|CrI\b|credible\s+interval\b)", tail, re.I):
            continue
        filtered_pcts.append(m.group(1))
    if not filtered_pcts:
        return [], False

    props: list[dict] = []
    ambiguous = False
    for raw_pct in filtered_pcts:
        dec_pct = Decimal(raw_pct)
        places = max(0, -dec_pct.as_tuple().exponent)
        quant = Decimal("1") if places == 0 else Decimal("1." + ("0" * places))
        matches: list[tuple[str, str, str]] = []
        for fid in fids:
            vals = catalog[fid].get("values", {})
            if not isinstance(vals, dict):
                continue
            int_items = [
                (k, int(v))
                for k, v in vals.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() and int(v) >= 0
            ]
            for nk, nv in int_items:
                for dk, dv in int_items:
                    if nk == dk or dv <= 0 or nv > dv:
                        continue
                    calc = (Decimal(nv) * Decimal(100) / Decimal(dv)).quantize(quant, rounding=ROUND_HALF_UP)
                    if calc == dec_pct:
                        # Prefer numerator/denominator numbers that also appear literally in the text
                        matches.append((fid, nk, dk))
        if len(matches) > 1:
            txt_nums = {_norm(m.group(1)) for m in NUM_RE.finditer(_scrub(text or ""))}
            narrowed = [
                (fid, nk, dk)
                for (fid, nk, dk) in matches
                if str(int(catalog[fid]["values"][nk])) in txt_nums or str(int(catalog[fid]["values"][dk])) in txt_nums
            ]
            if len(narrowed) >= 1:
                matches = narrowed
        if len(matches) > 1:
            # When all matches in the same fact have identical numeric (numerator, denominator) values
            # (e.g. n_nonmissing == n_total when missing == 0), prefer explicit nonmissing/denom keys.
            unique_val_pairs = {
                (fid, int(catalog[fid]["values"][nk]), int(catalog[fid]["values"][dk]))
                for (fid, nk, dk) in matches
            }
            if len(unique_val_pairs) == 1:
                preferred = sorted(
                    matches,
                    key=lambda item: (
                        0 if "nonmissing" in item[2] else (1 if "denom" in item[2] else 2),
                        len(item[1]),
                        item[2],
                    ),
                )
                matches = [preferred[0]]
        if len(matches) == 1:
            fid, nk, dk = matches[0]
            props.append({
                "fact_id": fid,
                "numerator_key": nk,
                "denominator_key": dk,
                "reported": f"{raw_pct}%",
            })
        else:
            ambiguous = True
    return props, ambiguous


def _score_fact_against_context(fact: dict, ctx_text: str, project: Path) -> int:
    ctx_words = _word_set(ctx_text)
    if not ctx_words:
        return 0
    blob = " ".join(
        f"{v} {clinical_label(v, project)}"
        for v in fact.get("context", {}).values()
        if isinstance(v, str) and not claims._not_applicable(v)
    )
    f_words = _word_set(blob)
    score = len(ctx_words & f_words)
    # Bonus for matching adjustment state (adjusted vs unadjusted)
    c_adj = claims._model_adjustment_state(ctx_text)
    f_adj = claims._model_adjustment_state(blob)
    if c_adj and f_adj:
        if c_adj == f_adj:
            score += 4
        elif not (c_adj & f_adj):
            score -= 8
    return score


def _select_covering_facts(
    text: str,
    ctx_text: str,
    catalog: dict,
    pools: dict[str, tuple[set, set, set]],
    project: Path,
) -> tuple[list[str] | None, list[list[str]]]:
    """Return (unique_winner_fids, candidate_fid_sets) covering all numbers in `text`."""
    quote_fams = claims.measure_families(text) | claims.measure_families(ctx_text)

    single_cands: list[tuple[int, list[str]]] = []
    combined_for_outcome = f"{text} {ctx_text}"
    for fid, fact in catalog.items():
        fl, st, pv = pools[fid]
        if _offenders(text, fl, st, set(), pv):
            continue
        try:
            claims.claim_values({"fact_ids": [fid], "_project": project}, catalog, combined_for_outcome)
        except ValueError:
            continue
        exp_u = fact["context"]["unit"]
        exp_fams = claims.measure_families(exp_u) | claims.measure_families(clinical_label(exp_u, project))
        if quote_fams and exp_fams and not (quote_fams & exp_fams):
            continue
        score = _score_fact_against_context(fact, f"{text} | {ctx_text}", project)
        single_cands.append((score, [fid]))

    if single_cands:
        single_cands.sort(key=lambda x: x[0], reverse=True)
        top_score = single_cands[0][0]
        tied = [c[1] for c in single_cands if c[0] == top_score]
        if len(tied) == 1:
            return tied[0], tied
        return None, [c[1] for c in single_cands[:5]]

    # Try 2-fact combinations only among facts that cover at least one number in `text`
    txt_nums = {_norm(m.group(1)) for m in NUM_RE.finditer(_scrub(text))}
    partial_fids: list[str] = []
    for fid in catalog:
        fl, st, pv = pools[fid]
        rem = set(_offenders(text, fl, st, set(), pv))
        if len(rem) < len(txt_nums):
            partial_fids.append(fid)

    pair_cands: list[tuple[int, list[str]]] = []
    for f1, f2 in combinations(partial_fids[:25], 2):
        fl = pools[f1][0] | pools[f2][0]
        st = pools[f1][1] | pools[f2][1]
        pv = pools[f1][2] | pools[f2][2]
        if _offenders(text, fl, st, set(), pv):
            continue
        sc = _score_fact_against_context(catalog[f1], f"{text} | {ctx_text}", project) + _score_fact_against_context(
            catalog[f2], f"{text} | {ctx_text}", project
        )
        pair_cands.append((sc, [f1, f2]))

    if pair_cands:
        pair_cands.sort(key=lambda x: x[0], reverse=True)
        top_score = pair_cands[0][0]
        tied = [c[1] for c in pair_cands if c[0] == top_score]
        if len(tied) == 1:
            return tied[0], tied
        return None, [c[1] for c in pair_cands[:5]]

    return None, []


def _find_prose_observation(
    field: str,
    expected_raw: str,
    project: Path,
    quote: str,
    preceding_scope: str,
) -> object:
    if field != "unit" and claims._not_applicable(expected_raw):
        return None
    if field == "unit" and claims._unit_is_exempt(expected_raw):
        return None
    expected = clinical_label(expected_raw, project)

    # 1. Exact or shorthand substring in `quote`
    for cand in (expected, expected_raw, claims._strip_sample_size(expected)):
        if cand and cand in quote:
            return cand
        m = re.search(r"(?<!\w)" + re.escape(cand) + r"(?!\w)", quote, re.I) if cand else None
        if m:
            return m.group(0)

    # 2. Check sub-clauses/noun phrases in quote for _clinical_shorthand_matches or _unit_matches
    if field == "unit" and claims._unit_matches(expected, quote):
        return None  # Unit already satisfied directly in quote

    # Try matching concise 2..6-word spans in quote against _clinical_shorthand_matches
    words = list(re.finditer(r"\S+", quote))
    for length in range(min(7, len(words)), 1, -1):
        for start_i in range(0, len(words) - length + 1):
            snippet = quote[words[start_i].start() : words[start_i + length - 1].end()].strip(" ,;:().")
            if snippet and snippet in quote and claims._clinical_shorthand_matches(expected, snippet):
                return snippet

    # 3. Section-level anchor preceding the quote
    for cand in (expected, expected_raw, claims._strip_sample_size(expected)):
        if cand and cand in preceding_scope:
            return {"mode": "literal", "scope": "section", "quote": cand}
        m = re.search(r"(?<!\w)" + re.escape(cand) + r"(?!\w)", preceding_scope, re.I) if cand else None
        if m:
            return {"mode": "literal", "scope": "section", "quote": m.group(0)}

    return {"mode": "pending", "expected": expected}


def scaffold_claim_bindings(
    project: Path,
    *,
    only_file: str | None = None,
    dry_run: bool = False,
) -> tuple[int, dict]:
    """Auto-scaffold unambiguous table cell and prose sentence bindings into 07_manuscript/claim_bindings.json."""
    if not (project / "01_protocol/study_facts.json").is_file():
        return 2, {"error": "missing 01_protocol/study_facts.json (run --bootstrap-facts first)"}
    try:
        catalog = claims.facts(project)
    except Exception as exc:  # noqa: BLE001
        return 2, {"error": f"study_facts resolution failed: {exc}"}

    pending_facts = [
        fid
        for fid, f in catalog.items()
        if any(str(v).strip() == PENDING_CTX for v in f.get("context", {}).values())
    ]
    if pending_facts:
        return 2, {
            "error": f"complete PENDING_CLINICAL_CONTEXT in 01_protocol/study_facts.json before scaffolding claims: {pending_facts[:8]}"
        }

    binding_rel = "07_manuscript/claim_bindings.json"
    binding_path = project / binding_rel
    if binding_path.is_file():
        work = json.loads(binding_path.read_text(encoding="utf-8"))
    else:
        work = {"schema_version": 1, "claims": []}
    rows: list[dict] = work.setdefault("claims", [])

    norm_only = Path(only_file).as_posix() if only_file else None
    if norm_only and norm_only.startswith("project/"):
        norm_only = norm_only[len("project/") :]

    pools = {fid: _fact_pool(fid, f, project) for fid, f in catalog.items()}
    stats = {
        "binding_file": binding_rel,
        "table_cells_added": 0,
        "table_cells_ambiguous": 0,
        "prose_claims_added": 0,
        "prose_claims_ambiguous": 0,
        "prose_pending_context": 0,
    }

    # 1. Scaffold table workbooks (04_tables/**/*.xlsx)
    existing_cells = {
        (str(r.get("path", "")), str(r.get("sheet", "")), str(r.get("cell", "")))
        for r in rows
        if r.get("sheet") and r.get("cell")
    }
    xlsx_targets: list[Path] = []
    if norm_only is None:
        if (project / "04_tables").is_dir():
            xlsx_targets = [
                p for p in sorted((project / "04_tables").rglob("*.xlsx"))
                if not p.name.startswith("~$")
            ]
    elif norm_only.endswith(".xlsx") and (project / norm_only).is_file():
        xlsx_targets = [project / norm_only]

    for xfile in xlsx_targets:
        rel_x = xfile.relative_to(project).as_posix()
        try:
            wb = xlsxlite.Workbook(xfile)
        except Exception:  # noqa: BLE001
            continue
        for sh in wb.sheets:
            hdr_rows, bottom_row = wb.header_rows(sh)
            if not hdr_rows or bottom_row is None:
                continue
            first_data_row = max(hdr_rows) + 1
            for cell in sh.cells:
                if cell.row < first_data_row or cell.row > bottom_row or cell.col == 1:
                    continue
                if (rel_x, sh.name, cell.ref) in existing_cells:
                    continue
                val_txt = str(cell.value if cell.value is not None else "").strip()
                if not val_txt or not NUM_RE.search(_scrub(val_txt)):
                    continue
                stub_ref = f"A{cell.row}"
                stub_txt = sh.cell_text(cell.row, 1)
                grp_txt = wb.row_group_header(sh.name, cell.ref) or ""
                col_hdrs = wb.column_headers(sh.name, cell.ref)
                ctx_str = " | ".join(x for x in (stub_txt, grp_txt, *col_hdrs) if x)
                winner, cands = _select_covering_facts(val_txt, ctx_str, catalog, pools, project)
                new_row: dict[str, object] = {
                    "path": rel_x,
                    "sheet": sh.name,
                    "cell": cell.ref,
                    "label_cells": [stub_ref] if stub_txt else [],
                    "text": val_txt,
                }
                if winner is not None:
                    new_row["fact_ids"] = winner
                    from .proportions import table_percentage_text
                    pct_probe = table_percentage_text(val_txt, " ".join([stub_txt, *col_hdrs]))
                    props, prop_amb = _infer_proportions(pct_probe, winner, catalog)
                    if props and not prop_amb:
                        new_row["proportions"] = props
                    stats["table_cells_added"] += 1
                else:
                    new_row["fact_ids"] = [AMBIGUOUS_SENTINEL]
                    new_row["_candidates"] = cands
                    stats["table_cells_ambiguous"] += 1
                rows.append(new_row)
                existing_cells.add((rel_x, sh.name, cell.ref))

    # 2. Scaffold prose files
    from .manuscript_sentences import split_prose_sentences
    md_targets: list[str] = []
    if norm_only is None:
        for cand_md in ("07_manuscript/results.md", "07_manuscript/abstract.md", "07_manuscript/discussion.md"):
            if (project / cand_md).is_file():
                md_targets.append(cand_md)
    elif norm_only.endswith(".md") and (project / norm_only).is_file():
        md_targets = [norm_only]

    for rel_md in md_targets:
        raw_md = (project / rel_md).read_text(encoding="utf-8")
        body = claims.results_text(raw_md, rel_md, include_discussion=True)
        if not NUM_RE.search(_scrub(body)):
            continue
        outline = claims._outline(body)
        covered_quotes = [str(r.get("text", "")) for r in rows if r.get("path") == rel_md and r.get("text")]
        masked_body = body
        for q in covered_quotes:
            if q and q in masked_body:
                masked_body = masked_body.replace(q, " " * len(q))

        for sent in split_prose_sentences(masked_body):
            if not NUM_RE.search(_scrub(sent)) or sent not in body:
                continue
            pos = body.find(sent)
            preceding_nodes = [n for n in outline if n["start"] <= pos]
            sec_path = list(preceding_nodes[-1]["path"]) if preceding_nodes else []
            sec_start = preceding_nodes[-1]["start"] if preceding_nodes else 0
            preceding_scope = body[sec_start : pos + len(sent)]
            ctx_str = " > ".join(sec_path)
            winner, cands = _select_covering_facts(sent, ctx_str, catalog, pools, project)
            entry: dict[str, object] = {
                "path": rel_md,
                "section": sec_path,
                "text": sent,
            }
            if winner is not None:
                entry["fact_ids"] = winner
                props, prop_amb = _infer_proportions(sent, winner, catalog)
                if props and not prop_amb:
                    entry["proportions"] = props
                ctx_ev: dict[str, dict] = {}
                for fid in winner:
                    fact = catalog[fid]
                    obs: dict[str, object] = {}
                    for field in ("population", "comparison", "model", "timepoint", "unit"):
                        found_obs = _find_prose_observation(
                            field, str(fact["context"].get(field, "")), project, sent, preceding_scope
                        )
                        if found_obs is not None:
                            obs[field] = found_obs
                            if isinstance(found_obs, dict) and found_obs.get("mode") == "pending":
                                stats["prose_pending_context"] += 1
                    ctx_ev[fid] = {
                        "fact_fingerprint": fact["fingerprint"],
                        "claim_fingerprint": claims.fingerprint(sent),
                        "observations": obs,
                    }
                entry["context_evidence"] = ctx_ev
                stats["prose_claims_added"] += 1
            else:
                entry["fact_ids"] = [AMBIGUOUS_SENTINEL]
                entry["_candidates"] = cands
                stats["prose_claims_ambiguous"] += 1
            rows.append(entry)

    if not dry_run:
        binding_path.parent.mkdir(parents=True, exist_ok=True)
        guard_outputs(project, [binding_path])
        atomic_json(binding_path, work)

    has_unresolved = (
        stats["table_cells_ambiguous"] > 0
        or stats["prose_claims_ambiguous"] > 0
        or stats["prose_pending_context"] > 0
    )
    return (2 if has_unresolved else 0), stats
