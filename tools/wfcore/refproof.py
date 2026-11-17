"""Tamper-evident PubMed verification receipts used by reference gates.

``verified: true`` is never accepted on its own.  A usable record must be bound to
the exact library file and to a cached raw XML payload produced by a fresh PubMed
EFetch request.  The gate reparses that payload and recomputes every material
bibliographic comparison.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET


SCHEMA = 3
GENERATOR = "tools/pubmed/verify.py"
SOURCE = "ncbi_pubmed_efetch"
CROSSREF_SOURCE = "crossref_doi_work"
AUTHORITY_SOURCE = "official_authority_snapshot"
TITLE_THRESHOLD = 0.92
JOURNAL_THRESHOLD = 0.85
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CACHE_RE = re.compile(r"^06_refs/cache/verify_efetch_pubmed_[A-Za-z0-9_.-]+\.xml$")
CROSSREF_CACHE_RE = re.compile(r"^06_refs/cache/verify_crossref_[A-Za-z0-9_.-]+\.json$")
AUTHORITY_CACHE_RE = re.compile(r"^06_refs/cache/verify_authority_(?:rcitation|url)_[A-Za-z0-9_.-]+\.(?:json|raw)$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9 ]", " ", text.casefold()).strip()


def ratio(left: object, right: object) -> float:
    a, b = norm(left), norm(right)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _text(node, path: str) -> str:
    found = node.find(path)
    return "" if found is None else "".join(found.itertext()).strip()


def _source_record(article) -> dict:
    pmid = _text(article, ".//MedlineCitation/PMID")
    title = _text(article, ".//Article/ArticleTitle") or _text(article, ".//BookTitle")
    abstract_parts = []
    for part in article.findall(".//Article/Abstract/AbstractText"):
        label = part.get("Label")
        body = "".join(part.itertext()).strip()
        if body:
            abstract_parts.append(f"{label}: {body}" if label else body)
    authors = []
    for author in article.findall(".//AuthorList/Author"):
        collective = _text(author, "CollectiveName")
        last = collective or _text(author, "LastName")
        if last:
            authors.append({"last": last, "first": _text(author, "ForeName"),
                            "initials": _text(author, "Initials"),
                            "suffix": _text(author, "Suffix"), "collective": bool(collective)})
    year = _text(article, ".//Journal/JournalIssue/PubDate/Year")
    if not year:
        match = re.search(r"(?:19|20)\d{2}",
                          _text(article, ".//Journal/JournalIssue/PubDate/MedlineDate"))
        year = match.group(0) if match else ""
    doi, pmcid = "", ""
    for item in article.findall(".//ELocationID"):
        if item.get("EIdType") == "doi":
            doi = (item.text or "").strip()
    for item in article.findall(".//ArticleIdList/ArticleId"):
        if item.get("IdType") == "doi" and not doi:
            doi = (item.text or "").strip()
        if item.get("IdType") == "pmc":
            pmcid = (item.text or "").strip().upper()
    publication_types = [(item.text or "").strip()
                         for item in article.findall(".//PublicationTypeList/PublicationType")]
    corrections = [item.get("RefType", "") for item in
                   article.findall(".//CommentsCorrectionsList/CommentsCorrections")]
    flags = []
    if any("Retract" in item for item in publication_types) or "RetractionIn" in corrections:
        flags.append("RETRACTED_OR_RETRACTION")
    if "ExpressionOfConcernIn" in corrections:
        flags.append("EXPRESSION_OF_CONCERN")
    if "Preprint" in publication_types:
        flags.append("PREPRINT")
    return {
        "pmid": pmid,
        "doi": doi.casefold(),
        "pmcid": pmcid,
        "authors": authors,
        "title": re.sub(r"\s+", " ", title).strip().rstrip("."),
        "journal": _text(article, ".//Journal/Title"),
        "year": year,
        "first_author": authors[0]["last"] if authors else "",
        "abstract": "\n".join(abstract_parts).strip(),
        "flags": flags,
    }


def parse_pubmed_payload(blob: bytes | str) -> dict[str, dict]:
    try:
        root = ET.fromstring(blob)
    except ET.ParseError as exc:
        raise ValueError(f"invalid PubMed XML: {exc}") from exc
    records: dict[str, dict] = {}
    for tag in ("PubmedArticle", "PubmedBookArticle"):
        for article in root.iter(tag):
            record = _source_record(article)
            if record["pmid"]:
                records[record["pmid"]] = record
    return records


def parse_crossref_payload(blob: bytes | str) -> dict:
    raw_text = blob.decode("utf-8", "replace") if isinstance(blob, bytes) else blob
    try:
        msg = json.loads(raw_text).get("message", {})
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Crossref JSON: {exc}") from exc
    if not isinstance(msg, dict) or not msg.get("DOI"):
        raise ValueError("Crossref payload lacks message.DOI")
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
    container = msg.get("container-title") or msg.get("publisher") or [""]
    journal = container[0] if isinstance(container, list) else str(container)
    return {
        "pmid": "",
        "doi": str(msg.get("DOI", "")).strip().casefold(),
        "pmcid": "",
        "authors": authors,
        "title": re.sub(r"\s+", " ", (msg.get("title") or [""])[0]).strip().rstrip("."),
        "journal": re.sub(r"\s+", " ", journal).strip(),
        "year": str(issued[0]) if issued and issued[0] else "",
        "first_author": authors[0]["last"] if authors else "",
        "abstract": raw_abs,
        "flags": ["PREPRINT"] if msg.get("type") == "posted-content" else [],
        "source": "crossref",
    }


def parse_authority_payload(cache_path: Path, blob: bytes) -> dict:
    if cache_path.suffix.lower() == ".json" and "rcitation_" in cache_path.name:
        try:
            data = json.loads(blob.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid R citation JSON: {exc}") from exc
        pkg = str(data.get("r_package") or "").strip()
        if not pkg:
            raise ValueError("R citation payload lacks r_package")
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
            "url": str(data.get("url") or "").strip(),
            "authors": authors,
            "title": re.sub(r"\s+", " ", str(data.get("title") or "")).strip().rstrip("."),
            "journal": re.sub(r"\s+", " ", str(data.get("journal") or "")).strip(),
            "year": re.sub(r"[^0-9]", "", str(data.get("year") or ""))[:4],
            "first_author": authors[0]["last"],
            "abstract": "",
            "flags": [],
            "source": "authority",
            "authority_kind": "r_software",
        }
    if len(blob) < 64:
        raise ValueError("official authority payload is empty or truncated")
    meta_path = cache_path.parent / (cache_path.name + ".meta.json")
    if not meta_path.is_file():
        raise ValueError("official authority metadata sidecar is missing")
    meta = _load_json(meta_path)
    actual_sha = hashlib.sha256(blob).hexdigest()
    if str(meta.get("payload_sha256", "")).casefold() != actual_sha:
        raise ValueError("official authority metadata sidecar disagrees with raw payload hash")
    author_name = str(meta.get("author") or "").strip()
    authors = [{"last": author_name, "first": "", "initials": "", "suffix": "", "collective": True}] if author_name else []
    return {
        "pmid": "",
        "doi": "",
        "pmcid": "",
        "url": str(meta.get("url") or "").strip(),
        "authors": authors,
        "title": re.sub(r"\s+", " ", str(meta.get("title") or "")).strip().rstrip("."),
        "journal": re.sub(r"\s+", " ", str(meta.get("journal") or "")).strip(),
        "year": str(meta.get("year") or "").strip(),
        "first_author": author_name,
        "abstract": "",
        "flags": [],
        "source": "authority",
        "authority_kind": "official_standard",
    }


def canonical_source(record: dict) -> dict:
    return {
        "pmid": str(record.get("pmid", "")),
        "doi": str(record.get("doi", "")).strip().casefold(),
        "pmcid": str(record.get("pmcid", "")).strip().upper(),
        "authors": canonical_authors(record),
        "title": re.sub(r"\s+", " ", str(record.get("title", ""))).strip().rstrip("."),
        "journal": re.sub(r"\s+", " ", str(record.get("journal", ""))).strip(),
        "year": str(record.get("year", "")),
        "first_author": str(record.get("first_author") or
                            ((record.get("authors") or [{}])[0].get("last", ""))),
        "abstract": str(record.get("abstract", "")).strip(),
        "flags": sorted(str(item) for item in record.get("flags", [])),
    }


def canonical_authors(record: dict) -> list[dict]:
    return [{"last": str(a.get("last", "")).strip(),
             "first": str(a.get("first", "")).strip(),
             "initials": str(a.get("initials", "")).strip(),
             "suffix": str(a.get("suffix", "")).strip(),
             "collective": bool(a.get("collective", False))}
            for a in record.get("authors", [])]


def record_sha256(record: dict) -> str:
    payload = json.dumps(canonical_source(record), sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalized_abstract(value: object) -> str:
    """Ignore layout whitespace only; preserve negation, numbers, punctuation and case."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def readable_source_errors(project: Path, entry: dict, source: dict | None = None) -> list[str]:
    """No PubMed abstract requires a registered real article, never an invented summary.

    Source identity and actual reading remain distinct. Structural checks reject notes,
    metadata-only XML and empty documents, not claim to understand or prove full coverage.
    """
    if normalized_abstract((source if source is not None else entry).get("abstract")):
        return []
    if entry.get("source") == "authority" and entry.get("authority_kind") in {"r_software", "official_standard"}:
        return []
    if entry.get("source") == "crossref" and entry.get("authority_kind") == "methodology_doi":
        return []
    from .packagefreeze import _safe_path
    from pubmed.identity import errors as identity_errors
    try:
        manifest=_load_json(project / "06_refs/fulltext/retrieval_manifest.json")
        retrievals=manifest.get("retrievals",[])
        if not isinstance(retrievals,list) or any(not isinstance(row,dict) for row in retrievals):
            return ["no abstract: malformed full-text registration records"]
        records=[row for row in retrievals if row.get("citekey")==entry.get("citekey")]
        if len(records)!=1: return ["no abstract: exactly one registered full-text record is required"]
        record=records[0]
        if record.get("access") not in {"oa","authorized"}:
            return ["no abstract: a paywall/link/stub is not readable full-text evidence"]
        if record.get("access")=="authorized" and not str(record.get("authorization_note","")).strip():
            return ["no abstract: authorized full text needs its actual access basis"]
        if str(record.get("pmid",""))!=str(entry.get("pmid","")) or str(record.get("doi","")).strip().casefold()!=str(entry.get("doi","")).strip().casefold():
            return ["no abstract: full-text registration identity differs from library metadata"]
        rel,path=_safe_path(project,record.get("fulltext",""))
        if not rel.startswith("06_refs/fulltext/") or path.suffix.lower() not in {".xml",".html",".htm",".pdf"} or not path.is_file():
            return ["no abstract: a registered local PDF/XML/HTML article is required, not notes or a URL"]
        if path.stat().st_size<1000 or str(record.get("sha256","")).casefold()!=file_sha256(path):
            return ["no abstract: registered full text is implausibly small or its hash changed"]
        issues=identity_errors(entry,path,record)
        if issues: return ["no abstract: "+issue for issue in issues]
        blob=path.read_bytes(); suffix=path.suffix.lower()
        if suffix==".xml":
            root=ET.fromstring(blob)
            bodies=[node for node in root.iter() if node.tag.split("}")[-1]=="body"]
            if not any("".join(node.itertext()).strip() for node in bodies):
                return ["no abstract: XML contains no article body; metadata is not full text"]
        elif suffix==".pdf":
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError
            try:
                reader=PdfReader(path)
                has_content=any(page.get_contents() is not None or page.images for page in reader.pages)
            except (PyPdfError,RuntimeError) as exc:
                return [f"no abstract: cannot read registered PDF ({exc})"]
            if not blob.startswith(b"%PDF") or not has_content:
                return ["no abstract: PDF has no actual pages"]
        else:
            from html.parser import HTMLParser
            class Body(HTMLParser):
                def __init__(self):
                    super().__init__(); self.in_body=False; self.hidden=0; self.text=[]
                def handle_starttag(self,tag,attrs):
                    if tag=="body": self.in_body=True
                    if tag in {"script","style"}: self.hidden+=1
                def handle_endtag(self,tag):
                    if tag=="body": self.in_body=False
                    if tag in {"script","style"}: self.hidden=max(0,self.hidden-1)
                def handle_data(self,data):
                    if self.in_body and not self.hidden: self.text.append(data)
            parser=Body(); parser.feed(blob.decode("utf-8",errors="replace"))
            if not "".join(parser.text).strip(): return ["no abstract: HTML contains no readable body"]
        return []
    except (OSError,ValueError,KeyError,TypeError,ImportError,ET.ParseError) as exc:
        return [f"no abstract: registered readable full-text evidence is unavailable ({exc})"]


def compare_entry_to_source(entry: dict, source: dict) -> list[str]:
    """Recompute all checks that determine whether a library entry is real."""
    src_kind = str(entry.get("source") or source.get("source") or "pubmed")
    raw_source = source
    source = canonical_source(source)
    problems = []
    if src_kind == "crossref":
        entry_doi = str(entry.get("doi", "")).strip().casefold()
        if not entry_doi:
            problems.append("Crossref entry lacks a DOI")
        elif entry_doi != source["doi"]:
            problems.append("DOI differs from Crossref payload")
        if ratio(entry.get("title", ""), source["title"]) < TITLE_THRESHOLD:
            problems.append("title differs from Crossref payload")
        if source["journal"] and ratio(entry.get("journal", ""), source["journal"]) < JOURNAL_THRESHOLD:
            problems.append("journal/container differs from Crossref payload")
        if str(entry.get("year", "")) != source["year"]:
            problems.append("year differs from Crossref payload")
        first_author = ((entry.get("authors") or [{}])[0].get("last", ""))
        if norm(first_author) != norm(source["first_author"]):
            problems.append("first author differs from Crossref payload")
        if source["flags"]:
            problems.append("non-citable Crossref flag(s): " + ", ".join(source["flags"]))
        return problems
    if src_kind == "authority":
        if ratio(entry.get("title", ""), source["title"]) < TITLE_THRESHOLD:
            problems.append("title differs from verified authority snapshot")
        if str(entry.get("year", "")) != source["year"]:
            problems.append("year differs from verified authority snapshot")
        first_author = ((entry.get("authors") or [{}])[0].get("last", ""))
        if norm(first_author) != norm(source["first_author"]):
            problems.append("author/organization differs from verified authority snapshot")
        if raw_source.get("r_package") and str(entry.get("r_package", "")).strip() != str(raw_source.get("r_package", "")).strip():
            problems.append("r_package differs from verified R citation snapshot")
        if raw_source.get("authority_kind") == "official_standard" and str(entry.get("url", "")).strip() != str(raw_source.get("url", "")).strip():
            problems.append("URL differs from verified official authority snapshot")
        return problems
    if not re.fullmatch(r"\d+", str(entry.get("pmid", ""))):
        problems.append("library PMID is missing or non-numeric")
    elif str(entry.get("pmid")) != source["pmid"]:
        problems.append("PMID differs from PubMed payload")
    if ratio(entry.get("title", ""), source["title"]) < TITLE_THRESHOLD:
        problems.append("title differs from PubMed payload")
    if ratio(entry.get("journal", ""), source["journal"]) < JOURNAL_THRESHOLD:
        problems.append("journal differs from PubMed payload")
    if str(entry.get("year", "")) != source["year"]:
        problems.append("year differs from PubMed payload")
    first_author = ((entry.get("authors") or [{}])[0].get("last", ""))
    if norm(first_author) != norm(source["first_author"]):
        problems.append("first author differs from PubMed payload")
    if normalized_abstract(entry.get("abstract")) != normalized_abstract(source["abstract"]):
        problems.append("abstract differs from PubMed payload; do not add or rewrite source text")
    entry_doi = str(entry.get("doi", "")).strip().casefold()
    if entry_doi != source["doi"]:
        problems.append("DOI differs from PubMed payload")
    if str(entry.get("pmcid", "")).strip().upper() != source["pmcid"]:
        problems.append("PMCID differs from PubMed payload")
    if canonical_authors(entry) != source["authors"]:
        problems.append("ordered authors, collective names or name parts differ from PubMed payload")
    if source["flags"]:
        problems.append("non-citable PubMed flag(s): " + ", ".join(source["flags"]))
    return problems


def evidence_for_live_record(record: dict) -> dict:
    rec_src = str(record.get("source") or "pubmed")
    ev_source = (CROSSREF_SOURCE if rec_src == "crossref"
                 else AUTHORITY_SOURCE if rec_src == "authority"
                 else SOURCE)
    return {
        "source": ev_source,
        "cache_file": str(record.get("cache_file", "")),
        "payload_sha256": str(record.get("cache_sha256", "")),
        "record_sha256": record_sha256(record),
        "fresh_fetch": record.get("fresh_fetch") is True,
    }


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _age_days(value: object) -> int | None:
    try:
        stamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None
    return (date.today() - stamp).days


def validate_local_proof(project: Path, required_keys: set[str] | None = None,
                         max_age_days: int = 90) -> tuple[bool, list[str], int]:
    """Validate a receipt without trusting any authored boolean or comparison result."""
    library_path = project / "06_refs/library.json"
    verified_path = project / "06_refs/verified.json"
    if not library_path.is_file() or not verified_path.is_file():
        missing = [str(path.relative_to(project)).replace("\\", "/") for path in
                   (library_path, verified_path) if not path.is_file()]
        return False, ["missing " + ", ".join(missing)], 0
    try:
        library = _load_json(library_path)
        verified = _load_json(verified_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return False, [f"reference verification files are invalid: {exc}"], 0

    entries = {str(item.get("citekey", "")): item for item in library.get("entries", [])
               if str(item.get("citekey", ""))}
    records = verified.get("records", {})
    if not isinstance(records, dict):
        records = {}
    problems: list[str] = []
    generator = verified.get("generator", {})
    if verified.get("schema") != SCHEMA:
        problems.append(f"verified.json schema must be {SCHEMA}; a boolean-only file is not evidence")
    if not isinstance(generator, dict) or generator.get("tool") != GENERATOR or \
            generator.get("mode") not in {"fresh_ncbi_pubmed_efetch", "fresh_multi_authority_verify"}:
        problems.append("verified.json lacks the bundled fresh-EFetch generator receipt")
    expected_library_hash = file_sha256(library_path)
    if verified.get("library_sha256") != expected_library_hash:
        problems.append("library.json changed after reference verification")
    age = _age_days(verified.get("verified_at"))
    if age is None or age < 0:
        problems.append("verified_at is missing or invalid")
    elif age > max_age_days:
        problems.append(f"reference verification is {age} days old (maximum {max_age_days})")
    if set(records) != set(entries):
        missing = sorted(set(entries) - set(records))
        extra = sorted(set(records) - set(entries))
        if missing:
            problems.append("verification receipt missing citekey(s): " + ", ".join(missing[:6]))
        if extra:
            problems.append("verification receipt has non-library citekey(s): " + ", ".join(extra[:6]))
    if verified.get("n_entries") != len(entries) or verified.get("n_verified") != len(entries):
        problems.append("verified.json summary counts do not equal the current library")

    wanted = set(entries) if required_keys is None else set(required_keys)
    unknown = sorted(wanted - set(entries))
    if unknown:
        problems.append("citekey(s) absent from library.json: " + ", ".join(unknown[:6]))
    payload_cache: dict[Path, tuple[str, dict[str, dict]]] = {}
    project_root = project.resolve()
    for key in sorted(wanted & set(entries)):
        receipt = records.get(key)
        if not isinstance(receipt, dict) or receipt.get("verified") is not True:
            problems.append(f"{key}: verified=true receipt is absent")
            continue
        evidence = receipt.get("evidence", {})
        ev_source = evidence.get("source") if isinstance(evidence, dict) else None
        if not isinstance(evidence, dict) or ev_source not in {SOURCE, CROSSREF_SOURCE, AUTHORITY_SOURCE} or \
                evidence.get("fresh_fetch") is not True:
            problems.append(f"{key}: no fresh verified source evidence")
            continue
        rel = str(evidence.get("cache_file", "")).replace("\\", "/")
        expected_re = (CACHE_RE if ev_source == SOURCE
                       else CROSSREF_CACHE_RE if ev_source == CROSSREF_SOURCE
                       else AUTHORITY_CACHE_RE)
        if not expected_re.fullmatch(rel):
            problems.append(f"{key}: verification cache path is not a bundled verifier output")
            continue
        cache_path = (project / rel).resolve()
        try:
            cache_path.relative_to(project_root)
        except ValueError:
            problems.append(f"{key}: verification cache escapes the project")
            continue
        if not cache_path.is_file():
            problems.append(f"{key}: verification payload is missing: {rel}")
            continue
        if ev_source == SOURCE:
            if cache_path not in payload_cache:
                try:
                    digest = file_sha256(cache_path)
                    payload_cache[cache_path] = (digest, parse_pubmed_payload(cache_path.read_bytes()))
                except (OSError, ValueError) as exc:
                    problems.append(f"{key}: cannot parse verification payload ({exc})")
                    continue
            digest, source_records = payload_cache[cache_path]
            claimed = str(evidence.get("payload_sha256", "")).casefold()
            if not SHA_RE.fullmatch(claimed) or claimed != digest:
                problems.append(f"{key}: PubMed payload hash mismatch")
                continue
            pmid = str(entries[key].get("pmid", ""))
            source = source_records.get(pmid)
            if source is None:
                problems.append(f"{key}: PMID {pmid or '(missing)'} is absent from its PubMed payload")
                continue
            source_hash = record_sha256(source)
            if evidence.get("record_sha256") != source_hash:
                problems.append(f"{key}: parsed PubMed record fingerprint mismatch")
            for issue in compare_entry_to_source(entries[key], source):
                problems.append(f"{key}: {issue}")
            for issue in readable_source_errors(project, entries[key], source):
                problems.append(f"{key}: {issue}")
            if str(receipt.get("pmid", "")) != source["pmid"]:
                problems.append(f"{key}: receipt PMID differs from its PubMed payload")
            if str(receipt.get("doi", "")).strip().casefold() != source["doi"]:
                problems.append(f"{key}: receipt DOI differs from its PubMed payload")
        elif ev_source == CROSSREF_SOURCE:
            try:
                digest = file_sha256(cache_path)
                source = parse_crossref_payload(cache_path.read_bytes())
            except (OSError, ValueError) as exc:
                problems.append(f"{key}: cannot parse Crossref verification payload ({exc})")
                continue
            claimed = str(evidence.get("payload_sha256", "")).casefold()
            if not SHA_RE.fullmatch(claimed) or claimed != digest:
                problems.append(f"{key}: Crossref payload hash mismatch")
                continue
            if evidence.get("record_sha256") != record_sha256(source):
                problems.append(f"{key}: parsed Crossref record fingerprint mismatch")
            for issue in compare_entry_to_source(entries[key], source):
                problems.append(f"{key}: {issue}")
            for issue in readable_source_errors(project, entries[key], source):
                problems.append(f"{key}: {issue}")
            if str(receipt.get("doi", "")).strip().casefold() != source["doi"]:
                problems.append(f"{key}: receipt DOI differs from its Crossref payload")
        else:
            try:
                digest = file_sha256(cache_path)
                source = parse_authority_payload(cache_path, cache_path.read_bytes())
            except (OSError, ValueError) as exc:
                problems.append(f"{key}: cannot parse authority verification payload ({exc})")
                continue
            claimed = str(evidence.get("payload_sha256", "")).casefold()
            if not SHA_RE.fullmatch(claimed) or claimed != digest:
                problems.append(f"{key}: authority payload hash mismatch")
                continue
            if evidence.get("record_sha256") != record_sha256(source):
                problems.append(f"{key}: parsed authority record fingerprint mismatch")
            for issue in compare_entry_to_source(entries[key], source):
                problems.append(f"{key}: {issue}")
            for issue in readable_source_errors(project, entries[key], source):
                problems.append(f"{key}: {issue}")
    return not problems, problems, len(wanted & set(entries))
