#!/usr/bin/env python3
"""Independently verify every library entry against the source of record.

Freshly re-fetches each PMID (and optionally cross-checks the DOI against Crossref),
then compares PMID / DOI / title / journal / year / first author.  The output binds
the exact library to hashed raw PubMed XML.  Gates reparse that XML and never trust
the authored ``verified`` boolean by itself.  Failures are quarantined, never patched.

    uv run python tools/pubmed/verify.py
    uv run python tools/pubmed/verify.py --strict     # also require a DOI/Crossref match
    uv run python tools/pubmed/verify.py --quarantine # move failures out of library.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pubmed import eutils as eu  # noqa: E402
from wfcore import refproof  # noqa: E402

TITLE_THRESHOLD = 0.92
JOURNAL_THRESHOLD = 0.85


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()


def ratio(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def verify_entry(entry: dict, live: dict | None, strict: bool, project: Path | None = None) -> dict:
    checks: list[dict] = []
    src_kind = str(entry.get("source") or "pubmed")
    if live is None:
        ident = entry.get("pmid") or entry.get("doi") or entry.get("r_package") or entry.get("url") or "(none)"
        return {
            "verified": False, "via": src_kind, "at": eu.now(),
            "reason": f"Source identifier {ident} returned no record on fresh re-fetch",
            "checks": [],
        }

    if src_kind == "crossref":
        entry_doi = str(entry.get("doi", "")).strip().casefold()
        live_doi = str(live.get("doi", "")).strip().casefold()
        checks.append({"field": "doi", "ok": bool(entry_doi) and entry_doi == live_doi, "expected": live_doi})
        t = ratio(entry.get("title", ""), live.get("title", ""))
        checks.append({"field": "title", "score": round(t, 3), "ok": t >= TITLE_THRESHOLD,
                       "expected": live.get("title", "")})
        if live.get("journal"):
            j = ratio(entry.get("journal", ""), live.get("journal", ""))
            checks.append({"field": "journal", "score": round(j, 3), "ok": j >= JOURNAL_THRESHOLD,
                           "expected": live.get("journal", "")})
        checks.append({"field": "year", "ok": str(entry.get("year", "")) == str(live.get("year", "")),
                       "expected": live.get("year", "")})
        ea = (entry.get("authors") or [{}])[0].get("last", "")
        la = (live.get("authors") or [{}])[0].get("last", "")
        checks.append({"field": "first_author", "ok": norm(ea) == norm(la), "expected": la})
        access_errors = refproof.readable_source_errors(project or eu.project_root(), entry, live)
        checks.append({"field": "readable_source", "ok": not access_errors,
                       "detail": "; ".join(access_errors) or "methodology DOI or registered full text verified"})
        checks.append({"field": "citable_status", "ok": not live.get("flags"),
                       "expected": "no preprint or retraction flag"})
        result = {
            "verified": all(c["ok"] for c in checks),
            "via": "crossref",
            "at": eu.now(),
            "pmid": "",
            "doi": live.get("doi", ""),
            "cache_file": live.get("cache_file", ""),
            "checks": checks,
            "flags": live.get("flags", []),
            "evidence": refproof.evidence_for_live_record(live),
        }
        if not result["verified"]:
            result["reason"] = "mismatch on: " + ", ".join(c["field"] for c in checks if not c["ok"])
        return result

    if src_kind == "authority":
        t = ratio(entry.get("title", ""), live.get("title", ""))
        checks.append({"field": "title", "score": round(t, 3), "ok": t >= TITLE_THRESHOLD,
                       "expected": live.get("title", "")})
        checks.append({"field": "year", "ok": str(entry.get("year", "")) == str(live.get("year", "")),
                       "expected": live.get("year", "")})
        ea = (entry.get("authors") or [{}])[0].get("last", "")
        la = (live.get("authors") or [{}])[0].get("last", "")
        checks.append({"field": "first_author", "ok": norm(ea) == norm(la), "expected": la})
        if live.get("r_package"):
            checks.append({"field": "r_package",
                           "ok": str(entry.get("r_package", "")).strip() == str(live.get("r_package", "")).strip(),
                           "expected": live.get("r_package", "")})
        else:
            checks.append({"field": "url",
                           "ok": str(entry.get("url", "")).strip() == str(live.get("url", "")).strip(),
                           "expected": live.get("url", "")})
        access_errors = refproof.readable_source_errors(project or eu.project_root(), entry, live)
        checks.append({"field": "readable_source", "ok": not access_errors,
                       "detail": "; ".join(access_errors) or "official authority snapshot verified"})
        result = {
            "verified": all(c["ok"] for c in checks),
            "via": "authority",
            "at": eu.now(),
            "pmid": "",
            "doi": "",
            "cache_file": live.get("cache_file", ""),
            "checks": checks,
            "flags": [],
            "evidence": refproof.evidence_for_live_record(live),
        }
        if not result["verified"]:
            result["reason"] = "mismatch on: " + ", ".join(c["field"] for c in checks if not c["ok"])
        return result

    pmid_ok = str(entry.get("pmid", "")) == str(live.get("pmid", ""))
    checks.append({"field": "pmid", "ok": pmid_ok, "expected": live.get("pmid", "")})
    entry_doi = str(entry.get("doi", "")).strip().casefold()
    live_doi = str(live.get("doi", "")).strip().casefold()
    doi_ok = entry_doi == live_doi
    checks.append({"field": "doi", "ok": doi_ok, "expected": live_doi})
    checks.append({"field": "pmcid", "ok": str(entry.get("pmcid", "")).upper() == str(live.get("pmcid", "")).upper(),
                   "expected": live.get("pmcid", "")})
    checks.append({"field": "authors", "ok": refproof.canonical_authors(entry) == refproof.canonical_authors(live),
                   "expected": refproof.canonical_authors(live)})

    t = ratio(entry.get("title", ""), live.get("title", ""))
    checks.append({"field": "title", "score": round(t, 3), "ok": t >= TITLE_THRESHOLD,
                   "expected": live.get("title", "")})
    j = ratio(entry.get("journal", ""), live.get("journal", ""))
    checks.append({"field": "journal", "score": round(j, 3), "ok": j >= JOURNAL_THRESHOLD,
                   "expected": live.get("journal", "")})
    y_ok = str(entry.get("year", "")) == str(live.get("year", ""))
    checks.append({"field": "year", "ok": y_ok, "expected": live.get("year", "")})

    ea = (entry.get("authors") or [{}])[0].get("last", "")
    la = (live.get("authors") or [{}])[0].get("last", "")
    a_ok = norm(ea) == norm(la)
    checks.append({"field": "first_author", "ok": a_ok, "expected": la})

    abs_ok = refproof.normalized_abstract(entry.get("abstract")) == refproof.normalized_abstract(live.get("abstract"))
    checks.append({"field": "abstract_matches_source", "ok": abs_ok})
    access_errors=refproof.readable_source_errors(project or eu.project_root(),entry,live)
    checks.append({"field": "readable_source", "ok": not access_errors,
                   "detail": "; ".join(access_errors) or "source abstract or registered full text available"})
    flags_ok = not live.get("flags")
    checks.append({"field": "citable_status", "ok": flags_ok,
                   "expected": "no retraction, expression-of-concern or preprint flag"})

    result = {
        "verified": all(c["ok"] for c in checks),
        "via": "pubmed",
        "at": eu.now(),
        "pmid": live.get("pmid", ""),
        "doi": live.get("doi", ""),
        "cache_file": live.get("cache_file", ""),
        "checks": checks,
        "flags": live.get("flags", []),
        "evidence": refproof.evidence_for_live_record(live),
    }

    if strict and entry.get("doi"):
        cr = eu.crossref_by_doi(entry["doi"])
        if cr is None:
            result["verified"] = False
            result["reason"] = f"DOI {entry['doi']} not resolvable at Crossref"
        else:
            ct = ratio(entry.get("title", ""), cr.get("title", ""))
            result["checks"].append({"field": "crossref_title", "score": round(ct, 3),
                                     "ok": ct >= TITLE_THRESHOLD, "expected": cr.get("title", "")})
            result["via"] = "pubmed+crossref"
            if ct < TITLE_THRESHOLD:
                result["verified"] = False
    if not result["verified"] and "reason" not in result:
        bad = [c["field"] for c in result["checks"] if not c["ok"]]
        result["reason"] = "mismatch on: " + ", ".join(bad)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="verify every reference against the source API")
    ap.add_argument("--strict", action="store_true", help="also require a Crossref DOI match")
    ap.add_argument("--quarantine", action="store_true",
                    help="move failures from library.json into quarantine.json")
    ap.add_argument("--check", action="store_true",
                    help="validate the existing proof without trusting verified=true")
    args = ap.parse_args()

    lib_path = eu.refs_dir() / "library.json"
    if not lib_path.exists():
        eu.die("06_refs/library.json does not exist. Run build_library.py first.")
    lib = json.loads(lib_path.read_text(encoding="utf-8"))
    entries = lib.get("entries", [])
    if not entries:
        eu.die("library.json has no entries")

    if args.check:
        ok, problems, count = refproof.validate_local_proof(eu.project_root())
        if not ok:
            print("reference proof failed:\n  " + "\n  ".join(problems[:20]), file=sys.stderr)
            return 2
        print(f"reference proof valid for {count} PubMed record(s)")
        return 0

    pubmed_entries = [e for e in entries if (e.get("source") or "pubmed") == "pubmed"]
    crossref_entries = [e for e in entries if e.get("source") == "crossref"]
    authority_entries = [e for e in entries if e.get("source") == "authority"]
    if len(pubmed_entries) + len(crossref_entries) + len(authority_entries) != len(entries):
        eu.die("unknown reference source track in library.json")
    pmids = [e["pmid"] for e in pubmed_entries if e.get("pmid")]
    if len(pmids) != len(pubmed_entries):
        eu.die("every PubMed library entry must have a PMID before verification")
    live_by_pmid: dict[str, dict] = {}
    if pmids:
        print(f"freshly re-fetching {len(pmids)} record(s) from PubMed...")
        live_recs = eu.efetch(pmids, fresh=True, purpose="verify")
        live_by_pmid = {r["pmid"]: r for r in live_recs}

    records: dict[str, dict] = {}
    failures: list[tuple[str, str]] = []
    for e in entries:
        src_kind = e.get("source") or "pubmed"
        if src_kind == "pubmed":
            live = live_by_pmid.get(e.get("pmid", ""))
        elif src_kind == "crossref":
            print(f"freshly verifying Crossref DOI {e.get('doi')}...")
            try:
                live = eu.crossref_fetch(e.get("doi", ""), fresh=True, purpose="verify")
            except Exception as exc:  # noqa: BLE001
                live = None
                print(f"  warning: Crossref fetch error for {e['citekey']}: {exc}", file=sys.stderr)
        else:
            print(f"freshly verifying authority source {e['citekey']}...")
            try:
                if e.get("authority_kind") == "r_software":
                    live = eu.r_citation_record(e.get("r_package", "R"), fresh=True, purpose="verify")
                else:
                    live = eu.authority_url_record(
                        e.get("url", ""),
                        title=e.get("title", ""),
                        year=e.get("year", ""),
                        author=((e.get("authors") or [{}])[0].get("last", "")),
                        journal=e.get("journal", ""),
                        fresh=True,
                        purpose="verify",
                    )
            except Exception as exc:  # noqa: BLE001
                live = None
                print(f"  warning: authority fetch error for {e['citekey']}: {exc}", file=sys.stderr)
        res = verify_entry(e, live, args.strict)
        records[e["citekey"]] = res
        if not res["verified"]:
            failures.append((e["citekey"], res.get("reason", "unknown")))

    has_non_pubmed = bool(crossref_entries or authority_entries)
    out = {
        "schema": refproof.SCHEMA,
        "generator": {
            "tool": refproof.GENERATOR,
            "mode": "fresh_multi_authority_verify" if has_non_pubmed else "fresh_ncbi_pubmed_efetch",
            "source": "NCBI PubMed EFetch + Crossref/Authority" if has_non_pubmed else "NCBI PubMed EFetch",
        },
        "verified_at": eu.now(),
        "strict": args.strict,
        "library_sha256": refproof.file_sha256(lib_path),
        "n_entries": len(entries),
        "n_verified": sum(1 for r in records.values() if r["verified"]),
        "records": records,
    }
    verified_path = eu.refs_dir() / "verified.json"
    verified_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nverified {out['n_verified']}/{len(entries)}")
    flagged = [(k, r["flags"]) for k, r in records.items() if r.get("flags")]
    if flagged:
        print("\nflagged records - do not cite these as evidence:")
        for k, f in flagged:
            print(f"  {k}: {', '.join(f)}")
    if failures:
        print(f"\n{len(failures)} failure(s):")
        for k, why in failures:
            print(f"  {k}: {why}")
        print("\nA failure means source identity, citable status or required readable evidence is not verified.")
        print("Re-fetch mismatched records or register the actual full text for a no-abstract record; never invent metadata or an abstract.")
        if args.quarantine:
            bad = {k for k, _ in failures}
            keep = [e for e in entries if e["citekey"] not in bad]
            removed = [e for e in entries if e["citekey"] in bad]
            (eu.refs_dir() / "quarantine.json").write_text(
                json.dumps({"at": eu.now(), "entries": removed}, indent=2, ensure_ascii=False),
                encoding="utf-8")
            lib["entries"] = keep
            lib_path.write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
            # Quarantine changes the library and therefore invalidates every derived
            # proof/export.  Remove them instead of leaving stale files that can look
            # authoritative to a human or an agent.  The next verifier run recreates
            # the proof from a new source request.
            for stale in (verified_path, eu.refs_dir() / "refs.bib", eu.refs_dir() / "refs.ris"):
                stale.unlink(missing_ok=True)
            print(f"\nquarantined {len(removed)} entr{'y' if len(removed) == 1 else 'ies'};"
                  f" library now holds {len(keep)}")
            print("removed stale verified.json/refs.bib/refs.ris")
            print("re-export and freshly verify the remaining library before continuing")
    else:
        print("\nall entries match the source of record.")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
