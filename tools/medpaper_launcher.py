#!/usr/bin/env python3
"""Initialize or safely upgrade a MedPaper workspace from a template directory or bundle.

Supports both directory master templates (for Antigravity/Gemini clones on any drive or OS,
resolved via --template-source, MEDPAPER_MASTER_TEMPLATE, the checkout containing this
script, or the local author default F:\\workspace\\medpapaer\\gemini) and packaged ZIP
archives. Upgrading an existing workspace updates only engine files while strictly
preserving project/ (including .wf/state.json and engine_pin), .venv/, and .git/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


SKILL_DIR = Path(__file__).resolve().parents[1]
ARCHIVE = SKILL_DIR / "assets" / "medpaper-codex-ready.zip"
ARCHIVE_ROOT = "medpaper-codex"
DEFAULT_LOCAL_MASTER = Path(r"F:\workspace\medpapaer\gemini")
EXCLUDED_TEMPLATE_DIRS = {
    ".git", ".venv", "dist", "scratch", "temp",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
EXCLUDED_TEMPLATE_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp"}
REQUIRED_TEMPLATE_PATHS = (
    "pipeline/pipeline.toml",
    "tools/wf.py",
    "requirements.txt",
    ".agent/rules/medpaper-pipeline.md",
    ".agents/skills/medpaper-pipeline/SKILL.md",
)


def is_pipeline(path: Path) -> bool:
    return (path / "pipeline" / "pipeline.toml").is_file() and (path / "tools" / "wf.py").is_file()


def validate_template_dir(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        raise RuntimeError(f"template source directory does not exist: {path}")
    missing = [rel for rel in REQUIRED_TEMPLATE_PATHS if not (path / rel).is_file()]
    if not (path / "reference").is_dir():
        missing.append("reference/")
    if missing:
        raise RuntimeError(
            f"template source {path} is incomplete (missing: {', '.join(missing)}); "
            "refusing partial workspace copy/upgrade"
        )


def resolve_template_source(explicit: Path | None = None) -> tuple[str, Path]:
    """Return ('dir' | 'zip', resolved_path) or raise a clear RuntimeError."""
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if candidate.is_file() and candidate.suffix.lower() == ".zip":
            return "zip", candidate
        validate_template_dir(candidate)
        return "dir", candidate

    env_raw = os.environ.get("MEDPAPER_MASTER_TEMPLATE", "").strip()
    if env_raw:
        candidate = Path(env_raw).expanduser().resolve()
        if candidate.is_file() and candidate.suffix.lower() == ".zip":
            return "zip", candidate
        validate_template_dir(candidate)
        return "dir", candidate

    if ARCHIVE.is_file():
        return "zip", ARCHIVE

    if is_pipeline(SKILL_DIR):
        validate_template_dir(SKILL_DIR)
        return "dir", SKILL_DIR

    if DEFAULT_LOCAL_MASTER.exists():
        validate_template_dir(DEFAULT_LOCAL_MASTER)
        return "dir", DEFAULT_LOCAL_MASTER

    raise RuntimeError(
        "no valid MedPaper template source found. Checked --template-source, "
        "MEDPAPER_MASTER_TEMPLATE, bundled archive, checkout root "
        f"({SKILL_DIR}), and {DEFAULT_LOCAL_MASTER}. Pass --template-source <dir> "
        "or set MEDPAPER_MASTER_TEMPLATE."
    )


def pipeline_version(path: Path) -> str:
    definition = path / "pipeline" / "pipeline.toml"
    data = tomllib.loads(definition.read_text(encoding="utf-8"))
    return str(data.get("meta", {}).get("version", "unknown"))


def source_version(kind: str, src: Path) -> str:
    if kind == "zip":
        with zipfile.ZipFile(src) as zf:
            raw = zf.read(f"{ARCHIVE_ROOT}/pipeline/pipeline.toml").decode("utf-8")
        return str(tomllib.loads(raw).get("meta", {}).get("version", "unknown"))
    return pipeline_version(src)


def default_workspace() -> Path:
    current = Path.cwd().resolve()
    return current if is_pipeline(current) else current / "medpaper-study"


def safe_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for info in zf.infolist():
        name = PurePosixPath(info.filename)
        if name.is_absolute() or ".." in name.parts:
            raise RuntimeError(f"unsafe archive member: {info.filename}")
        if not name.parts or name.parts[0] != ARCHIVE_ROOT:
            raise RuntimeError(f"unexpected archive root: {info.filename}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise RuntimeError(f"symbolic links are not allowed: {info.filename}")
        relative = PurePosixPath(*name.parts[1:])
        if relative.parts:
            members.append((info, relative))
    return members


def _stage_template_to_dir(kind: str, src: Path, temp_root: Path, *, include_project_skeleton: bool) -> None:
    if kind == "zip":
        with zipfile.ZipFile(src) as zf:
            members = safe_members(zf)
            corrupt = zf.testzip()
            if corrupt:
                raise RuntimeError(f"bundled archive failed integrity check at {corrupt}")
            for info, relative in members:
                if not include_project_skeleton and relative.parts[0] == "project":
                    continue
                destination = temp_root.joinpath(*relative.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, destination.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
        return

    validate_template_dir(src)
    for item in sorted(src.rglob("*")):
        if item.is_symlink():
            raise RuntimeError(f"symbolic links are not allowed in template source: {item}")
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        if any(part in EXCLUDED_TEMPLATE_DIRS for part in rel.parts) or item.suffix.lower() in EXCLUDED_TEMPLATE_SUFFIXES:
            continue
        if rel.name == ".medpaper-engine.json":
            continue
        if rel.parts[0] == "project":
            if not include_project_skeleton or rel.as_posix() != "project/.gitkeep":
                continue
        destination = temp_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination)
    if include_project_skeleton:
        gitkeep = temp_root / "project" / ".gitkeep"
        gitkeep.parent.mkdir(parents=True, exist_ok=True)
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")


def extract_new(workspace: Path, template_source: Path | None = None) -> None:
    kind, src = resolve_template_source(template_source)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists() and any(workspace.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty directory: {workspace}")

    temp_root = Path(tempfile.mkdtemp(prefix=".medpaper-install-", dir=workspace.parent))
    try:
        _stage_template_to_dir(kind, src, temp_root, include_project_skeleton=True)
        if not is_pipeline(temp_root):
            raise RuntimeError("template source did not produce a valid medpaper pipeline")
        if workspace.exists():
            workspace.rmdir()
        temp_root.replace(workspace)
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def refresh_existing(workspace: Path, template_source: Path | None = None, *, force_same_version: bool = False) -> bool:
    """Replace only engine files; strictly preserve project/ (and engine_pin), .venv/, .git/."""
    kind, src = resolve_template_source(template_source)
    if src.is_dir() and src.resolve() == workspace.resolve():
        return False
    installed = pipeline_version(workspace)
    baseline = workspace / ".medpaper-engine.json"
    if baseline.is_file():
        try:
            manifest = json.loads(baseline.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("Installed engine baseline is unreadable; preserve the workspace for explicit maintenance") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), dict) or not manifest["files"]:
            raise RuntimeError("Installed engine baseline is invalid; maintain explicitly rather than silently refreshing study code")
        for relative, expected in manifest["files"].items():
            part = PurePosixPath(relative)
            file = (workspace / part).resolve()
            if part.is_absolute() or ".." in part.parts or not file.is_relative_to(workspace.resolve()) or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
                raise RuntimeError("Installed engine was modified; preserve it and report the maintenance defect before upgrade: " + relative)
    target_version = source_version(kind, src)
    if installed == target_version and not force_same_version:
        return False
    temp_root = Path(tempfile.mkdtemp(prefix=".medpaper-refresh-", dir=workspace.parent))
    try:
        _stage_template_to_dir(kind, src, temp_root, include_project_skeleton=False)
        workspace_resolved = workspace.resolve()
        updates = []
        for source in temp_root.rglob("*"):
            if not source.is_file():
                continue
            rel = source.relative_to(temp_root)
            if rel.parts[0] in {"project", ".venv", ".git"}:
                continue
            destination = workspace / rel
            try:
                destination.resolve().relative_to(workspace_resolved)
            except ValueError as exc:
                raise RuntimeError(f"unsafe engine refresh target: {destination}") from exc
            if destination.is_dir():
                raise RuntimeError(f"engine file conflicts with an existing directory: {destination}")
            updates.append((source, destination))
        for source, destination in updates:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
        if baseline.is_file():
            sys.path.insert(0, str(workspace / "tools"))
            from wfcore.engineintegrity import engine_member
            refreshed_files = {
                p.relative_to(workspace).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(workspace.rglob("*"))
                if p.is_file()
                and not any(part in EXCLUDED_TEMPLATE_DIRS for part in p.relative_to(workspace).parts)
                and p.relative_to(workspace).parts[0] != "project"
                and engine_member(p.relative_to(workspace).as_posix())
            }
            baseline.write_text(json.dumps({"schema_version": 1, "files": refreshed_files}, sort_keys=True, indent=2), encoding="utf-8")
        print(f"updated medpaper engine {installed} -> {target_version}; project/, .venv/ and engine_pin preserved")
        return True
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def run_pipeline(workspace: Path, no_bootstrap: bool, refreshed: bool = False) -> int:
    if no_bootstrap:
        print(f"medpaper workspace ready: {workspace}")
        return 0
    uv = shutil.which("uv")
    venv_python = workspace / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not venv_python.is_file():
        if not uv:
            raise RuntimeError("uv was not found on PATH; install uv before bootstrapping medpaper")
        command = [uv, "run", "--python", "3.13", "python", "bootstrap.py"]
    elif refreshed:
        if not uv:
            raise RuntimeError("uv was not found on PATH; it is required to refresh pinned dependencies")
        command = [uv, "run", "--python", "3.13", "python", "bootstrap.py", "--skip-selftest"]
    else:
        command = [str(venv_python), "tools/wf.py", "status"]
    print(f"medpaper workspace: {workspace}")
    result = subprocess.run(command, cwd=workspace).returncode
    if result == 0 and command[-1] != "status":
        return subprocess.run([str(venv_python), "tools/wf.py", "status"], cwd=workspace).returncode
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="initialize, resume, or safely upgrade a medpaper pipeline workspace")
    parser.add_argument("--workspace", type=Path, help="target workspace; defaults to cwd or cwd/medpaper-study")
    parser.add_argument("--template-source", type=Path, help="master template directory or archive (overrides MEDPAPER_MASTER_TEMPLATE)")
    parser.add_argument("--upgrade", action="store_true", help="explicitly upgrade engine files in an existing workspace while preserving project/ and .venv/")
    parser.add_argument("--no-bootstrap", action="store_true", help="copy/upgrade files only without running bootstrap")
    args = parser.parse_args(argv)

    workspace = (args.workspace.expanduser() if args.workspace else default_workspace()).resolve()
    try:
        refreshed = False
        if not is_pipeline(workspace):
            extract_new(workspace, args.template_source)
            print(f"installed medpaper pipeline {pipeline_version(workspace)} at {workspace}")
        else:
            refreshed = refresh_existing(workspace, args.template_source, force_same_version=args.upgrade)
            print(f"resuming existing medpaper workspace at {workspace}")
        return run_pipeline(workspace, args.no_bootstrap, refreshed)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"medpaper launcher error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
