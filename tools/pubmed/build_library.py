#!/usr/bin/env python3
"""Build 06_refs/library.json and export refs.bib / refs.ris.

Records without an abstract remain candidates pending registered full-text evidence; never
write a substitute abstract. Citekeys already
used anywhere in the project are pulled in automatically so no citation is orphaned.

    uv run python tools/pubmed/build_library.py --add-ids <selected PMIDs>
    uv run python tools/pubmed/build_library.py --add-query "<uncovered argument>"
    uv run python tools/pubmed/build_library.py --add-ids 12345678,23456789
    uv run python tools/pubmed/build_library.py --export
    uv run python tools/pubmed/build_library.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pubmed import eutils as eu  # noqa: E402

LIB = "library.json"
MANUSCRIPT_GLOBS = [
    "01_protocol/*.md", "03_analysis/*.md", "07_manuscript/*.md",
]
CITE_RE = re.compile(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)")


def lib_path() -> Path:
    return eu.refs_dir() / LIB


def load_library() -> dict:
    p = lib_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"built_at": eu.now(), "queries": [], "entries": []}


def save_library(lib: dict) -> None:
    lib["updated_at"] = eu.now()
    lib_path().write_text(json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")


def used_citekeys() -> set[str]:
    """Citekeys already referenced in project prose - these must stay in the library."""
    out: set[str] = set()
    for pattern in MANUSCRIPT_GLOBS:
        for p in eu.project_root().glob(pattern):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in re.finditer(r"\[([^\]]*@[^\]]*)\]", text):
                out.update(CITE_RE.findall(m.group(1)))
    return out


def _entry_from_record(rec: dict, taken: set[str]) -> dict:
    key = eu.make_citekey(rec, taken)
    taken.add(key)
    out = {
        "citekey": key,
        "pmid": rec.get("pmid", ""),
        "doi": rec.get("doi", ""),
        "pmcid": rec.get("pmcid", ""),
        "title": rec.get("title", ""),
        "abstract": rec.get("abstract", ""),
        "authors": rec.get("authors", []),
        "journal": rec.get("journal", ""),
        "journal_abbrev": rec.get("journal_abbrev", ""),
        "year": rec.get("year", ""),
        "volume": rec.get("volume", ""),
        "issue": rec.get("issue", ""),
        "pages": rec.get("pages", ""),
        "publication_types": rec.get("publication_types", []),
        "mesh": rec.get("mesh", [])[:15],
        "flags": rec.get("flags", []),
        "source": rec.get("source", "pubmed"),
        "cache_file": rec.get("cache_file", ""),
        "retrieved_at": rec.get("retrieved_at", eu.now()),
    }
    for opt_key in ("url", "r_package", "authority_kind", "bib_type", "pool_role"):
        if rec.get(opt_key):
            out[opt_key] = rec[opt_key]
    return out


def add_records(lib: dict, records: list[dict]) -> tuple[int, int, int]:
    by_pmid = {e.get("pmid"): e for e in lib["entries"] if e.get("pmid")}
    by_doi = {str(e.get("doi")).casefold(): e for e in lib["entries"] if e.get("doi")}
    by_rpkg = {e.get("r_package"): e for e in lib["entries"] if e.get("r_package")}
    by_auth_url = {e.get("url"): e for e in lib["entries"] if e.get("source") == "authority" and e.get("url") and not e.get("r_package")}
    taken = {e["citekey"] for e in lib["entries"]}
    added = dropped = dup = 0
    for rec in records:
        if rec.get("pmid") and rec["pmid"] in by_pmid:
            dup += 1
            continue
        if rec.get("doi") and str(rec["doi"]).casefold() in by_doi:
            dup += 1
            continue
        if rec.get("r_package") and rec["r_package"] in by_rpkg:
            dup += 1
            continue
        if rec.get("source") == "authority" and not rec.get("r_package") and rec.get("url") and rec["url"] in by_auth_url:
            dup += 1
            continue
        entry = _entry_from_record(rec, taken)
        lib["entries"].append(entry)
        if entry["pmid"]:
            by_pmid[entry["pmid"]] = entry
        if entry["doi"]:
            by_doi[str(entry["doi"]).casefold()] = entry
        if entry.get("r_package"):
            by_rpkg[entry["r_package"]] = entry
        if entry.get("source") == "authority" and not entry.get("r_package") and entry.get("url"):
            by_auth_url[entry["url"]] = entry
        added += 1
    return added, dropped, dup


# ---------------------------------------------------------------------------
# exporters
# ---------------------------------------------------------------------------
BIB_ESCAPE = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"}


def _bib_escape(s: str) -> str:
    out = []
    for ch in s or "":
        out.append(BIB_ESCAPE.get(ch, ch))
    return "".join(out)


def to_bibtex(entries: list[dict]) -> str:
    chunks = ["% Generated from library.json. Do not edit by hand - regenerate with --export.\n"]
    for e in entries:
        btype = e.get("bib_type") or "article"
        authors = " and ".join(
            ("{" + _bib_escape(a["last"]) + "}" if a.get("collective") else
             "{" + _bib_escape(a["last"]) + "}, " +
             (_bib_escape(a["suffix"]) + ", " if a.get("suffix") else "") +
             _bib_escape(a.get("first") or a.get("initials", "")))
            for a in e.get("authors", []) if a.get("last")
        )
        fields = [
            ("author", authors),
            ("title", _bib_escape(e.get("title", ""))),
            ("journal" if btype == "article" else "organization", _bib_escape(e.get("journal", ""))),
            ("year", e.get("year", "")),
            ("volume", e.get("volume", "")),
            ("number", e.get("issue", "")),
            ("pages", (e.get("pages", "") or "").replace("-", "--")),
            ("doi", e.get("doi", "")),
            ("pmid", e.get("pmid", "")),
            ("url", e.get("url", "")),
        ]
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
        note = ""
        if e.get("flags"):
            note = f",\n  note = {{FLAGS: {', '.join(e['flags'])}}}"
        chunks.append(f"@{btype}{{{e['citekey']},\n{body}{note}\n}}\n")
    return "\n".join(chunks)


def to_ris(entries: list[dict]) -> str:
    out = []
    for e in entries:
        btype = e.get("bib_type") or "article"
        ty = "COMP" if btype == "manual" else "GEN" if btype == "misc" else "JOUR"
        lines = [f"TY  - {ty}"]
        for a in e.get("authors", []):
            if a.get("last"):
                name = a["last"] if a.get("collective") else (
                    f"{a['last']}, {a.get('first') or a.get('initials', '')}".strip(", ") +
                    (f", {a['suffix']}" if a.get("suffix") else ""))
                lines.append(f"AU  - {name}")
        lines += [
            f"TI  - {e.get('title', '')}",
            f"JO  - {e.get('journal', '')}",
            f"PY  - {e.get('year', '')}",
        ]
        for tag, key in (("VL", "volume"), ("IS", "issue"), ("SP", "pages"), ("DO", "doi"), ("UR", "url")):
            if e.get(key):
                lines.append(f"{tag}  - {e[key]}")
        if e.get("abstract"):
            lines.append(f"AB  - {e['abstract']}")
        if e.get("pmid"):
            lines.append(f"AN  - {e['pmid']}")
        lines.append(f"ID  - {e['citekey']}")
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


def export(lib: dict) -> None:
    entries = sorted(lib["entries"], key=lambda e: e["citekey"])
    (eu.refs_dir() / "refs.bib").write_text(to_bibtex(entries), encoding="utf-8")
    (eu.refs_dir() / "refs.ris").write_text(to_ris(entries), encoding="utf-8")
    print(f"exported {len(entries)} entries -> 06_refs/refs.bib, 06_refs/refs.ris")


def report(lib: dict) -> None:
    entries = lib["entries"]
    print(f"library: {len(entries)} entries")
    no_abs = [e["citekey"] for e in entries if not (e.get("abstract") or "").strip()]
    flagged = [(e["citekey"], e["flags"]) for e in entries if e.get("flags")]
    years = sorted(int(e["year"]) for e in entries if str(e.get("year", "")).isdigit())
    if years:
        recent = sum(1 for y in years if y >= years[-1] - 4)
        print(f"years  : {years[0]}-{years[-1]}  ({recent} from the last 5 years)")
    print(f"with abstract : {len(entries) - len(no_abs)}/{len(entries)}")
    if no_abs:
        print(f"  requires registered, identity-checked full text before citation: {', '.join(no_abs)}")
    if flagged:
        print("flagged records (do not cite as evidence):")
        for k, f in flagged:
            print(f"  {k}: {', '.join(f)}")
    orphans = used_citekeys() - {e["citekey"] for e in entries}
    if orphans:
        print(f"!! cited in the project but absent from the library: {', '.join(sorted(orphans))}")
    print("\njournals:")
    from collections import Counter
    for name, n in Counter(e.get("journal", "?") for e in entries).most_common(15):
        print(f"  {n:>3}  {name}")


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="build and export the verified reference library")
    ap.add_argument("--topic", help="primary topic; runs a small family of queries")
    ap.add_argument("--add-query", action="append", default=[], help="one extra query (repeatable)")
    ap.add_argument("--add-ids", help="comma-separated PMIDs to add directly")
    ap.add_argument("--add-dois", help="comma-separated DOIs resolved via Crossref for non-PubMed references")
    ap.add_argument("--methodology", action="store_true",
                    help="mark --add-dois records as foundational statistical/methodological DOI citations")
    ap.add_argument("--add-r-citation", action="append", default=[], metavar="PACKAGE",
                    help="add verified R software/package citation via Rscript citation() (use 'R' for base R)")
    ap.add_argument("--add-authority-url", help="add official guideline/dictionary/regulatory URL snapshot")
    ap.add_argument("--authority-title", default="", help="exact official document title for --add-authority-url")
    ap.add_argument("--authority-year", default="", help="publication/release year for --add-authority-url")
    ap.add_argument("--authority-author", default="", help="issuing authority/organization for --add-authority-url")
    ap.add_argument("--authority-journal", default="Official Guideline / Regulatory Standard",
                    help="container/series label for --add-authority-url")
    ap.add_argument("--pool-role", choices=["candidate", "core"], default="",
                    help="tag newly added entries with pool_role ('candidate' entries do not require per-item uncited prose reasons)")
    ap.add_argument("--archive-uncited", action="store_true",
                    help="record batch candidate-pool explanation in 06_refs/usage.json for all uncited library entries without touching library.json")
    ap.add_argument("--archive-reason",
                    default="Screened in verified candidate literature/benchmark pool; retained un-cited in final prose to avoid citation padding.",
                    help="explanation string (>=20 chars) used by --archive-uncited")
    ap.add_argument("--target", type=int, help="legacy advisory planning hint; never skips remaining coverage queries")
    ap.add_argument("--retmax", type=int, default=60, help="records to pull per query")
    ap.add_argument("--years", type=int, help="restrict searches to the last N years")
    ap.add_argument("--export", action="store_true", help="regenerate refs.bib and refs.ris")
    ap.add_argument("--report", action="store_true", help="audit the current library")
    ap.add_argument("--uncited-reason", nargs=2, action="append", default=[], metavar=("CITEKEY","REASON"), help="record why a genuine library entry is not cited; does not modify metadata")
    ap.add_argument("--drop", action="append", default=[], help="remove a citekey")
    args = ap.parse_args()

    lib = load_library()
    if args.archive_uncited:
        if args.topic or args.add_query or args.add_ids or args.add_dois or args.add_r_citation or args.add_authority_url or args.drop or args.export:
            raise ValueError("Run --archive-uncited separately from metadata acquisition/export")
        reason_str = args.archive_reason.strip()
        if len(reason_str) < 20:
            raise ValueError("--archive-reason must be at least 20 characters")
        from wfcore.readiness import atomic_json
        cited = set()
        for sec in ("introduction", "methods", "results", "discussion", "abstract", "supplementary_methods"):
            sec_path = eu.project_root() / f"07_manuscript/{sec}.md"
            if sec_path.is_file():
                for m in re.finditer(r"\[([^\]]*@[^\]]*)\]", sec_path.read_text(encoding="utf-8", errors="replace")):
                    cited.update(CITE_RE.findall(m.group(1)))
        usage = eu.project_root() / "06_refs/usage.json"
        record = json.loads(usage.read_text(encoding="utf-8")) if usage.is_file() else {"uncited_reasons": {}}
        reasons = record.setdefault("uncited_reasons", {})
        recorded_n = 0
        for e in lib.get("entries", []):
            ck = e.get("citekey", "")
            if ck and ck not in cited and len(str(reasons.get(ck, "")).strip()) < 20:
                reasons[ck] = reason_str
                recorded_n += 1
        atomic_json(usage, record)
        print(f"Archived {recorded_n} uncited candidate entry/entries in 06_refs/usage.json; library.json unchanged.")
        return 0

    if args.uncited_reason:
        if args.topic or args.add_query or args.add_ids or args.add_dois or args.add_r_citation or args.add_authority_url or args.drop or args.export:
            raise ValueError("Record usage separately from metadata acquisition/export")
        from wfcore.readiness import atomic_json
        usage=eu.project_root()/"06_refs/usage.json"
        record=json.loads(usage.read_text(encoding="utf-8")) if usage.is_file() else {"uncited_reasons":{}}
        for key,reason in args.uncited_reason:
            if key not in {e["citekey"] for e in lib["entries"]} or len(reason.strip())<20:
                raise ValueError("Uncited reason needs an existing citekey and concrete explanation")
            record["uncited_reasons"][key]=reason
        atomic_json(usage,record)
        print("Uncited usage explanations recorded; verified bibliographic metadata unchanged")
        return 0

    for key in args.drop:
        before = len(lib["entries"])
        lib["entries"] = [e for e in lib["entries"] if e["citekey"] != key]
        print(f"dropped {key}" if len(lib["entries"]) < before else f"{key} not in library")

    queries: list[str] = []
    if args.topic:
        queries += [
            args.topic,
            f"{args.topic} AND (epidemiology OR prevalence OR incidence)",
            f"{args.topic} AND (cohort OR cross-sectional OR case-control)",
            f"{args.topic} AND (systematic review OR meta-analysis)",
            f"{args.topic} AND (guideline OR consensus OR definition)",
        ]
    queries += args.add_query

    for q in queries:
        res = eu.esearch(q, retmax=args.retmax, years=args.years)
        recs = eu.efetch(res["ids"])
        if args.pool_role:
            for r in recs:
                r["pool_role"] = args.pool_role
        added, dropped, dup = add_records(lib, recs)
        lib.setdefault("queries", []).append(
            {"query": q, "at": eu.now(), "hits": res["count"], "added": added,
             "dropped_no_abstract": dropped, "duplicates": dup,
             "cache_file": res["cache_file"]}
        )
        print(f"[{q[:60]}] hits={res['count']} +{added} added, "
              f"{dup} duplicate(s); records without abstracts await full-text verification")

    if args.add_ids:
        ids = [x for x in args.add_ids.replace(" ", "").split(",") if x]
        recs = eu.efetch(ids)
        if args.pool_role:
            for r in recs:
                r["pool_role"] = args.pool_role
        added, dropped, dup = add_records(lib, recs)
        print(f"[--add-ids] +{added} added, {dup} already present; no-abstract records require registered full text")

    if args.add_dois:
        dois = [x.strip() for x in args.add_dois.split(",") if x.strip()]
        recs = []
        for doi in dois:
            rec = eu.crossref_fetch(doi, fresh=False, purpose="discovery")
            if rec is None:
                eu.die(f"DOI not resolvable via Crossref: {doi}")
            if args.methodology:
                rec["authority_kind"] = "methodology_doi"
            if args.pool_role:
                rec["pool_role"] = args.pool_role
            recs.append(rec)
        added, _, dup = add_records(lib, recs)
        print(f"[--add-dois] +{added} Crossref DOI record(s) added, {dup} already present")

    if args.add_r_citation:
        recs = []
        for pkg in args.add_r_citation:
            rec = eu.r_citation_record(pkg, fresh=False, purpose="discovery")
            if args.pool_role:
                rec["pool_role"] = args.pool_role
            recs.append(rec)
        added, _, dup = add_records(lib, recs)
        print(f"[--add-r-citation] +{added} R software citation(s) added, {dup} already present")

    if args.add_authority_url:
        if not (args.authority_title.strip() and args.authority_year.strip() and args.authority_author.strip()):
            eu.die("--add-authority-url requires --authority-title, --authority-year, and --authority-author")
        rec = eu.authority_url_record(
            args.add_authority_url,
            title=args.authority_title,
            year=args.authority_year,
            author=args.authority_author,
            journal=args.authority_journal,
            fresh=False,
            purpose="discovery",
        )
        if args.pool_role:
            rec["pool_role"] = args.pool_role
        added, _, dup = add_records(lib, [rec])
        print(f"[--add-authority-url] +{added} official authority snapshot added, {dup} already present")

    missing = used_citekeys() - {e["citekey"] for e in lib["entries"]}
    if missing:
        print(f"\n!! {len(missing)} citekey(s) are cited in the project but not in the library:")
        print("   " + ", ".join(sorted(missing)))
        print("   Add them with --add-ids <pmid> / --add-dois <doi>, or fix the citation. Never leave a dangling key.")

    save_library(lib)
    if args.export or queries or args.add_ids or args.add_dois or args.add_r_citation or args.add_authority_url or args.drop:
        export(lib)
    if args.report:
        report(lib)

    n = len(lib["entries"])
    print(f"\nlibrary now holds {n} entr{'y' if n == 1 else 'ies'} "
          f"-> next: uv run python tools/pubmed/verify.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
