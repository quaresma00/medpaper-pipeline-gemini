"""Reuse unchanged independent live reference checks within the explicit freshness window."""
from datetime import datetime, timezone
import json

from . import refproof
from .packagefreeze import _safe_path
from .readiness import atomic_json

REL = ".wf/reference_live.json"
GATE_PREFIXES = (
    "06_refs/cache/gate_efetch_pubmed_",
    "06_refs/cache/gate_crossref_",
    "06_refs/cache/gate_authority_",
)


def cached_sources(project, entries, max_hours=24):
    try:
        payload = json.loads((project / REL).read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(payload["at"])).total_seconds()
        if age < 0 or age > max_hours * 3600:
            return None
        pubmed_sources = {}
        crossref_sources = {}
        authority_sources = []
        for row in payload["payloads"]:
            rel, path = _safe_path(project, row["path"])
            if not rel.startswith(GATE_PREFIXES):
                return None
            if refproof.file_sha256(path) != row["sha256"]:
                return None
            raw = path.read_bytes()
            if rel.startswith("06_refs/cache/gate_efetch_pubmed_"):
                pubmed_sources.update(refproof.parse_pubmed_payload(raw))
            elif rel.startswith("06_refs/cache/gate_crossref_"):
                rec = refproof.parse_crossref_payload(raw)
                crossref_sources[rec["doi"]] = rec
            else:
                authority_sources.append(refproof.parse_authority_payload(path, raw))
        pm_entries = [e for e in entries if (e.get("source") or "pubmed") == "pubmed"]
        cr_entries = [e for e in entries if e.get("source") == "crossref"]
        au_entries = [e for e in entries if e.get("source") == "authority"]
        if len(pm_entries) + len(cr_entries) + len(au_entries) != len(entries):
            return None
        if set(pubmed_sources) != {str(e.get("pmid", "")) for e in pm_entries}:
            return None
        if any(refproof.compare_entry_to_source(e, pubmed_sources[str(e.get("pmid", ""))]) for e in pm_entries):
            return None
        for e in cr_entries:
            doi = str(e.get("doi", "")).strip().casefold()
            if doi not in crossref_sources or refproof.compare_entry_to_source(e, crossref_sources[doi]):
                return None
        for e in au_entries:
            if not any(not refproof.compare_entry_to_source(e, au) for au in authority_sources):
                return None
        return {"pubmed": pubmed_sources, "crossref": crossref_sources, "authority": authority_sources}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def store_sources(project, live_records):
    payloads = {}
    for row in live_records:
        rel = row.get("cache_file", "")
        if not rel.startswith(GATE_PREFIXES):
            return  # a mocked/test record or non-independent source cannot seed the cache
        _, path = _safe_path(project, rel)
        if not path.is_file():
            return
        payloads[rel] = {"path": rel, "sha256": refproof.file_sha256(path)}
    atomic_json(project / REL, {"at": datetime.now(timezone.utc).isoformat(),
                                "payloads": list(payloads.values())})
