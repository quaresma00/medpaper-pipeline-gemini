#!/usr/bin/env python3
r"""Fetch open-access full text for the deep-read papers.

Legal open-access routes only, tried in order: Europe PMC / PMC OA -> Unpaywall ->
OpenAlex. Paywalled papers are recorded as paywalled; they are never
silently treated as read.

    uv run python tools\pubmed\fulltext.py fetch --citekey smith2023
    uv run python tools\pubmed\fulltext.py register --citekey smith2023 \
        --file paper.pdf --access oa --source-url https://example.org/article
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pubmed import eutils as eu  # noqa: E402
from pubmed.identity import inspect, norm  # noqa: E402
from wfcore.readiness import atomic_json  # noqa: E402

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
UNPAYWALL = "https://api.unpaywall.org/v2"
OPENALEX = "https://api.openalex.org/works"
MANIFEST = "retrieval_manifest.json"


def out_dir() -> Path:
    d = eu.project_root() / "06_refs" / "fulltext"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(name: str, blob: bytes, entry: dict) -> str:
    identity = inspect(entry, blob, Path(name).suffix)
    if identity["status"] == "mismatch":
        raise ValueError("Wrong article identity; previous full text preserved")
    p = out_dir() / name
    temporary = p.with_suffix(p.suffix + ".tmp")
    temporary.write_bytes(blob)
    temporary.replace(p)
    return f"06_refs/fulltext/{name}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_retrieval(entry: dict, result: dict) -> dict:
    """Upsert a machine-verifiable provenance record for a retrieval result."""
    path = out_dir() / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    records = {r.get("citekey"): r for r in data.get("retrievals", []) if r.get("citekey")}
    record = {
        "citekey": entry["citekey"],
        "pmid": entry.get("pmid", ""),
        "doi": entry.get("doi", ""),
        "route": result.get("route", ""),
        "access": result.get("access", ""),
        "fulltext": result.get("fulltext", ""),
        "source_url": result.get("source_url", ""),
        "authorization_note": result.get("authorization_note", ""),
        "retrieved_at": _now(),
    }
    if entry.get("cache_file"):
        metadata = eu.project_root() / entry["cache_file"]
        record["metadata_cache"] = entry["cache_file"]
        record["metadata_sha256"] = _sha256(metadata)
    source = record["fulltext"]
    if source and not str(source).startswith("http"):
        local = eu.project_root() / source
        if local.is_file():
            record["bytes"] = local.stat().st_size
            record["sha256"] = _sha256(local)
            record["identity"] = inspect(entry, local.read_bytes(), local.suffix)
            prior = records.get(entry["citekey"], {})
            if prior.get("sha256") == record["sha256"] and prior.get("identity_confirmation"):
                record["identity_confirmation"] = prior["identity_confirmation"]
    records[entry["citekey"]] = record
    payload = {"schema": 1, "updated_at": _now(),
               "retrievals": [records[k] for k in sorted(records)]}
    atomic_json(path, payload)
    return record


# ---------------------------------------------------------------------------
def try_europepmc(entry: dict) -> dict | None:
    pmid, pmcid = entry.get("pmid"), entry.get("pmcid")
    if not pmcid and pmid:
        try:
            raw = eu.http_get(f"{EPMC}/search",
                              {"query": f"EXT_ID:{pmid}", "format": "json", "resultType": "core"})
            hits = json.loads(raw).get("resultList", {}).get("result", [])
            if hits:
                pmcid = hits[0].get("pmcid") or ""
                if hits[0].get("isOpenAccess") != "Y" and not pmcid:
                    return None
        except Exception:  # noqa: BLE001
            return None
    if not pmcid:
        return None
    pmcid = pmcid if pmcid.upper().startswith("PMC") else f"PMC{pmcid}"
    for kind, url, ext in (
        ("xml", f"{EPMC}/{pmcid}/fullTextXML", "xml"),
        ("pdf", f"{EPMC}/{pmcid}/pdf", "pdf"),
    ):
        try:
            blob = eu.http_get(url)
        except Exception:  # noqa: BLE001
            continue
        if len(blob) < 2000:
            continue
        rel = _save(f"{entry['citekey']}.{ext}", blob, entry)
        return {"route": f"europepmc-{kind}", "access": "oa", "fulltext": rel,
                "bytes": len(blob), "pmcid": pmcid, "source_url": url}
    return None


def try_unpaywall(entry: dict) -> dict | None:
    doi, email = entry.get("doi"), eu.api_email()
    if not doi or not email:
        return None
    try:
        raw = eu.http_get(f"{UNPAYWALL}/{urllib.parse.quote(doi)}", {"email": email})
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    loc = data.get("best_oa_location") or {}
    url = loc.get("url_for_pdf") or loc.get("url")
    if not url:
        return None
    try:
        blob = eu.http_get(url)
    except Exception:  # noqa: BLE001
        return {"route": "unpaywall-link", "access": "link-only", "fulltext": url,
                "source_url": url,
                "note": "OA landing page found but the file could not be downloaded here"}
    ext = "pdf" if blob[:4] == b"%PDF" else "html"
    return {"route": "unpaywall", "access": "oa",
            "fulltext": _save(f"{entry['citekey']}.{ext}", blob, entry), "bytes": len(blob),
            "license": loc.get("license"), "version": loc.get("version"),
            "source_url": url}


def try_openalex(entry: dict) -> dict | None:
    doi = entry.get("doi")
    if not doi:
        return None
    try:
        raw = eu.http_get(f"{OPENALEX}/doi:{urllib.parse.quote(doi)}",
                          {"mailto": eu.api_email() or ""})
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    loc = data.get("best_oa_location") or {}
    url = loc.get("pdf_url") or loc.get("landing_page_url")
    if not url:
        return None
    try:
        blob = eu.http_get(url)
        ext = "pdf" if blob[:4] == b"%PDF" else "html"
        return {"route": "openalex", "access": "oa",
                "fulltext": _save(f"{entry['citekey']}.{ext}", blob, entry), "bytes": len(blob),
                "source_url": url}
    except Exception:  # noqa: BLE001
        return {"route": "openalex-link", "access": "link-only", "fulltext": url,
                "source_url": url}


SCIHUB_MIRRORS = ("https://sci-hub.se", "https://sci-hub.st", "https://sci-hub.ru")
CAPTCHA_MARKERS = ("captcha", "verify you are human", "cloudflare", "just a moment", "ddos-guard", "g-recaptcha", "hcaptcha")


def _extract_scihub_pdf_url(html: str, base_url: str) -> str | None:
    from urllib.parse import urljoin
    for pat in (
        r'(?:<embed|<iframe)[^>]+src=["\']([^"\']+?\.pdf[^"\']*)["\']',
        r'(?:<embed|<iframe)[^>]+src=["\']([^"\']+)["\']',
        r"location\.href\s*=\s*['\"]([^'\"]+\.pdf[^'\"]*)['\"]",
        r'href=["\']([^"\']+\.pdf[^"\']*)["\']',
    ):
        m = re.search(pat, html, re.I)
        if m:
            candidate = m.group(1).strip()
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            return urljoin(base_url + "/", candidate)
    return None


def try_scihub(entry: dict) -> dict | None:
    """Attempt DOI resolution across Sci-Hub mirrors; abort immediately on any CAPTCHA/anti-bot gate."""
    doi = (entry.get("doi") or "").strip()
    if not doi:
        return None
    import urllib.error
    import urllib.request
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MedPaperResearch/1.30)"}
    saw_captcha = False
    for mirror in SCIHUB_MIRRORS:
        target = f"{mirror.rstrip('/')}/{doi}"
        try:
            req = urllib.request.Request(target, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                raw = resp.read(2_500_000)
                if raw[:4] == b"%PDF" or "application/pdf" in ctype:
                    pdf_bytes = raw
                    pdf_url = target
                else:
                    html = raw.decode("utf-8", errors="replace")
                    low = html.lower()
                    if any(marker in low for marker in CAPTCHA_MARKERS):
                        saw_captcha = True
                        continue
                    pdf_url = _extract_scihub_pdf_url(html, mirror)
                    if not pdf_url:
                        continue
                    req2 = urllib.request.Request(pdf_url, headers=headers)
                    with urllib.request.urlopen(req2, timeout=20) as resp2:
                        pdf_bytes = resp2.read(25_000_000)
                if len(pdf_bytes) < 1000 or pdf_bytes[:4] != b"%PDF":
                    continue
                if inspect(entry, pdf_bytes, ".pdf")["status"] == "mismatch":
                    continue
                dest = out_dir() / f"{entry['citekey']}.pdf"
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".pdf.tmp")
                tmp.write_bytes(pdf_bytes)
                tmp.replace(dest)
                return {
                    "route": "scihub",
                    "access": "authorized",
                    "fulltext": f"06_refs/fulltext/{dest.name}",
                    "source_url": pdf_url,
                    "authorization_note": f"Full-text PDF retrieved via {mirror} DOI lookup; automated identity verified.",
                    "note": "retrieved via Sci-Hub DOI fallback; verify PDF text clarity during deep read.",
                }
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
    if saw_captcha:
        return {
            "route": "scihub_captcha_blocked",
            "access": "captcha_or_blocked",
            "fulltext": f"https://doi.org/{doi}",
            "source_url": f"https://doi.org/{doi}",
            "note": "Sci-Hub mirror returned an anti-bot/CAPTCHA gate; skipped automatically per policy. Request PDF from user.",
        }
    return None


ROUTES = (try_europepmc, try_unpaywall, try_openalex, try_scihub)


def fetch_one(entry: dict) -> dict:
    captcha_note = None
    for fn in ROUTES:
        try:
            res = fn(entry)
        except Exception as exc:  # noqa: BLE001
            res = None
            print(f"    {fn.__name__} raised {type(exc).__name__}: {exc}")
        if res and res.get("access") in {"oa", "authorized"}:
            return res
        if res and res.get("access") == "captcha_or_blocked":
            captcha_note = res
    if captcha_note:
        return captcha_note
    doi = entry.get("doi")
    return {
        "route": "none", "access": "paywalled",
        "fulltext": f"https://doi.org/{doi}" if doi else "",
        "source_url": f"https://doi.org/{doi}" if doi else "",
        "note": "no OA or Sci-Hub full text found. Ask the user to provide the PDF and register via "
                "`fulltext.py register`; an abstract or link is not a deep read.",
    }


NOTES_TEMPLATE = """# {citekey} - {short_title}

Source: {source}
Access: {access} (route: {route})
PMID {pmid} | DOI {doi}

## Design and population

## What they did differently from us

## Their key numbers

## How this supports or contradicts our finding

## What a reviewer would take from this
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="fetch open-access full text for deep reading")
    ap.add_argument("command", nargs="?", choices=("fetch", "register", "confirm"), default="fetch")
    ap.add_argument("--confirmed-by", help="actual reader who explicitly confirmed article identity")
    ap.add_argument("--identity-note", help="concrete first-page/title/authors/identifier evidence, >=30 chars")
    ap.add_argument("--citekey", action="append", default=[])
    ap.add_argument("--pmid", action="append", default=[], help="comparator-only fresh PubMed route; does not edit the scientific library")
    ap.add_argument("--all-deepread", action="store_true",
                    help="fetch everything listed in deepread_index.json")
    ap.add_argument("--no-stub", action="store_true", help="do not create the notes stub")
    ap.add_argument("--file", type=Path, help="local PDF/XML/HTML to register")
    ap.add_argument("--access", choices=("oa", "authorized"),
                    help="legal access basis for a registered file")
    ap.add_argument("--source-url", help="landing page or authoritative source URL")
    ap.add_argument("--route", default="external", help="acquisition route, e.g. scansci-pdf")
    ap.add_argument("--authorization-note",
                    help="required for institutionally authorized full text")
    ap.add_argument("--replace-existing", action="store_true",
                    help="replace a different previously registered file for this citekey")
    args = ap.parse_args()

    lib_path = eu.refs_dir() / "library.json"
    entries = {e["citekey"]: e for e in json.loads(lib_path.read_text(encoding="utf-8")).get("entries", [])} if lib_path.is_file() else {}

    keys = list(args.citekey)
    # Comparator-only acquisition must not mutate a frozen scientific bibliography.
    if args.pmid:
        fetched = eu.efetch(args.pmid, fresh=True, purpose="benchmark")
        if {str(e["pmid"]) for e in fetched} != set(args.pmid):
            eu.die("Comparator metadata retrieval incomplete; never replace missing IDs with invented entries")
        for entry in fetched:
            key = "benchmark" + str(entry["pmid"])
            entry["citekey"] = key; entries[key] = entry; keys.append(key)
    dr_path = eu.project_root() / "06_refs" / "deepread" / "deepread_index.json"
    if args.all_deepread:
        if not dr_path.exists():
            eu.die("deepread_index.json missing; pass --citekey instead")
        keys += [i["citekey"] for i in json.loads(dr_path.read_text(encoding="utf-8")).get("selected", [])]
    if not keys:
        eu.die("give at least one --citekey (or --all-deepread)")

    if args.command == "confirm":
        if len(keys) != 1 or not (args.confirmed_by or "").strip() or len((args.identity_note or "").strip()) < 30:
            eu.die("confirm requires one citekey and actual --confirmed-by / --identity-note; do not invent user confirmation")
        key = keys[0]
        entry = entries.get(key)
        data = json.loads((out_dir() / MANIFEST).read_text(encoding="utf-8"))
        record = next((r for r in data["retrievals"] if r["citekey"] == key), None)
        if not entry or not record:
            eu.die("Library entry / registration missing")
        from wfcore.packagefreeze import _safe_path
        local = _safe_path(eu.project_root(), record["fulltext"])[1]
        if record.get("sha256") != _sha256(local) or inspect(entry, local.read_bytes(), local.suffix)["status"] == "mismatch":
            eu.die("Changed file or contradictory article identity; confirmation rejected")
        record["identity_confirmation"] = {"confirmed_by": args.confirmed_by.strip(), "note": args.identity_note.strip(),
            "sha256": record["sha256"], "expected": {k: norm(k, entry.get(k)) for k in ("doi", "pmid", "pmcid", "title")},
            "confirmed_at": _now()}
        atomic_json(out_dir() / MANIFEST, data)
        print(f"{key}: explicit reader confirmation recorded for the exact registered file")
        return 0

    if args.command == "register":
        if len(keys) != 1 or not args.file or not args.access or not args.source_url:
            eu.die("register requires one --citekey plus --file, --access and --source-url")
        if args.access == "authorized" and not (args.authorization_note or "").strip():
            eu.die("--authorization-note is required when --access authorized")
        if not re.match(r"^https?://", args.source_url, re.I):
            eu.die("--source-url must be an http(s) URL")
        key = keys[0]
        entry = entries.get(key)
        if not entry:
            eu.die(f"{key}: not in library.json - fetch it with build_library.py --add-ids before registration; verify after full-text registration")
        source = args.file.expanduser().resolve()
        if not source.is_file():
            eu.die(f"file not found: {source}")
        suffix = source.suffix.lower()
        if suffix not in {".pdf", ".xml", ".html", ".htm"}:
            eu.die("registered full text must be PDF, XML or HTML")
        if source.stat().st_size < 1000:
            eu.die("registered full text is implausibly small (<1000 bytes)")
        if suffix == ".pdf":
            with source.open("rb") as stream:
                if stream.read(4) != b"%PDF":
                    eu.die("file has a .pdf suffix but no PDF signature")
        dest = out_dir() / f"{key}{suffix}"
        if inspect(entry, source.read_bytes(), suffix)["status"] == "mismatch":
            eu.die("Wrong article identity; registration rejected and previous full text preserved")
        if dest.exists() and source != dest.resolve() and _sha256(dest) != _sha256(source):
            if not args.replace_existing:
                eu.die(f"{dest.name} already exists with different content; inspect it or pass "
                       "--replace-existing explicitly")
        if source != dest.resolve():
            temporary = dest.with_suffix(dest.suffix + ".tmp")
            shutil.copy2(source, temporary)
            temporary.replace(dest)
        result = {
            "route": args.route.strip() or "external",
            "access": args.access,
            "fulltext": f"06_refs/fulltext/{dest.name}",
            "source_url": args.source_url,
            "authorization_note": (args.authorization_note or "").strip(),
        }
        record = record_retrieval(entry, result)
        print(f"{key}: registered {record['fulltext']}")
        print(f"    route={record['route']} access={record['access']} sha256={record['sha256']}")
        if not args.no_stub:
            notes = eu.project_root() / "06_refs" / "deepread" / f"{key}.md"
            notes.parent.mkdir(parents=True, exist_ok=True)
            if not notes.exists():
                notes.write_text(NOTES_TEMPLATE.format(
                    citekey=key,
                    short_title=re.sub(r"\s+", " ", entry.get("title", ""))[:80],
                    source=f"{entry.get('journal', '')} {entry.get('year', '')}",
                    access=result["access"], route=result["route"],
                    pmid=entry.get("pmid", ""), doi=entry.get("doi", ""),
                ), encoding="utf-8")
                print(f"    notes stub: 06_refs/deepread/{key}.md")
        return 0

    results = {}
    failed = []
    for key in dict.fromkeys(keys):
        entry = entries.get(key)
        if not entry:
            print(f"{key}: not in library.json - add it before deep-reading")
            failed.append(key)
            continue
        print(f"{key}: {entry.get('title', '')[:70]}")
        res = fetch_one(entry)
        record_retrieval(entry, res)
        results[key] = res
        source = res.get("fulltext", "")
        if res.get("access") not in {"oa", "authorized"} or not source or source.startswith("http") or not (eu.project_root() / source).is_file():
            failed.append(key)
        print(f"    -> {res['route']} / {res['access']} / {res.get('fulltext', '')}")
        if res.get("note"):
            print(f"       {res['note']}")

        if not args.no_stub:
            notes = eu.project_root() / "06_refs" / "deepread" / f"{key}.md"
            notes.parent.mkdir(parents=True, exist_ok=True)
            if not notes.exists():
                notes.write_text(NOTES_TEMPLATE.format(
                    citekey=key,
                    short_title=re.sub(r"\s+", " ", entry.get("title", ""))[:80],
                    source=f"{entry.get('journal', '')} {entry.get('year', '')}",
                    access=res["access"], route=res["route"],
                    pmid=entry.get("pmid", ""), doi=entry.get("doi", ""),
                ), encoding="utf-8")
                print(f"       notes stub: 06_refs/deepread/{key}.md")

    oa = sum(1 for r in results.values() if r["access"] == "oa")
    auth = sum(1 for r in results.values() if r["access"] == "authorized")
    print(f"\n{oa}/{len(results)} open-access, {auth}/{len(results)} retrieved/authorized local full texts.")
    print("Fill in every notes file, then record them in 06_refs/deepread/deepread_index.json.")
    print("Notes under 400 characters are rejected by the S15 gate.")
    req_json = eu.project_root() / ".wf/pending_fulltext_requests.json"
    req_md = eu.project_root() / ".wf/pending_fulltext_requests.md"
    if failed:
        missing_rows = []
        md_lines = ["# Pending Full-Text PDFs Required From User", "",
                    "Automated OA + Sci-Hub retrieval could not obtain the following full texts (paywall or anti-bot gate).",
                    "Please download the PDF(s) and supply their file path(s) to register:", ""]
        for key in failed:
            ent = entries.get(key, {})
            res = results.get(key, {})
            doi = ent.get("doi", "")
            pmid = ent.get("pmid", "")
            title = re.sub(r"\s+", " ", ent.get("title", "")).strip()
            row = {
                "citekey": key,
                "pmid": str(pmid),
                "doi": doi,
                "doi_url": f"https://doi.org/{doi}" if doi else "",
                "title": title,
                "route": res.get("route", "none"),
                "reason": res.get("note", "not retrieved"),
            }
            missing_rows.append(row)
            md_lines.append(f"- **{key}** | PMID: `{pmid or 'N/A'}` | DOI: `{doi or 'N/A'}` ({row['doi_url'] or 'no DOI'})")
            md_lines.append(f"  - Title: {title or '(unknown)'}")
            md_lines.append(f"  - Reason: {row['reason']}")
            md_lines.append(f"  - Register command: `uv run python tools/pubmed/fulltext.py register --citekey {key} --file <path/to/{key}.pdf> --access authorized --route user-provided --source-url {row['doi_url'] or 'https://pubmed.ncbi.nlm.nih.gov/' + str(pmid)} --authorization-note \"User-supplied institutional/subscribed PDF\"`")
        atomic_json(req_json, {"pending": missing_rows})
        req_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        print(f"Pending user PDF request checklist written to project/.wf/pending_fulltext_requests.md ({len(missing_rows)} item(s))")
        print("Incomplete full-text acquisition: " + ", ".join(failed) + "; ask the user to supply these PDFs via `fulltext.py register`; genuine partial receipts preserved")
        return 2
    for stale in (req_json, req_md):
        if stale.is_file():
            stale.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
