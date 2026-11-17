"""NCBI E-utilities + Crossref access. Stdlib only (urllib + ElementTree).

Every response is written to project/06_refs/cache/ before it is parsed, and every
search appends to scan_manifest.json. That cache is the evidence the gates inspect:
a claim about the literature that has no cached payload behind it is treated as
fabricated.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CROSSREF = "https://api.crossref.org/works"
TOOL = "medpaper-codex-pipeline"
UA = f"{TOOL}/1.0 (research pipeline; contact via NCBI_API_EMAIL)"

_last_call = [0.0]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_global_env_var(*names: str) -> str | None:
    for name in names:
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    for env_path in (Path.home() / ".env", Path.home() / ".gemini" / ".env"):
        if not env_path.is_file():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in names and v:
                    os.environ.setdefault(k, v)
                    return v
        except OSError:
            continue
    return None


def api_key() -> str | None:
    return _load_global_env_var("NCBI_API_KEY", "PUBMED_API_KEY")


def api_email() -> str | None:
    return _load_global_env_var("NCBI_API_EMAIL", "PUBMED_API_EMAIL")


def _min_interval() -> float:
    # NCBI: 3 requests/second without a key, 10/second with one. Stay under.
    return 0.12 if api_key() else 0.36


def _throttle() -> None:
    wait = _min_interval() - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def http_get(url: str, params: dict | None = None, retries: int = 4, timeout: int = 60) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, '')})}"
    last: Exception | None = None
    for attempt in range(retries):
        _throttle()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url} ({last})")


# ---------------------------------------------------------------------------
# project paths / cache
# ---------------------------------------------------------------------------
def repo_root() -> Path:
    env = os.environ.get("MEDPAPER_ROOT")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[2]


def project_root() -> Path:
    env = os.environ.get("MEDPAPER_PROJECT")
    return Path(env).resolve() if env else repo_root() / "project"


def cache_dir() -> Path:
    d = project_root() / "06_refs" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def refs_dir() -> Path:
    d = project_root() / "06_refs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _digest(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()[:16]


def cached(name: str, fetch, binary: bool = False, refresh: bool = False):
    """Return a payload and cache it; ``refresh`` always contacts the source first."""
    p = cache_dir() / name
    if not refresh and p.exists() and p.stat().st_size > 0:
        return p.read_bytes() if binary else p.read_text(encoding="utf-8")
    blob = fetch()
    tmp = p.with_suffix(p.suffix + ".tmp")
    if isinstance(blob, str):
        # Write exact UTF-8 bytes. Text-mode writes on Windows can translate LF
        # to CRLF, making a receipt hash computed from the response disagree with
        # the raw payload that was actually preserved on disk.
        tmp.write_bytes(blob.encode("utf-8"))
    else:
        tmp.write_bytes(blob)
    tmp.replace(p)
    return blob if binary or isinstance(blob, str) else blob.decode("utf-8", "replace")


def manifest_path() -> Path:
    return cache_dir() / "scan_manifest.json"


def load_manifest() -> dict:
    p = manifest_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"created_at": now(), "queries": []}


def append_manifest(entry: dict) -> None:
    man = load_manifest()
    man.setdefault("queries", []).append(entry)
    man["updated_at"] = now()
    manifest_path().write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# E-utilities
# ---------------------------------------------------------------------------
def esearch(query: str, retmax: int = 100, years: int | None = None, db: str = "pubmed",
            sort: str = "relevance", record: bool = True) -> dict:
    params = {
        "db": db, "term": query, "retmax": retmax, "retmode": "json",
        "sort": sort, "tool": TOOL, "email": api_email(), "api_key": api_key(),
    }
    if years:
        params["reldate"] = int(years) * 365
        params["datetype"] = "pdat"
    name = f"esearch_{db}_{_digest(query, str(retmax), str(years), sort)}.json"
    raw = cached(name, lambda: http_get(f"{EUTILS}/esearch.fcgi", params).decode("utf-8", "replace"))
    data = json.loads(raw)
    res = data.get("esearchresult", {})
    ids = res.get("idlist", [])
    out = {
        "query": query, "db": db, "at": now(), "retmax": retmax, "years": years,
        "count": int(res.get("count", 0) or 0), "ids": ids, "cache_file": f"06_refs/cache/{name}",
        "translation": res.get("querytranslation", ""),
    }
    if record:
        append_manifest(out)
    return out


def efetch(pmids: list[str], db: str = "pubmed", *, fresh: bool = False,
           purpose: str = "discovery") -> list[dict]:
    """Fetch full MEDLINE records in batches of 200.

    Ordinary discovery calls may reuse the cache.  Verification calls must pass
    ``fresh=True``; those responses receive unique ``verify_`` cache names and
    carry a payload hash that the workflow gate reparses independently.
    """
    out: list[dict] = []
    pmids = [str(p).strip() for p in pmids if str(p).strip()]
    for i in range(0, len(pmids), 200):
        batch = pmids[i:i + 200]
        clean_purpose = re.sub(r"[^a-z0-9_-]", "", purpose.casefold()) or "discovery"
        if fresh:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            name = f"{clean_purpose}_efetch_{db}_{_digest(','.join(batch))}_{stamp}.xml"
        else:
            name = f"efetch_{db}_{_digest(','.join(batch))}.xml"
        params = {
            "db": db, "id": ",".join(batch), "retmode": "xml",
            "tool": TOOL, "email": api_email(), "api_key": api_key(),
        }
        raw = cached(
            name,
            lambda: http_get(f"{EUTILS}/efetch.fcgi", params).decode("utf-8", "replace"),
            refresh=fresh,
        )
        # Receipts bind to the actual preserved source bytes, never to a
        # newline-normalized in-memory string.
        digest = hashlib.sha256((cache_dir() / name).read_bytes()).hexdigest()
        records = parse_pubmed_xml(raw, cache_file=f"06_refs/cache/{name}")
        for record in records:
            record["cache_sha256"] = digest
            record["fresh_fetch"] = fresh
        out.extend(records)
    return out


def parse_pubmed_xml(xml_text: str, cache_file: str = "") -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"unparseable PubMed XML: {exc}")
    records = []
    for art in root.iter("PubmedArticle"):
        records.append(_one_record(art, cache_file))
    for art in root.iter("PubmedBookArticle"):
        rec = _one_record(art, cache_file)
        rec["type"] = "book"
        records.append(rec)
    return records


def _text(node, path: str, default: str = "") -> str:
    el = node.find(path)
    if el is None:
        return default
    return "".join(el.itertext()).strip()


def _one_record(art, cache_file: str) -> dict:
    pmid = _text(art, ".//MedlineCitation/PMID")
    title = _text(art, ".//Article/ArticleTitle") or _text(art, ".//BookTitle")

    parts = []
    for ab in art.findall(".//Article/Abstract/AbstractText"):
        label = ab.get("Label")
        body = "".join(ab.itertext()).strip()
        if body:
            parts.append(f"{label}: {body}" if label else body)
    abstract = "\n".join(parts).strip()

    authors = []
    for a in art.findall(".//AuthorList/Author"):
        coll = _text(a, "CollectiveName")
        if coll:
            authors.append({"last": coll, "first": "", "collective": True})
            continue
        last, fore = _text(a, "LastName"), _text(a, "ForeName")
        if last:
            authors.append({"last": last, "first": fore, "initials": _text(a, "Initials"),
                            "suffix": _text(a, "Suffix")})

    year = _text(art, ".//Journal/JournalIssue/PubDate/Year")
    if not year:
        m = re.search(r"(19|20)\d{2}", _text(art, ".//Journal/JournalIssue/PubDate/MedlineDate"))
        year = m.group(0) if m else ""

    doi = ""
    for el in art.findall(".//ELocationID"):
        if el.get("EIdType") == "doi":
            doi = (el.text or "").strip()
    pmcid = ""
    for el in art.findall(".//ArticleIdList/ArticleId"):
        t = el.get("IdType")
        if t == "doi" and not doi:
            doi = (el.text or "").strip()
        elif t == "pmc":
            pmcid = (el.text or "").strip()

    ptypes = [(_p.text or "").strip() for _p in art.findall(".//PublicationTypeList/PublicationType")]
    corrections = [c.get("RefType", "") for c in art.findall(".//CommentsCorrectionsList/CommentsCorrections")]
    flags = []
    if any("Retract" in t for t in ptypes) or "RetractionIn" in corrections:
        flags.append("RETRACTED_OR_RETRACTION")
    if "ExpressionOfConcernIn" in corrections:
        flags.append("EXPRESSION_OF_CONCERN")
    if "Preprint" in ptypes:
        flags.append("PREPRINT")

    return {
        "pmid": pmid,
        "doi": doi.lower(),
        "pmcid": pmcid,
        "title": re.sub(r"\s+", " ", title).strip().rstrip("."),
        "abstract": abstract,
        "authors": authors,
        "journal": _text(art, ".//Journal/Title"),
        "journal_abbrev": _text(art, ".//Journal/ISOAbbreviation"),
        "year": year,
        "volume": _text(art, ".//JournalIssue/Volume"),
        "issue": _text(art, ".//JournalIssue/Issue"),
        "pages": _text(art, ".//Pagination/MedlinePgn") or _text(art, ".//Pagination/StartPage"),
        "publication_types": ptypes,
        "mesh": [(_m.text or "").strip() for _m in art.findall(".//MeshHeading/DescriptorName")],
        "flags": flags,
        "source": "pubmed",
        "cache_file": cache_file,
        "retrieved_at": now(),
    }


def _parse_crossref_message(msg: dict) -> dict:
    issued = msg.get("issued", {}).get("date-parts", [[None]])[0]
    if not (issued and issued[0]):
        issued = msg.get("published-print", {}).get("date-parts", [[None]])[0]
    if not (issued and issued[0]):
        issued = msg.get("published-online", {}).get("date-parts", [[None]])[0]
    authors = []
    for a in msg.get("author", []):
        if a.get("family"):
            authors.append({"last": str(a.get("family", "")).strip(),
                            "first": str(a.get("given", "")).strip(),
                            "initials": "",
                            "suffix": str(a.get("suffix", "")).strip(),
                            "collective": False})
        elif a.get("name"):
            authors.append({"last": str(a.get("name", "")).strip(),
                            "first": "", "initials": "", "suffix": "", "collective": True})
    raw_abs = str(msg.get("abstract") or "").strip()
    if raw_abs:
        raw_abs = re.sub(r"<[^>]+>", " ", raw_abs)
        raw_abs = re.sub(r"\s+", " ", raw_abs).strip()
    title = re.sub(r"\s+", " ", (msg.get("title") or [""])[0]).strip().rstrip(".")
    container = (msg.get("container-title") or msg.get("publisher") or [""])
    journal = container[0] if isinstance(container, list) else str(container)
    return {
        "pmid": "",
        "doi": (msg.get("DOI") or "").strip().lower(),
        "pmcid": "",
        "title": title,
        "abstract": raw_abs,
        "authors": authors,
        "journal": re.sub(r"\s+", " ", journal).strip(),
        "journal_abbrev": ((msg.get("short-container-title") or [""])[0] or "").strip(),
        "year": str(issued[0]) if issued and issued[0] else "",
        "volume": str(msg.get("volume") or "").strip(),
        "issue": str(msg.get("issue") or "").strip(),
        "pages": str(msg.get("page") or "").strip(),
        "type": msg.get("type", ""),
        "flags": ["PREPRINT"] if msg.get("type") == "posted-content" else [],
        "source": "crossref",
    }


def crossref_by_doi(doi: str) -> dict | None:
    if not doi:
        return None
    clean_doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    name = f"crossref_{_digest(clean_doi.lower())}.json"
    try:
        raw = cached(name, lambda: http_get(f"{CROSSREF}/{urllib.parse.quote(clean_doi)}",
                                           {"mailto": api_email() or ""}).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    try:
        msg = json.loads(raw).get("message", {})
    except json.JSONDecodeError:
        return None
    rec = _parse_crossref_message(msg)
    rec["cache_file"] = f"06_refs/cache/{name}"
    return rec


def crossref_fetch(doi: str, *, fresh: bool = False, purpose: str = "discovery") -> dict | None:
    """Fetch a Crossref work record by DOI with tamper-evident raw JSON caching."""
    clean_doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", (doi or "").strip(), flags=re.I)
    if not clean_doi:
        return None
    clean_purpose = re.sub(r"[^a-z0-9_-]", "", purpose.casefold()) or "discovery"
    if fresh:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"{clean_purpose}_crossref_{_digest(clean_doi.lower())}_{stamp}.json"
    else:
        name = f"crossref_{_digest(clean_doi.lower())}.json"
    raw = cached(
        name,
        lambda: http_get(f"{CROSSREF}/{urllib.parse.quote(clean_doi)}",
                         {"mailto": api_email() or ""}),
        binary=True,
        refresh=fresh,
    )
    payload_bytes = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    msg = json.loads(payload_bytes.decode("utf-8", "replace")).get("message", {})
    if not msg or not msg.get("DOI"):
        return None
    rec = _parse_crossref_message(msg)
    rec["cache_file"] = f"06_refs/cache/{name}"
    rec["cache_sha256"] = hashlib.sha256(payload_bytes).hexdigest()
    rec["fresh_fetch"] = fresh
    rec["retrieved_at"] = now()
    return rec


def r_citation_record(package: str = "R", *, fresh: bool = False,
                      purpose: str = "discovery") -> dict:
    """Extract official R / CRAN package citation metadata from the installed R runtime."""
    import shutil
    import subprocess
    rscript = shutil.which("Rscript")
    if not rscript:
        raise RuntimeError("Rscript is not on PATH; cannot verify R software citation")
    pkg = (package or "R").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.]*", pkg):
        raise ValueError(f"invalid R package identifier: {pkg}")
    clean_purpose = re.sub(r"[^a-z0-9_-]", "", purpose.casefold()) or "discovery"
    slug = re.sub(r"[^a-z0-9_.-]", "_", pkg.casefold())
    if fresh:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"{clean_purpose}_authority_rcitation_{slug}_{stamp}.json"
    else:
        name = f"authority_rcitation_{slug}.json"
    r_expr = (
        f"cit <- if ('{pkg}' == 'R') utils::citation() else utils::citation('{pkg}'); "
        "e <- cit[[1]]; "
        "auths <- lapply(e$author, function(p) list(last=paste(p$family, collapse=' '), first=paste(p$given, collapse=' '), collective=is.null(p$given) || !length(p$given))); "
        "yr <- as.character(e$year); if (!length(yr) || !nzchar(yr)) yr <- format(Sys.Date(), '%Y'); "
        "ver <- if ('" + pkg + "' == 'R') paste(R.version$major, R.version$minor, sep='.') else as.character(utils::packageVersion('" + pkg + "')); "
        "out <- list(r_package='" + pkg + "', version=ver, title=paste(as.character(e$title), collapse=' '), "
        "year=yr, url=paste(as.character(e$url), collapse=' '), journal=paste(as.character(if (!is.null(e$organization)) e$organization else if (!is.null(e$journal)) e$journal else 'R Foundation / CRAN'), collapse=' '), "
        "note=paste(as.character(e$note), collapse=' '), authors=auths, bibtex=paste(as.character(utils::toBibtex(cit)), collapse='\\n')); "
        "cat(jsonlite::toJSON(out, auto_unbox=TRUE))"
    )
    def _run_r() -> bytes:
        proc = subprocess.run([rscript, "--vanilla", "-e", r_expr],
                              capture_output=True, timeout=60, check=False)
        if proc.returncode != 0 or not proc.stdout.strip():
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"Rscript citation('{pkg}') failed: {err}")
        return proc.stdout

    raw = cached(name, _run_r, binary=True, refresh=fresh)
    payload_bytes = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    data = json.loads(payload_bytes.decode("utf-8", "replace"))
    authors = []
    for a in data.get("authors") or []:
        last = str(a.get("last") or "").strip()
        first = str(a.get("first") or "").strip()
        if last or first:
            authors.append({
                "last": last or first,
                "first": first if last else "",
                "initials": "",
                "suffix": "",
                "collective": bool(a.get("collective")) or not first,
            })
    if not authors:
        authors = [{"last": "R Core Team" if pkg == "R" else pkg, "first": "", "initials": "", "suffix": "", "collective": True}]
    return {
        "pmid": "",
        "doi": "",
        "pmcid": "",
        "r_package": pkg,
        "url": str(data.get("url") or ("https://www.R-project.org/" if pkg == "R" else f"https://CRAN.R-project.org/package={pkg}")).strip(),
        "title": re.sub(r"\s+", " ", str(data.get("title") or "")).strip().rstrip("."),
        "abstract": "",
        "authors": authors,
        "journal": re.sub(r"\s+", " ", str(data.get("journal") or "R Foundation for Statistical Computing")).strip(),
        "year": re.sub(r"[^0-9]", "", str(data.get("year") or ""))[:4],
        "volume": "",
        "issue": "",
        "pages": "",
        "flags": [],
        "source": "authority",
        "authority_kind": "r_software",
        "bib_type": "manual",
        "cache_file": f"06_refs/cache/{name}",
        "cache_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "fresh_fetch": fresh,
        "retrieved_at": now(),
    }


def authority_url_record(url: str, *, title: str, year: str, author: str,
                         journal: str = "Official Guideline / Standard",
                         fresh: bool = False, purpose: str = "discovery") -> dict:
    """Fetch and hash an official regulatory/guideline URL snapshot."""
    clean_url = (url or "").strip()
    if not re.match(r"^https?://", clean_url, flags=re.I):
        raise ValueError("authority URL must start with http:// or https://")
    clean_purpose = re.sub(r"[^a-z0-9_-]", "", purpose.casefold()) or "discovery"
    if fresh:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"{clean_purpose}_authority_url_{_digest(clean_url)}_{stamp}.raw"
    else:
        name = f"authority_url_{_digest(clean_url)}.raw"
    raw = cached(name, lambda: http_get(clean_url), binary=True, refresh=fresh)
    payload_bytes = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    if len(payload_bytes) < 64:
        raise RuntimeError(f"authority URL returned implausibly small payload ({len(payload_bytes)} bytes): {clean_url}")
    meta_sidecar = cache_dir() / (name + ".meta.json")
    meta_obj = {
        "url": clean_url,
        "title": re.sub(r"\s+", " ", title.strip()).rstrip("."),
        "year": str(year).strip(),
        "author": author.strip(),
        "journal": journal.strip(),
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload_bytes": len(payload_bytes),
    }
    meta_sidecar.write_bytes(json.dumps(meta_obj, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return {
        "pmid": "",
        "doi": "",
        "pmcid": "",
        "url": clean_url,
        "title": meta_obj["title"],
        "abstract": "",
        "authors": [{"last": author.strip(), "first": "", "initials": "", "suffix": "", "collective": True}],
        "journal": meta_obj["journal"],
        "year": meta_obj["year"],
        "volume": "",
        "issue": "",
        "pages": "",
        "flags": [],
        "source": "authority",
        "authority_kind": "official_standard",
        "bib_type": "misc",
        "cache_file": f"06_refs/cache/{name}",
        "cache_sha256": meta_obj["payload_sha256"],
        "fresh_fetch": fresh,
        "retrieved_at": now(),
    }


# ---------------------------------------------------------------------------
# citekeys
# ---------------------------------------------------------------------------
STOPWORDS = {
    "the", "a", "an", "of", "and", "in", "on", "for", "with", "to", "from", "by",
    "at", "as", "is", "are", "was", "were", "be", "been", "its", "their", "this",
    "that", "these", "those", "study", "analysis", "using", "based", "among",
    "between", "after", "before", "during", "effect", "effects", "role", "new",
}


def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def make_citekey(rec: dict, taken: set[str] | None = None) -> str:
    taken = taken or set()
    authors = rec.get("authors") or []
    last = _ascii(authors[0]["last"]) if authors else "anon"
    last = re.sub(r"[^A-Za-z]", "", last).lower() or "anon"
    year = re.sub(r"[^0-9]", "", str(rec.get("year") or ""))[:4] or "0000"
    words = [w for w in re.findall(r"[A-Za-z]{3,}", _ascii(rec.get("title", "")).lower())
             if w not in STOPWORDS]
    word = words[0] if words else "untitled"
    base = f"{last}{year}{word}"
    if base not in taken:
        return base
    for suffix in "abcdefghijklmnopqrstuvwxyz":
        cand = f"{base}{suffix}"
        if cand not in taken:
            return cand
    return f"{base}{rec.get('pmid', '')}"


# ---------------------------------------------------------------------------
def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)
