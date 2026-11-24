"""Detect changed installed engine files without git or claims of an OS security sandbox."""
import hashlib,json
from pathlib import Path,PurePosixPath

BASELINE=".medpaper-engine.json"
PREFIXES=("tools/","pipeline/","reference/",".agents/",".agent/")
_VERIFIED_ENGINES: dict[Path, tuple[int, int, tuple[tuple[str, int, int], ...]]] = {}


def engine_member(name):
    return name.startswith(PREFIXES) or name in {"AGENTS.md","bootstrap.py","requirements.txt","requirements-guides.txt"}


def verify_engine(root,required=False):
    root=Path(root).resolve(); baseline=root/BASELINE
    if not baseline.is_file():
        if required: raise ValueError("Required installed-engine baseline is missing; repair through maintenance, never silently downgrade to legacy mode")
        return "maintenance/legacy checkout: no packaged baseline; not certified immutable"
    bstat = baseline.stat()
    cached = _VERIFIED_ENGINES.get(root)
    if cached and cached[0] == bstat.st_size and cached[1] == bstat.st_mtime_ns:
        stats_ok = True
        for rel, exp_size, exp_mtime in cached[2]:
            p = root / rel
            try:
                st = p.stat()
            except OSError:
                stats_ok = False
                break
            if st.st_size != exp_size or st.st_mtime_ns != exp_mtime:
                stats_ok = False
                break
        if stats_ok:
            return "packaged engine identity matches"
    row=json.loads(baseline.read_text(encoding="utf-8"))
    if not isinstance(row,dict) or row.get("schema_version")!=1 or not isinstance(row.get("files"),dict) or not row["files"]: raise ValueError("Installed engine baseline is invalid; repair through workflow maintenance, never a study-side reset")
    defects=[]
    stat_snapshot = []
    for relative,expected in row["files"].items():
        part=PurePosixPath(relative)
        if part.is_absolute() or ".." in part.parts or not engine_member(relative): raise ValueError("Invalid engine baseline path")
        path=(root/part).resolve()
        if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            defects.append(relative)
        else:
            st = path.stat()
            stat_snapshot.append((relative, st.st_size, st.st_mtime_ns))
    if defects:
        _VERIFIED_ENGINES.pop(root, None)
        raise ValueError("Installed engine changed: "+", ".join(defects[:8])+". Stop study work; report a focused maintenance defect. Do not edit engine/state or weaken integrity gates to proceed.")
    _VERIFIED_ENGINES[root] = (bstat.st_size, bstat.st_mtime_ns, tuple(stat_snapshot))
    return "packaged engine identity matches"
