"""Single-source author block rendering and placement verification (v1.28+).

Rules enforced:
1. Non-blinded journals (default): the main manuscript first page directly carries the
   complete author block (title, authors, affiliations, corresponding author + contact
   details, ORCID) rendered from ``00_input/author_info.json``.
2. A separate ``title_page.docx`` is produced for a non-blinded journal ONLY when the
   official journal guidelines explicitly require a separate title-page upload (backed by a
   verified verbatim guideline quote). When both exist, both render from the exact same
   ``00_input/author_info.json`` source so they cannot diverge.
3. Double-blind journals (``blinded_main_manuscript == true``): the main manuscript stays
   anonymous and author information appears ONLY in the separate ``title_page.docx``.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .guides import normalize as _norm_ws
from .packagefreeze import _safe_path

AUTHOR_REL = "00_input/author_info.json"
TARGET_REL = "08_submission/target_journal.json"
REQ_REL = "08_submission/submission_requirements.json"
TITLE_PAGE_MD_REL = "08_submission/integration/title_page.md"
INTEGRATION_MS_REL = "08_submission/integration/full_manuscript.md"
MASTER_TITLE_REL = "07_manuscript/title.md"
MANIFEST_REL = "08_submission/bundle/manifest.json"

ORCID_RE = re.compile(r"^(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$", re.I)
EMAIL_SIMPLE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def verify_sourced_clause(project: Path, clause: object, label: str) -> list[str]:
    """Verify an explicit official-guideline override against captured guide text."""
    if not isinstance(clause, dict):
        return [f"{label}: override must be an object citing the official guideline passage"]
    quote = _norm_ws(str(clause.get("quote", "")))
    locator = str(clause.get("locator", "")).strip()
    if len(quote) < 15 or re.search(r"<|>|\btodo\b|\btbd\b", quote, re.I):
        return [f"{label}: provide a verbatim official guideline quote (>= 15 chars), never an AI assumption"]
    if len(locator) < 3:
        return [f"{label}: provide the exact guideline section/page locator"]

    from . import journalcontext as jc
    if jc.enabled(project):
        try:
            ctx = jc.current(project)
        except (OSError, ValueError, KeyError) as exc:
            return [f"{label}: journal context unreadable ({exc})"]
        source_id = str(clause.get("source_id", "")).strip()
        if not source_id or source_id not in ctx.get("sources", {}):
            return [f"{label}: source_id must reference a captured source in journal_context.json"]
        try:
            _, text_path = _safe_path(project, ctx["sources"][source_id]["text"])
            captured = _norm_ws(text_path.read_text(encoding="utf-8", errors="replace")).casefold()
        except (OSError, ValueError, KeyError) as exc:
            return [f"{label}: captured guideline text unreadable ({exc})"]
        if quote.casefold() not in captured:
            return [f"{label}: verbatim quote was not found in captured official source '{source_id}'"]
        return []

    source = str(clause.get("source", "")).strip()
    target_path = project / TARGET_REL
    if target_path.is_file():
        try:
            guide_url = str(json.loads(target_path.read_text(encoding="utf-8")).get("guidelines_url", "")).strip()
        except (OSError, json.JSONDecodeError):
            guide_url = ""
        if guide_url and guide_url not in source:
            return [f"{label}: source must include target_journal.json guidelines_url ({guide_url})"]
    elif len(source) < 12:
        return [f"{label}: source must cite the official journal instructions URL"]

    extract_path = project / "08_submission/guidelines_extract.md"
    if extract_path.is_file():
        extract_text = _norm_ws(extract_path.read_text(encoding="utf-8", errors="replace")).casefold()
        if quote.casefold() not in extract_text:
            return [f"{label}: verbatim quote must appear in 08_submission/guidelines_extract.md"]
    return []


def is_blinded(project: Path) -> bool:
    path = project / TARGET_REL
    if not path.is_file():
        return False
    try:
        target = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(target.get("blinded_main_manuscript") is True)


def title_page_policy(project: Path) -> tuple[bool, bool, list[str]]:
    """Return (manuscript_has_authors, needs_separate_title_page, policy_problems)."""
    blinded = is_blinded(project)
    req_path = project / REQ_REL
    req = {}
    if req_path.is_file():
        try:
            req = json.loads(req_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return (not blinded), blinded, [f"{REQ_REL}: invalid JSON ({exc})"]

    problems: list[str] = []
    roles = [str(r).strip().casefold() for r in req.get("required_upload_roles", []) if str(r).strip()]
    sep = req.get("separate_title_page")

    if blinded:
        if req and roles and "title_page" not in roles:
            problems.append("double-blind journal requires 'title_page' in submission_requirements.json required_upload_roles")
        if isinstance(sep, dict) and str(sep.get("status", "")).casefold() in {"forbidden", "not_required"}:
            problems.append("double-blind journal cannot disable separate_title_page")
        return False, True, problems

    # Non-blinded journal: main manuscript carries full author info on page 1.
    explicit_separate = False
    if isinstance(sep, dict):
        status = str(sep.get("status", "unspecified")).strip().casefold()
        if status == "required":
            explicit_separate = True
            problems.extend(verify_sourced_clause(project, sep, "separate_title_page"))
        elif status not in {"unspecified", "not_required", "none", "false"}:
            problems.append("separate_title_page.status must be 'required' (with official quote) or 'unspecified'/'not_required'")
    elif sep is True:
        problems.append("separate_title_page cannot be a bare boolean true; provide {status: 'required', source_id/source, locator, quote}")

    if "title_page" in roles and not explicit_separate:
        problems.append(
            "non-blinded journal lists 'title_page' in required_upload_roles without a verified "
            "separate_title_page={status: 'required', quote: ...} rule from the official guidelines"
        )
    if explicit_separate and roles and "title_page" not in roles:
        problems.append("separate_title_page is required by the journal but 'title_page' is missing from required_upload_roles")
    return True, explicit_separate, problems


def expected_narrative_roles(project: Path) -> list[str]:
    """Expected narrative DOCX upload roles when checking manifest completeness."""
    req_path = project / REQ_REL
    if not req_path.is_file():
        # Legacy standalone fixture without submission_requirements.json
        return ["manuscript", "cover_letter"]
    try:
        req = json.loads(req_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["manuscript", "cover_letter"]
    _, needs_sep, _ = title_page_policy(project)
    configured = [str(r).strip().casefold() for r in req.get("required_upload_roles", []) if str(r).strip()]
    if configured:
        return configured
    base = ["manuscript", "cover_letter"]
    if needs_sep:
        base.insert(1, "title_page")
    return base


def _normalize_orcid(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    match = ORCID_RE.match(text)
    return match.group(1).upper() if match else "__INVALID__"


def validate_author_info(facts: object, *, strict: bool = True) -> list[str]:
    """Validate structured 00_input/author_info.json for single-source rendering."""
    if not isinstance(facts, dict):
        return ["00_input/author_info.json must be a JSON object"]
    problems: list[str] = []

    raw_affs = facts.get("affiliations")
    aff_map: dict[str, str] = {}
    if isinstance(raw_affs, list) and raw_affs:
        for idx, entry in enumerate(raw_affs, start=1):
            if isinstance(entry, dict):
                key = str(entry.get("id", idx)).strip()
                label = str(entry.get("name") or entry.get("department") or entry.get("institution") or entry.get("text") or "").strip()
            else:
                key = str(idx)
                label = str(entry).strip()
            if not label:
                problems.append(f"affiliations[{idx}] is empty")
            else:
                aff_map[key] = label
    elif isinstance(raw_affs, dict) and raw_affs:
        for key, val in raw_affs.items():
            label = str(val).strip()
            if not label:
                problems.append(f"affiliations[{key}] is empty")
            else:
                aff_map[str(key).strip()] = label
    else:
        problems.append("affiliations must be a non-empty list or numbered map")

    authors = facts.get("authors")
    if not isinstance(authors, list) or not authors:
        problems.append("authors must be a non-empty list")
        authors = []

    any_orcid = False
    author_names: set[str] = set()
    for idx, author in enumerate(authors, start=1):
        if isinstance(author, str):
            if strict:
                problems.append(
                    f"authors[{idx}] ({author!r}): in v1.28+, each author must be an object with "
                    "name, affiliations, and orcid (or null with orcid_absent_reason)"
                )
            elif author.strip():
                author_names.add(author.strip().casefold())
            continue
        if not isinstance(author, dict):
            problems.append(f"authors[{idx}] must be an object")
            continue
        name = str(author.get("name") or author.get("full_name") or "").strip()
        if len(name) < 2:
            problems.append(f"authors[{idx}] is missing a valid author name")
        else:
            author_names.add(name.casefold())
        aff_refs = author.get("affiliations", author.get("affiliation"))
        if isinstance(aff_refs, (int, str)):
            aff_refs = [aff_refs]
        if not isinstance(aff_refs, list) or not aff_refs:
            problems.append(f"authors[{idx}] ({name or '?'}) must reference at least one affiliation")
        elif aff_map:
            aff_values_cf = {v.casefold(): k for k, v in aff_map.items()}
            for ref in aff_refs:
                sref = str(ref).strip()
                if sref not in aff_map and sref.casefold() not in aff_values_cf:
                    problems.append(f"authors[{idx}] ({name or '?'}): unknown affiliation reference {ref!r}")
        if strict:
            if "orcid" not in author:
                problems.append(f"authors[{idx}] ({name or '?'}) must include 'orcid' (0000-000X-XXXX-XXXX, or null with orcid_absent_reason)")
            else:
                norm = _normalize_orcid(author.get("orcid"))
                if norm == "__INVALID__":
                    problems.append(f"authors[{idx}] ({name or '?'}): invalid ORCID {author.get('orcid')!r} (expected 0000-000X-XXXX-XXXX)")
                elif norm:
                    any_orcid = True
                elif len(str(author.get("orcid_absent_reason", "")).strip()) < 10:
                    problems.append(f"authors[{idx}] ({name or '?'}): null/empty orcid requires 'orcid_absent_reason'")

    corr = facts.get("corresponding")
    corr_list = corr if isinstance(corr, list) else ([corr] if isinstance(corr, dict) else [])
    if not corr_list:
        problems.append("corresponding must be an object (or non-empty list) with name, email, and contact/address")
    for idx, item in enumerate(corr_list, start=1):
        if not isinstance(item, dict):
            problems.append(f"corresponding[{idx}] must be an object")
            continue
        cname = str(item.get("name") or "").strip()
        email = str(item.get("email") or "").strip()
        contact = str(item.get("address") or item.get("contact") or item.get("phone") or item.get("institution") or "").strip()
        if len(cname) < 2:
            problems.append("corresponding author name is missing")
        elif author_names and cname.casefold() not in author_names:
            problems.append(f"corresponding author {cname!r} does not match any entry in authors")
        if not EMAIL_SIMPLE_RE.match(email):
            problems.append(f"corresponding author email is missing or invalid: {email!r}")
        if strict and len(contact) < 6:
            problems.append("corresponding author must include contact details ('address', 'contact', or 'phone')")
        if "orcid" in item and item.get("orcid") is not None:
            norm = _normalize_orcid(item.get("orcid"))
            if norm == "__INVALID__":
                problems.append(f"corresponding author has invalid ORCID: {item.get('orcid')!r}")
            elif norm:
                any_orcid = True

    if strict and authors and not any_orcid:
        problems.append("at least one author (typically the corresponding/lead author) must provide a valid ORCID iD")
    return problems


def structured_author_ready(project: Path) -> bool:
    path = project / AUTHOR_REL
    if not path.is_file():
        return False
    try:
        facts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return not validate_author_info(facts, strict=False)


def resolve_manuscript_title(project: Path, manuscript_path: Path | None = None) -> str:
    candidates = [p for p in (manuscript_path, project / INTEGRATION_MS_REL, project / "07_manuscript/full_manuscript.md", project / MASTER_TITLE_REL) if p is not None and p.is_file()]
    for path in candidates:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                return stripped[2:].strip()
    raise ValueError("cannot resolve manuscript title from integration/full_manuscript.md or title.md")


def render_author_lines(project: Path) -> list[str]:
    """Render deterministic author-block paragraphs from 00_input/author_info.json."""
    path = project / AUTHOR_REL
    if not path.is_file():
        raise FileNotFoundError(f"missing {AUTHOR_REL}")
    facts = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_author_info(facts, strict=False)
    if errors:
        raise ValueError("; ".join(errors))

    raw_affs = facts["affiliations"]
    ordered_affs: list[tuple[str, str]] = []
    if isinstance(raw_affs, list):
        for idx, entry in enumerate(raw_affs, start=1):
            if isinstance(entry, dict):
                key = str(entry.get("id", idx)).strip()
                label = str(entry.get("name") or entry.get("department") or entry.get("institution") or entry.get("text") or "").strip()
            else:
                key = str(idx)
                label = str(entry).strip()
            ordered_affs.append((key, label))
    else:
        for key, val in raw_affs.items():
            ordered_affs.append((str(key).strip(), str(val).strip()))

    key_to_num = {key: str(i) for i, (key, _) in enumerate(ordered_affs, start=1)}
    text_to_num = {label.casefold(): str(i) for i, (_, label) in enumerate(ordered_affs, start=1)}

    corr = facts["corresponding"]
    corr_list = corr if isinstance(corr, list) else [corr]
    corr_names = {str(item.get("name", "")).strip().casefold() for item in corr_list if isinstance(item, dict)}

    author_tokens: list[str] = []
    orcid_tokens: list[str] = []
    seen_orcids: set[str] = set()
    for author in facts["authors"]:
        if isinstance(author, str):
            name = author.strip()
            star = "*" if name.casefold() in corr_names else ""
            author_tokens.append(f"{name}{star}")
            continue
        name = str(author.get("name") or author.get("full_name") or "").strip()
        aff_refs = author.get("affiliations", author.get("affiliation"))
        if isinstance(aff_refs, (int, str)):
            aff_refs = [aff_refs]
        nums: list[str] = []
        for ref in aff_refs or []:
            sref = str(ref).strip()
            mapped = key_to_num.get(sref) or text_to_num.get(sref.casefold()) or sref
            if mapped not in nums:
                nums.append(mapped)
        star = "*" if name.casefold() in corr_names else ""
        badge = f" [{','.join(nums)}]" if nums else ""
        author_tokens.append(f"{name}{badge}{star}")
        norm_orcid = _normalize_orcid(author.get("orcid"))
        if norm_orcid and norm_orcid != "__INVALID__" and name.casefold() not in seen_orcids:
            orcid_tokens.append(f"{name}, {norm_orcid}")
            seen_orcids.add(name.casefold())

    for item in corr_list:
        if isinstance(item, dict):
            cname = str(item.get("name", "")).strip()
            norm_orcid = _normalize_orcid(item.get("orcid"))
            if cname and norm_orcid and norm_orcid != "__INVALID__" and cname.casefold() not in seen_orcids:
                orcid_tokens.append(f"{cname}, {norm_orcid}")
                seen_orcids.add(cname.casefold())

    lines = [
        "Authors: " + ", ".join(author_tokens),
        "Affiliations: " + "; ".join(f"[{i}] {label}" for i, (_, label) in enumerate(ordered_affs, start=1)),
    ]
    corr_segments: list[str] = []
    for item in corr_list:
        cname = str(item.get("name", "")).strip()
        email = str(item.get("email", "")).strip()
        contact = str(item.get("address") or item.get("contact") or item.get("phone") or item.get("institution") or "").strip()
        seg = cname
        if contact:
            seg += f", {contact}"
        seg += f" (Email: {email})"
        corr_segments.append(seg)
    lines.append("Corresponding author: " + "; ".join(corr_segments))
    if orcid_tokens:
        lines.append("ORCID: " + "; ".join(orcid_tokens))
    return lines


def render_title_page_markdown(project: Path, *, preserve_ref_count: bool = True) -> str:
    """Build deterministic title_page.md from the same single source."""
    title = resolve_manuscript_title(project)
    lines = render_author_lines(project)
    existing_ref_line = ""
    tp_path = project / TITLE_PAGE_MD_REL
    if preserve_ref_count and tp_path.is_file():
        for raw in tp_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if re.match(r"^\s*(?:number\s+of\s+references|reference\s+count|references)\s*:\s*\d+\b", raw, re.I):
                existing_ref_line = raw.strip()
                break
    blocks = [f"# {title}", *lines]
    if existing_ref_line:
        blocks.append(existing_ref_line)
    return "\n\n".join(blocks) + "\n"


def sync_title_page_markdown(project: Path, *, force: bool = False) -> Path | None:
    """Write 08_submission/integration/title_page.md when policy requires one (or --force)."""
    _, needs_sep, problems = title_page_policy(project)
    if problems and not force:
        raise ValueError("; ".join(problems))
    tp_path = project / TITLE_PAGE_MD_REL
    if not needs_sep and not force:
        if tp_path.is_file():
            tp_path.unlink()
        return None
    content = render_title_page_markdown(project, preserve_ref_count=True)
    tp_path.parent.mkdir(parents=True, exist_ok=True)
    tp_path.write_text(content, encoding="utf-8")
    return tp_path


def inject_docx_author_block(doc, project: Path, *, manuscript_inputs: list[Path] | None = None) -> None:
    """Insert the single-source author block on page 1 of a non-blinded manuscript DOCX."""
    if is_blinded(project) or not structured_author_ready(project):
        return
    lines = render_author_lines(project)
    existing_texts = [_norm_ws(p.text) for p in doc.paragraphs if p.text.strip()]
    if all(_norm_ws(line) in existing_texts for line in lines):
        return

    # Find the Abstract heading paragraph; insert right before it (i.e. right under Title on page 1).
    insert_before = None
    title_seen = False
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        if not title_seen:
            title_seen = True
            continue
        if txt.casefold() == "abstract":
            insert_before = p
            break
    if insert_before is None:
        return
    for line in lines:
        insert_before.insert_paragraph_before(line)


def _docx_front_paragraphs(path: Path) -> tuple[str, list[str]]:
    """Extract (title, paragraphs_before_abstract_or_end) from a DOCX file."""
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    paras: list[str] = []
    for p in root.findall(".//w:p", NS):
        txt = "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()
        if txt:
            paras.append(_norm_ws(txt.replace("\u00a0", " ")))
    if not paras:
        return "", []
    title = paras[0]
    rest: list[str] = []
    for txt in paras[1:]:
        if txt.casefold() == "abstract":
            break
        if re.match(r"^(?:number\s+of\s+references|reference\s+count|references)\s*:\s*\d+\b", txt, re.I):
            continue
        rest.append(txt)
    return title, rest


def verify_author_placement(project: Path, stage_id: str) -> list[str]:
    """Enforce v1.28+ author-placement and single-source consistency across S20-S25."""
    problems: list[str] = []
    ms_has_authors, needs_sep, pol_problems = title_page_policy(project)
    problems.extend(pol_problems)

    if stage_id == "S20_journal":
        return problems

    author_path = project / AUTHOR_REL
    if not author_path.is_file():
        return problems + [f"{AUTHOR_REL} missing"]
    try:
        facts = json.loads(author_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return problems + [f"{AUTHOR_REL}: invalid JSON ({exc})"]

    problems.extend(validate_author_info(facts, strict=True))
    if problems:
        return problems

    expected_title = resolve_manuscript_title(project)
    expected_lines = [_norm_ws(line.replace("\u00a0", " ")) for line in render_author_lines(project)]

    tp_md = project / TITLE_PAGE_MD_REL
    if needs_sep:
        if not tp_md.is_file():
            problems.append(
                f"{TITLE_PAGE_MD_REL} missing (required because journal is double-blind or explicitly mandates a separate title page); "
                "run tools/manuscript/author_block.py sync"
            )
        else:
            rendered = render_title_page_markdown(project, preserve_ref_count=True)
            if _norm_ws(tp_md.read_text(encoding="utf-8", errors="replace")) != _norm_ws(rendered):
                problems.append(
                    f"{TITLE_PAGE_MD_REL} diverges from single-source {AUTHOR_REL}; "
                    "regenerate with tools/manuscript/author_block.py sync"
                )
    else:
        if tp_md.is_file():
            problems.append(
                f"{TITLE_PAGE_MD_REL} should not exist for a non-blinded journal that does not explicitly require a separate title page; "
                "run tools/manuscript/author_block.py sync to clean up"
            )

    if stage_id not in {"S23_package", "S24_package_human_review", "S25_submission_audit"}:
        return problems

    manifest_path = project / MANIFEST_REL
    if not manifest_path.is_file():
        return problems + [f"{MANIFEST_REL} missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return problems + [f"{MANIFEST_REL}: invalid JSON ({exc})"]

    uploads_by_role: dict[str, list[Path]] = {}
    for item in manifest.get("items", []):
        if item.get("upload", True) is False:
            continue
        role = str(item.get("role", "")).strip().casefold()
        raw = str(item.get("file", "")).strip()
        if raw:
            try:
                _, resolved = _safe_path(project, raw)
                uploads_by_role.setdefault(role, []).append(resolved)
            except ValueError as exc:
                problems.append(str(exc))

    ms_files = [p for p in uploads_by_role.get("manuscript", []) if p.is_file() and p.suffix.lower() == ".docx"]
    tp_files = [p for p in uploads_by_role.get("title_page", []) if p.is_file() and p.suffix.lower() == ".docx"]

    if not ms_files:
        problems.append("manifest lacks a built manuscript DOCX")
    else:
        ms_title, ms_front = _docx_front_paragraphs(ms_files[0])
        if ms_has_authors:
            if _norm_ws(ms_title) != _norm_ws(expected_title):
                problems.append("manuscript.docx first-page title differs from selected title")
            if ms_front != expected_lines:
                problems.append(
                    "non-blinded manuscript.docx page 1 lacks the exact single-source author block "
                    "(title, authors, affiliations, corresponding author + contact, ORCID); rebuild with build_docx.py"
                )
        else:
            if ms_front:
                problems.append("double-blind manuscript.docx must remain anonymous before Abstract (found front-matter lines)")
            from .journalspec import blind_problems
            problems.extend(blind_problems(ms_files[0], project, "manuscript"))

    if needs_sep:
        if not tp_files:
            problems.append("separate title_page.docx upload is required by blinding/guideline rule but missing from manifest")
        else:
            tp_title, tp_front = _docx_front_paragraphs(tp_files[0])
            if _norm_ws(tp_title) != _norm_ws(expected_title) or tp_front != expected_lines:
                problems.append(
                    "title_page.docx diverges from single-source 00_input/author_info.json; "
                    "run author_block.py sync and rebuild title_page.docx"
                )
    else:
        if "title_page" in uploads_by_role:
            problems.append(
                "non-blinded journal without an explicit separate-title-page guideline rule must NOT upload a separate title_page.docx"
            )
    return problems
