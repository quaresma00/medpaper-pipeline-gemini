#!/usr/bin/env python3
"""Synchronize claim/fact fingerprints and safely re-anchor wording-only edits in claim_bindings.json.

Safety contract:
- Never invents fact_ids, numbers, citekeys, or executor read-back interpretations.
- Fact fingerprints are recomputed strictly from 01_protocol/study_facts.json + 03_analysis/results/*.json.
- `--reanchor` only updates a prose binding's `text` when a unique sentence (or multi-sentence span)
  in the same target file and section preserves the EXACT numeric multiset (and citekeys for source_claims)
  with high lexical similarity (>= 0.70) and zero ambiguity.
- Unless `--no-validate` is passed, every touched markdown target is verified with `claims.validate_prose`
  before committing changes; any provenance failure rolls back automatically.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from wfcore import claims, journalspec, sourceclaims  # noqa: E402
from wfcore.checks.numbers import NUM_RE, _norm, _scrub  # noqa: E402
from wfcore.checks.refs import citekeys  # noqa: E402
from wfcore.readiness import atomic_json  # noqa: E402
from wfcore.revision import guard_outputs  # noqa: E402

_ABBR_DOT_RE = re.compile(
    r"\b(vs|et\s+al|e\.g|i\.e|Fig|Figs|No|Ref|Refs|Dr|Prof|approx|ca)\.\s+",
    re.I,
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'“])")


def project_root(override: Path | None = None) -> Path:
    if override is not None:
        return override.resolve()
    raw = os.environ.get("MEDPAPER_PROJECT")
    return Path(raw).resolve() if raw else (ROOT / "project").resolve()


def _num_multiset(text: str) -> Counter[str]:
    return Counter(_norm(m.group(1)) for m in NUM_RE.finditer(_scrub(text or "")))


def _split_sentences(block: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n", block or ""):
        stripped = para.strip()
        if not stripped or re.match(r"^#{1,6}\s+", stripped):
            continue
        compact = re.sub(r"\s*\n\s*", " ", stripped)
        protected = _ABBR_DOT_RE.sub(lambda m: m.group(0).replace(". ", ".\u0000"), compact)
        raw_sents = [s.replace(".\u0000", ". ").strip() for s in _SENT_SPLIT_RE.split(protected) if s.strip()]
        out.extend(raw_sents)
        if len(raw_sents) >= 2:
            for idx in range(len(raw_sents) - 1):
                out.append(f"{raw_sents[idx]} {raw_sents[idx + 1]}")
        if stripped not in out and len(raw_sents) <= 3:
            out.append(compact)
    # Deduplicate preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _scoped_search_text(body: str, section: list[str] | None) -> str:
    if not section:
        return body
    outline = claims._outline(body)
    parts: list[str] = []
    for node in outline:
        if node["path"][: len(section)] == section or node["path"][-len(section) :] == section:
            parts.append(body[node["content"] : node["end"]])
    return "\n\n".join(parts) if parts else body


def _normalize_section_path(body: str, quote: str, row: dict) -> bool:
    """Repair component section paths that omitted the leading H1 chapter heading (e.g. ['Primary outcome'] -> ['Results', 'Primary outcome'])."""
    sec = row.get("section")
    if not isinstance(sec, list) or not sec or not quote or quote not in body:
        return False
    outline = claims._outline(body)
    try:
        claims._locate_claim(body, quote, row, outline)
        return False
    except ValueError:
        pass
    candidate_paths: list[list[str]] = []
    for m in re.finditer(re.escape(quote), body):
        preceding = [i for i, n in enumerate(outline) if n["start"] <= m.start()]
        node = outline[preceding[-1]] if preceding else None
        if node and len(node["path"]) >= len(sec) and node["path"][-len(sec) :] == sec:
            if node["path"] not in candidate_paths:
                candidate_paths.append(list(node["path"]))
    if len(candidate_paths) == 1:
        probe = {**row, "section": candidate_paths[0]}
        try:
            claims._locate_claim(body, quote, probe, outline)
            row["section"] = candidate_paths[0]
            return True
        except ValueError:
            return False
    return False


def _find_reanchor_candidate(
    search_text: str,
    old_quote: str,
    *,
    required_citekeys: set[str] | None = None,
    min_ratio: float = 0.70,
) -> tuple[str | None, str | None]:
    expected_nums = _num_multiset(old_quote)
    if not expected_nums:
        return None, "original quote contains no numeric tokens to anchor safely"
    scored: list[tuple[float, str]] = []
    for cand in _split_sentences(search_text):
        if _num_multiset(cand) != expected_nums:
            continue
        if required_citekeys is not None and set(citekeys(cand)) != required_citekeys:
            continue
        ratio = difflib.SequenceMatcher(None, old_quote.casefold(), cand.casefold()).ratio()
        if ratio >= min_ratio:
            scored.append((ratio, cand))
    if not scored:
        return None, "no sentence with identical numeric multiset and similarity >= 0.70 found"
    scored.sort(key=lambda item: item[0], reverse=True)
    best_ratio, best_cand = scored[0]
    distinct_runners = [item for item in scored[1:] if item[1] != best_cand]
    if distinct_runners and (best_ratio - distinct_runners[0][0]) < 0.03:
        return None, f"ambiguous re-anchor candidates (top similarity {best_ratio:.3f} vs {distinct_runners[0][0]:.3f})"
    return best_cand, None


def _adapt_anchor_in_quote(anchor: str, new_quote: str) -> str:
    if not anchor or anchor in new_quote:
        return anchor
    for system in ("american", "british"):
        converted = journalspec.spelling(anchor, system)
        if converted in new_quote:
            return converted
        m = re.search(r"(?<!\w)" + re.escape(converted) + r"(?!\w)", new_quote, re.I)
        if m:
            return m.group(0)
    m_orig = re.search(r"(?<!\w)" + re.escape(anchor) + r"(?!\w)", new_quote, re.I)
    if m_orig:
        return m_orig.group(0)
    return anchor


def sync_bindings(
    project: Path,
    *,
    layer: str = "auto",
    only_file: str | None = None,
    reanchor: bool = False,
    dry_run: bool = False,
    validate: bool = True,
) -> tuple[int, dict]:
    norm_only = Path(only_file).as_posix() if only_file else None
    if norm_only and norm_only.startswith("project/"):
        norm_only = norm_only[len("project/") :]

    if layer == "auto":
        use_journal = bool(norm_only and norm_only.startswith("08_submission/"))
    else:
        use_journal = layer == "journal"

    binding_rel = (
        "08_submission/integration/claim_bindings.json"
        if use_journal
        else "07_manuscript/claim_bindings.json"
    )
    binding_path = project / binding_rel
    if not binding_path.is_file():
        return 2, {"error": f"missing {binding_rel}"}
    if not (project / "01_protocol/study_facts.json").is_file():
        return 2, {"error": "missing 01_protocol/study_facts.json"}

    try:
        catalog = claims.facts(project)
    except Exception as exc:  # noqa: BLE001
        return 2, {"error": f"study_facts resolution failed: {exc}"}

    original_bytes = binding_path.read_text(encoding="utf-8")
    payload = json.loads(original_bytes)
    work = copy.deepcopy(payload)
    rows = work.get("claims", [])
    if not isinstance(rows, list):
        return 2, {"error": f"{binding_rel}: claims must be a list"}

    has_component_rows = (
        not use_journal
        and any(
            r.get("path") in {"07_manuscript/abstract.md", "07_manuscript/results.md", "07_manuscript/discussion.md"}
            for r in rows
        )
    )

    stats = {
        "binding_file": binding_rel,
        "fact_fingerprints_updated": 0,
        "claim_fingerprints_updated": 0,
        "claims_reanchored": 0,
        "source_claims_reanchored": 0,
        "assembled_refreshed": False,
        "unresolved": [],
    }
    md_cache: dict[str, str] = {}
    touched_mds: set[str] = set()

    def _read_md(rel_path: str) -> str | None:
        if rel_path not in md_cache:
            p = project / rel_path
            md_cache[rel_path] = p.read_text(encoding="utf-8") if p.is_file() else ""
        return md_cache[rel_path] or None

    for row in rows:
        rel_path = str(row.get("path", ""))
        if not rel_path.endswith(".md"):
            continue
        if norm_only and rel_path != norm_only:
            continue
        if has_component_rows and rel_path == "07_manuscript/full_manuscript.md" and norm_only != "07_manuscript/full_manuscript.md":
            # Derived canonical full_manuscript rows are regenerated below from component sections.
            continue

        md_text = _read_md(rel_path)
        if md_text is None:
            continue
        touched_mds.add(rel_path)
        body = claims.results_text(md_text, rel_path, include_discussion=True)
        quote = str(row.get("text", ""))
        active_quote = quote

        if quote and quote not in body:
            if reanchor:
                search_area = _scoped_search_text(body, row.get("section"))
                cand, reason = _find_reanchor_candidate(search_area, quote)
                if cand is not None:
                    row["text"] = cand
                    active_quote = cand
                    stats["claims_reanchored"] += 1
                else:
                    stats["unresolved"].append(f"{rel_path}: {reason} -> {quote[:90]!r}")
                    continue
            else:
                stats["unresolved"].append(
                    f"{rel_path}: claim text changed (pass --reanchor to rebind wording-only edits) -> {quote[:90]!r}"
                )
                continue

        if active_quote and active_quote in body:
            if _normalize_section_path(body, active_quote, row):
                stats["sections_normalized"] = stats.get("sections_normalized", 0) + 1

        ev = row.get("context_evidence")
        if isinstance(ev, dict):
            for fid in row.get("fact_ids", []):
                if fid not in catalog or not isinstance(ev.get(fid), dict):
                    continue
                item = ev[fid]
                expected_ffp = catalog[fid]["fingerprint"]
                if item.get("fact_fingerprint") != expected_ffp:
                    item["fact_fingerprint"] = expected_ffp
                    stats["fact_fingerprints_updated"] += 1
                if active_quote and active_quote in body:
                    expected_cfp = claims.fingerprint(active_quote)
                    if item.get("claim_fingerprint") != expected_cfp:
                        item["claim_fingerprint"] = expected_cfp
                        stats["claim_fingerprints_updated"] += 1
                    obs = item.get("observations")
                    if isinstance(obs, dict) and active_quote != quote:
                        for field, val in list(obs.items()):
                            if isinstance(val, str):
                                obs[field] = _adapt_anchor_in_quote(val, active_quote)
                            elif isinstance(val, dict) and val.get("scope", "claim") == "claim" and isinstance(val.get("quote"), str):
                                val["quote"] = _adapt_anchor_in_quote(val["quote"], active_quote)

    if reanchor:
        for srow in work.get("source_claims", []):
            rel_path = str(srow.get("path", ""))
            if not rel_path.endswith(".md"):
                continue
            if norm_only and rel_path != norm_only:
                continue
            if has_component_rows and rel_path == "07_manuscript/full_manuscript.md" and norm_only != "07_manuscript/full_manuscript.md":
                continue
            md_text = _read_md(rel_path)
            if md_text is None:
                continue
            touched_mds.add(rel_path)
            passage = str(srow.get("text", ""))
            if passage and passage not in md_text:
                req_keys = set(citekeys(passage))
                if srow.get("citekey"):
                    req_keys.add(str(srow["citekey"]))
                cand, reason = _find_reanchor_candidate(md_text, passage, required_citekeys=req_keys)
                if cand is not None:
                    srow["text"] = cand
                    stats["source_claims_reanchored"] += 1
                else:
                    stats["unresolved"].append(f"{rel_path} (source_claim {srow.get('citekey')}): {reason}")

    if not use_journal and has_component_rows and (project / "07_manuscript/full_manuscript.md").is_file():
        full_text = _read_md("07_manuscript/full_manuscript.md") or ""
        original_non_full = [r for r in work["claims"] if r.get("path") != "07_manuscript/full_manuscript.md"]
        seen: set[str] = set()
        assembled: list[dict] = []
        chapter_map = {
            "07_manuscript/abstract.md": "Abstract",
            "07_manuscript/results.md": "Results",
            "07_manuscript/discussion.md": "Discussion",
        }
        for r in original_non_full:
            chapter = chapter_map.get(r.get("path"))
            if not chapter:
                continue
            if r.get("text") and r["text"] in full_text:
                current = r.get("context_evidence") is not None
                key = json.dumps(
                    [
                        r["text"],
                        r.get("fact_ids"),
                        r.get("path") if current else None,
                        r.get("section") if current else None,
                        r.get("occurrence") if current else None,
                    ],
                    sort_keys=True,
                )
                if key not in seen:
                    derived = copy.deepcopy(r)
                    derived["path"] = "07_manuscript/full_manuscript.md"
                    if current:
                        sec = derived.get("section", [])
                        derived["section"] = sec if sec and sec[0] == chapter else [chapter] + list(sec)
                    assembled.append(derived)
                    seen.add(key)
        ext_non_full = [r for r in work.get("source_claims", []) if r.get("path") != "07_manuscript/full_manuscript.md"]
        ext_derived = [
            {**copy.deepcopy(r), "path": "07_manuscript/full_manuscript.md"}
            for r in ext_non_full
            if r.get("text") and r["text"] in full_text
        ]
        work["claims"] = original_non_full + assembled
        if "source_claims" in work or ext_derived:
            work["source_claims"] = ext_non_full + ext_derived
        stats["assembled_refreshed"] = True
        if not norm_only:
            touched_mds.add("07_manuscript/full_manuscript.md")

    if stats["unresolved"]:
        return 2, stats

    if dry_run:
        return 0, stats

    guard_outputs(project, [binding_path])
    atomic_json(binding_path, work)

    if validate:
        validation_errors: list[str] = []
        targets = [norm_only] if norm_only else sorted(touched_mds)
        for rel_path in targets:
            if not rel_path or not (project / rel_path).is_file():
                continue
            raw_md = (project / rel_path).read_text(encoding="utf-8")
            masked, ext_errs = sourceclaims.mask(project, rel_path, raw_md)
            if ext_errs:
                validation_errors.extend(f"{rel_path}: {e}" for e in ext_errs)
                continue
            validation_errors.extend(claims.validate_prose(project, rel_path, masked, already_masked=True))
        if validation_errors:
            binding_path.write_text(original_bytes, encoding="utf-8")
            stats["validation_errors"] = validation_errors
            return 2, stats

    return 0, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Synchronize study_facts/claim fingerprints and safely re-anchor wording-only edits in claim_bindings.json."
    )
    ap.add_argument("--project", type=Path, default=None, help="override project root")
    ap.add_argument("--layer", choices=["auto", "science", "journal"], default="auto")
    ap.add_argument("--file", help="restrict sync to one markdown file (e.g. 07_manuscript/results.md)")
    ap.add_argument("--reanchor", action="store_true", help="re-anchor wording-only sentence edits with identical numeric multiset")
    ap.add_argument("--dry-run", action="store_true", help="report updates without modifying files")
    ap.add_argument("--no-validate", action="store_true", help="skip post-sync claims.validate_prose check")
    ap.add_argument("--json", action="store_true", help="print JSON summary")
    args = ap.parse_args(argv)

    proj = project_root(args.project)
    rc, info = sync_bindings(
        proj,
        layer=args.layer,
        only_file=args.file,
        reanchor=args.reanchor,
        dry_run=args.dry_run,
        validate=not args.no_validate,
    )
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return rc
    if rc != 0:
        if "error" in info:
            print(f"sync_claims error: {info['error']}", file=sys.stderr)
        for item in info.get("unresolved", []):
            print(f"  [UNRESOLVED] {item}", file=sys.stderr)
        for item in info.get("validation_errors", []):
            print(f"  [VALIDATION FAILED] {item}", file=sys.stderr)
        return rc
    mode = "[dry-run] " if args.dry_run else ""
    print(
        f"{mode}synced {info['binding_file']}: "
        f"reanchored={info['claims_reanchored']} claim(s), "
        f"source_reanchored={info['source_claims_reanchored']}, "
        f"fact_fp={info['fact_fingerprints_updated']}, "
        f"claim_fp={info['claim_fingerprints_updated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
