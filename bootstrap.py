#!/usr/bin/env python3
"""One-command setup. Stdlib only, so it runs before anything is installed.

    python bootstrap.py

Creates .venv, installs requirements.txt into it, wires the agent adapters, initialises the
project folders, then runs doctor and the self test. Safe to re-run.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd: list[str], label: str, optional: bool = False) -> bool:
    print(f"\n>>> {label}")
    print(f"    {' '.join(str(c) for c in cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=ROOT)
    except FileNotFoundError:
        print(f"    !! {cmd[0]} not found")
        return False
    if proc.returncode != 0:
        print(f"    !! exited {proc.returncode}" + ("  (optional, continuing)" if optional else ""))
        return False
    return True


def make_venv(uv: str | None) -> bool:
    if venv_python().exists():
        print(f"\n>>> virtualenv already present at {VENV.name}")
        return True
    if uv:
        return run([uv, "venv", str(VENV)], "create virtualenv (uv)")
    return run([sys.executable, "-m", "venv", str(VENV)], "create virtualenv (stdlib venv)")


def install(uv: str | None) -> bool:
    req = ROOT / "requirements.txt"
    if not req.exists():
        print("!! requirements.txt missing")
        return False
    if uv:
        return run([uv, "pip", "install", "--python", str(venv_python()), "-r", str(req)],
                   "install science dependencies (uv)")
    return run([str(venv_python()), "-m", "pip", "install", "-r", str(req)],
               "install science dependencies (pip)")


def main() -> int:
    ap = argparse.ArgumentParser(description="set up the medpaper pipeline")
    ap.add_argument("--skip-venv", action="store_true", help="use the current interpreter")
    ap.add_argument("--skip-selftest", action="store_true")
    args = ap.parse_args()

    if sys.version_info < (3, 11):
        print(f"Python 3.11+ required (tomllib). Found {sys.version.split()[0]}")
        return 1

    print("=" * 74)
    print("medpaper bootstrap")
    print(f"  repo   {ROOT}")
    print(f"  python {sys.version.split()[0]}")
    uv = shutil.which("uv")
    print(f"  uv     {uv or 'not found (falling back to venv + pip)'}")
    print("=" * 74)

    ok_env = True
    if not args.skip_venv:
        ok_env = make_venv(uv) and install(uv)
        if not ok_env:
            print("\n!! dependency install failed. The workflow driver still works "
                  "(it is stdlib only); figures and tables will not.")

    run([sys.executable, "tools/wf.py", "init"], "scaffold project/ and create run state",
        optional=True)
    run([sys.executable, "tools/wf.py", "doctor"], "environment check", optional=True)

    if ok_env and not args.skip_selftest and venv_python().exists():
        run([str(venv_python()), "tools/selftest.py"], "self test", optional=True)

    print("\n" + "=" * 74)
    print("Start work with:")
    print("    uv run python tools/wf.py status")
    print("\nThen put your research idea file in project/00_input/ and follow the stage card.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
