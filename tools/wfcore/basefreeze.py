"""Base Manuscript & Research Core Freeze Engine.

Freezes all foundational research assets and canonical manuscript files at the end of S17,
BEFORE any journal selection (S18) or journal-specific adaptations (S19/S20).
Guarantees that 01_protocol/ through 07_manuscript/ remain strictly read-only and unpolluted
by journal-specific cuts, word limits, or idiosyncratic reformatting.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

BASE_FREEZE_REL = "07_manuscript/base_manuscript_freeze.json"

# Core canonical manuscript files that must exist at base freeze
MANDATORY_MANUSCRIPT_FILES = (
    "07_manuscript/title_page.md",
    "07_manuscript/abstract.md",
    "07_manuscript/introduction.md",
    "07_manuscript/methods.md",
    "07_manuscript/results.md",
    "07_manuscript/discussion.md",
    "07_manuscript/statements.md",
    "07_manuscript/manuscript_complete.md",
    "07_manuscript/review_report.md",
)

# Foundational research assets to freeze
RESEARCH_CORE_GLOBS = (
    "01_protocol/*.json",
    "01_protocol/*.md",
    "02_data/*.md",
    "02_data/*.json",
    "03_analysis/results/*.json",
    "03_analysis/notes.md",
    "04_tables/main/*.xlsx",
    "04_tables/supplementary/*.xlsx",
    "04_tables/*.md",
    "05_figures/legends.md",
    "05_figures/out/*",
    "06_refs/library.json",
    "06_refs/verified.json",
    "06_refs/refs.bib",
    "06_refs/refs.ris",
    "07_manuscript/*.md",
)


def _safe_path(project: Path, raw: str) -> tuple[str, Path]:
    rel = PurePosixPath(str(raw).replace("\\", "/"))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise ValueError(f"unsafe project-relative path: {raw}")
    normalized = rel.as_posix()
    path = project.joinpath(*rel.parts).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError as exc:
        raise ValueError(f"path leaves the project directory: {raw}") from exc
    return normalized, path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def collect_base_files(project: Path) -> dict[str, Path]:
    """Collect all canonical research core and manuscript files that must be frozen."""
    project = project.resolve()
    files: dict[str, Path] = {}
    missing_mandatory: list[str] = []

    # 1. Check mandatory manuscript files
    for rel in MANDATORY_MANUSCRIPT_FILES:
        norm, p = _safe_path(project, rel)
        if not p.is_file():
            missing_mandatory.append(norm)
        else:
            files[norm] = p

    if missing_mandatory:
        raise ValueError("Cannot freeze base manuscript: mandatory files missing: " + ", ".join(missing_mandatory))

    # 2. Collect core research files across earlier stages
    for pattern in RESEARCH_CORE_GLOBS:
        for p in project.glob(pattern):
            if p.is_file() and p.name != ".gitkeep" and "base_manuscript_freeze.json" not in p.name:
                rel = p.relative_to(project).as_posix()
                files[rel] = p

    return dict(sorted(files.items()))


def build_base_freeze(project: Path) -> dict:
    """Build the base manuscript freeze manifest with cryptographic hashes."""
    files = collect_base_files(project)
    records = [
        {"path": rel, "sha256": _sha256(path), "size": path.stat().st_size}
        for rel, path in files.items()
    ]
    aggregate_hash = hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()

    return {
        "schema_version": 1,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Canonical base manuscript freeze before target journal selection and adaptation",
        "aggregate_hash": aggregate_hash,
        "file_count": len(records),
        "files": records,
    }


def write_base_freeze(project: Path, target: Path | None = None) -> Path:
    """Write the base freeze manifest to disk."""
    target_path = target.resolve() if target else (project / BASE_FREEZE_REL).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_data = build_base_freeze(project)
    target_path.write_text(json.dumps(freeze_data, indent=2), encoding="utf-8")
    return target_path


def verify_base_freeze(project: Path, freeze_path: Path | None = None) -> tuple[bool, list[str], int]:
    """Verify that no canonical base file has been modified, corrupted, or deleted."""
    target_path = freeze_path.resolve() if freeze_path else (project / BASE_FREEZE_REL).resolve()
    if not target_path.is_file():
        return False, [f"Base freeze manifest missing: {target_path.name}"], 0

    try:
        data = json.loads(target_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, [f"Corrupted base freeze JSON: {exc}"], 0

    files = data.get("files", [])
    if not isinstance(files, list) or not files:
        return False, ["Base freeze manifest contains no file records"], 0

    problems: list[str] = []
    verified_count = 0

    for item in files:
        rel = item.get("path")
        expected_sha = item.get("sha256")
        expected_size = item.get("size")
        if not rel or not expected_sha:
            problems.append(f"Invalid record in base freeze manifest: {item}")
            continue

        try:
            norm, p = _safe_path(project, rel)
        except ValueError as e:
            problems.append(str(e))
            continue

        if not p.is_file():
            problems.append(f"Frozen base file missing: {norm}")
            continue

        act_size = p.stat().st_size
        if expected_size is not None and act_size != expected_size:
            problems.append(f"Frozen base file modified (size {act_size} != {expected_size}): {norm}")
            continue

        act_sha = _sha256(p)
        if act_sha != expected_sha:
            problems.append(f"Frozen base file modified (hash mismatch): {norm}")
            continue

        verified_count += 1

    return len(problems) == 0, problems, verified_count
