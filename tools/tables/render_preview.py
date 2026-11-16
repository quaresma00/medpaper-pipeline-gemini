#!/usr/bin/env python3
"""Render Excel three-line tables to cropped PNG previews and run deterministic layout QC.

Usage:
    uv run python tools/tables/render_preview.py --all
    uv run python tools/tables/render_preview.py --table "Table 1"
    uv run python tools/tables/render_preview.py --table "Table S1" --engine python
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from wfcore import paths as wfpaths  # noqa: E402
from wfcore.readiness import atomic_json, load as load_json  # noqa: E402
from wfcore.packagefreeze import _safe_path, _sha256  # noqa: E402


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(name).strip()).strip("_") or "Table"


def _crop_whitespace(png_path: Path, pad_px: int = 24) -> None:
    """Trim uniform white borders while keeping clean symmetric margins."""
    with Image.open(png_path) as im:
        rgb = im.convert("RGB")
        bg = Image.new("RGB", rgb.size, (255, 255, 255))
        diff = ImageChops.difference(rgb, bg)
        bbox = diff.getbbox()
        if bbox is None:
            return
        x0 = max(0, bbox[0] - pad_px)
        y0 = max(0, bbox[1] - pad_px)
        x1 = min(rgb.width, bbox[2] + pad_px)
        y1 = min(rgb.height, bbox[3] + pad_px)
        cropped = rgb.crop((x0, y0, x1, y1))
        cropped.save(png_path, format="PNG")


def _table_entries(project: Path, tables_filter: list[str] | None = None) -> list[dict]:
    plan_path = project / "01_protocol" / "artifact_plan.json"
    entries: list[dict] = []
    if plan_path.is_file():
        plan = load_json(project, "01_protocol/artifact_plan.json")
        for grp in ("main_tables", "supp_tables"):
            for e in plan.get(grp, []):
                if e.get("file"):
                    entries.append(e)
    else:
        for p in sorted((project / "04_tables" / "main").glob("*.xlsx")) + sorted((project / "04_tables" / "supplementary").glob("*.xlsx")):
            wb = load_workbook(p, read_only=True, data_only=True)
            try:
                for sh_name in wb.sheetnames:
                    entries.append({"id": sh_name, "sheet": sh_name, "file": p.relative_to(project).as_posix()})
            finally:
                wb.close()
    if tables_filter:
        wanted = [t.strip().casefold() for t in tables_filter if t.strip()]
        entries = [
            e for e in entries
            if any(
                w == str(e.get("id", "")).strip().casefold()
                or w == str(e.get("sheet", "")).strip().casefold()
                or w.replace(" ", "") == str(e.get("id", "")).strip().casefold().replace(" ", "")
                for w in wanted
            )
        ]
    return entries


def _inspect_sheet_layout(ws) -> list[dict]:
    """Deterministic layout QA on Excel column widths, wrapping, alignment adjacency, and print setup."""
    warnings_and_fails: list[dict] = []
    ncol = ws.max_column or 1
    nrow = ws.max_row or 1
    col_widths = [float(ws.column_dimensions[get_column_letter(c)].width or 12.0) for c in range(1, ncol + 1)]
    total_width = sum(col_widths)

    merged_anchors: set[tuple[int, int]] = set()
    for rng in ws.merged_cells.ranges:
        merged_anchors.add((rng.min_row, rng.min_col))

    unwrapped_overflow: list[str] = []
    max_fill_ratio = [0.0] * ncol
    dominant_align: list[str] = []
    for c in range(1, ncol + 1):
        align_counts: dict[str, int] = {}
        w_eff = max(4.0, col_widths[c - 1] - 1.5)
        for r in range(2, nrow + 1):
            val = ws.cell(r, c).value
            if val is None or str(val).strip() == "":
                continue
            if (r, c) in merged_anchors and c == 1:
                continue  # Title or merged footnote spans across full width
            cell = ws.cell(r, c)
            h_align = (cell.alignment.horizontal or ("left" if c == 1 else "center")).lower()
            align_counts[h_align] = align_counts.get(h_align, 0) + 1
            text_lines = str(val).splitlines() or [""]
            longest = max(len(ln) for ln in text_lines)
            indent = int(cell.alignment.indent or 0) * 2
            ratio = (longest + indent) / w_eff
            max_fill_ratio[c - 1] = max(max_fill_ratio[c - 1], ratio)
            if not cell.alignment.wrap_text and ratio > 1.05:
                unwrapped_overflow.append(f"{get_column_letter(c)}{r} ({longest} chars > width {col_widths[c-1]:.1f})")
        dom = max(align_counts, key=align_counts.get) if align_counts else ("left" if c == 1 else "center")
        dominant_align.append(dom)

    if unwrapped_overflow:
        warnings_and_fails.append({
            "check": "wrapped_text_audit",
            "ok": False,
            "severity": "fail",
            "detail": f"{len(unwrapped_overflow)} cell(s) disable wrap_text and risk truncation: {'; '.join(unwrapped_overflow[:4])}",
        })
    else:
        warnings_and_fails.append({
            "check": "wrapped_text_audit",
            "ok": True,
            "severity": "fail",
            "detail": "all body/header cells either wrap cleanly or fit within declared column widths",
        })

    touch_risks: list[str] = []
    for c in range(ncol - 1):
        if dominant_align[c] == "right" and dominant_align[c + 1] == "left":
            if max_fill_ratio[c] > 0.88 and max_fill_ratio[c + 1] > 0.88:
                touch_risks.append(f"col {c + 1} (right) -> col {c + 2} (left) tight gap")
    warnings_and_fails.append({
        "check": "adjacent_column_touch_risk",
        "ok": not touch_risks,
        "severity": "warn",
        "detail": "; ".join(touch_risks) if touch_risks else "no tight right-to-left adjacent column pairs detected",
    })

    if total_width > 95.0 and (ws.page_setup.orientation or "portrait").lower() != "landscape":
        warnings_and_fails.append({
            "check": "landscape_page_fit",
            "ok": False,
            "severity": "warn",
            "detail": f"wide table (total column width {total_width:.1f} > 95) should set orientation='landscape' and fitToWidth=1",
        })
    else:
        warnings_and_fails.append({
            "check": "landscape_page_fit",
            "ok": True,
            "severity": "warn",
            "detail": f"page orientation ({ws.page_setup.orientation or 'default'}) fits table width ({total_width:.1f})",
        })

    if nrow > 35 and not str(ws.print_title_rows or "").strip():
        warnings_and_fails.append({
            "check": "print_title_rows",
            "ok": False,
            "severity": "warn",
            "detail": f"long table ({nrow} rows) lacks print_title_rows ('1:2') to repeat headers across printed pages",
        })
    else:
        warnings_and_fails.append({
            "check": "print_title_rows",
            "ok": True,
            "severity": "warn",
            "detail": f"print_title_rows={ws.print_title_rows or '(single-page fit)'}",
        })

    return warnings_and_fails


def _render_excel_com(xlsx: Path, sheet_name: str, out_base: Path, dpi: int) -> list[Path] | None:
    """Render one worksheet via headless Windows Excel COM -> PDF -> pdftoppm PNG."""
    if os.name != "nt" or not shutil.which("pdftoppm"):
        return None
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        return None
    with tempfile.TemporaryDirectory(prefix="medpaper_tbl_com_") as tmpdir:
        tmp = Path(tmpdir)
        pdf_path = tmp / f"{out_base.stem}.pdf"
        ps_script = tmp / "export.ps1"
        ps_script.write_text(
            "\n".join([
                "$ErrorActionPreference = 'Stop'",
                "$excel = $null",
                "$wb = $null",
                "try {",
                "  $excel = New-Object -ComObject Excel.Application",
                "  $excel.Visible = $false",
                "  $excel.DisplayAlerts = $false",
                "  $excel.ScreenUpdating = $false",
                f"  $wb = $excel.Workbooks.Open('{str(xlsx).replace(chr(39), chr(39)*2)}', 0, $true)",
                f"  $ws = $wb.Worksheets.Item('{sheet_name.replace(chr(39), chr(39)*2)}')",
                f"  $ws.ExportAsFixedFormat(0, '{str(pdf_path).replace(chr(39), chr(39)*2)}')",
                "} finally {",
                "  if ($wb -ne $null) { $wb.Close($false) | Out-Null }",
                "  if ($excel -ne $null) { $excel.Quit() | Out-Null }",
                "}",
            ]),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_script)],
                capture_output=True, text=True, timeout=45,
            )
            if proc.returncode != 0 or not pdf_path.is_file():
                return None
            prefix = tmp / "page"
            pdftoppm = shutil.which("pdftoppm")
            pproc = subprocess.run(
                [pdftoppm, "-png", "-r", str(dpi), str(pdf_path), str(prefix)],
                capture_output=True, text=True, timeout=45,
            )
            if pproc.returncode != 0:
                return None
            pages = sorted(tmp.glob("page-*.png"))
            if not pages:
                return None
            written: list[Path] = []
            for idx, page in enumerate(pages, 1):
                target = out_base if idx == 1 else out_base.with_name(f"{out_base.stem}_p{idx}.png")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(page, target)
                _crop_whitespace(target)
                written.append(target)
            return written
        except (OSError, subprocess.TimeoutExpired):
            return None


def _render_python(ws, out_base: Path, dpi: int) -> list[Path]:
    """Cross-platform deterministic three-line table renderer matching Excel widths and wrapping."""
    ncol = max(1, ws.max_column or 1)
    nrow = max(1, ws.max_row or 1)
    col_widths = [float(ws.column_dimensions[get_column_letter(c)].width or 14.0) for c in range(1, ncol + 1)]
    total_char_w = max(40.0, sum(col_widths))

    # Locate three horizontal rule boundaries
    top_rows = [r for r in range(1, nrow + 1) if any(ws.cell(r, c).border.top and ws.cell(r, c).border.top.style for c in range(1, ncol + 1))]
    bot_rows = [r for r in range(1, nrow + 1) if any(ws.cell(r, c).border.bottom and ws.cell(r, c).border.bottom.style for c in range(1, ncol + 1))]
    hdr_start = min(top_rows) if top_rows else 2
    last_body = max(bot_rows) if bot_rows else nrow
    hdr_end = max([r for r in bot_rows if hdr_start <= r < last_body] or [hdr_start])

    title_text = " ".join(str(ws.cell(1, c).value or "") for c in range(1, ncol + 1)).strip()

    def _wrap_cell(text: str, char_w: float, indent: int = 0) -> list[str]:
        s = (text or "").strip()
        if not s:
            return [""]
        cap = max(6, int((char_w - 1.5 - indent * 2.0) * 0.92))
        out: list[str] = []
        for part in s.splitlines():
            out.extend(textwrap.wrap(part, width=cap, break_long_words=False) or [""])
        return out

    title_lines = _wrap_cell(title_text, total_char_w * 0.95)
    headers: list[list[dict]] = []
    for r in range(hdr_start, hdr_end + 1):
        row_items = []
        for c in range(1, ncol + 1):
            cell = ws.cell(r, c)
            row_items.append({
                "lines": _wrap_cell("" if cell.value is None else str(cell.value), col_widths[c - 1]),
                "align": (cell.alignment.horizontal or ("left" if c == 1 else "center")).lower(),
                "bold": bool(cell.font and cell.font.bold),
            })
        headers.append(row_items)

    body_rows: list[list[dict]] = []
    for r in range(hdr_end + 1, last_body + 1):
        row_items = []
        for c in range(1, ncol + 1):
            cell = ws.cell(r, c)
            ind = int(cell.alignment.indent or 0) if c == 1 else 0
            row_items.append({
                "lines": _wrap_cell("" if cell.value is None else str(cell.value), col_widths[c - 1], indent=ind),
                "align": (cell.alignment.horizontal or ("left" if c == 1 else "center")).lower(),
                "bold": bool(cell.font and cell.font.bold),
                "indent": ind,
            })
        body_rows.append(row_items)

    foot_lines: list[str] = []
    for r in range(last_body + 1, nrow + 1):
        txt = " ".join(str(ws.cell(r, c).value or "") for c in range(1, ncol + 1)).strip()
        if txt:
            foot_lines.extend(_wrap_cell(txt, total_char_w * 0.96))

    # Split long tables into readable pages (~44 visual lines per page)
    max_body_lines_per_page = 38
    pages_body: list[list[list[dict]]] = []
    cur_page: list[list[dict]] = []
    cur_lines = 0
    for row_items in body_rows:
        need = max(len(it["lines"]) for it in row_items)
        if cur_page and cur_lines + need > max_body_lines_per_page:
            pages_body.append(cur_page)
            cur_page = [row_items]
            cur_lines = need
        else:
            cur_page.append(row_items)
            cur_lines += need
    if cur_page or not pages_body:
        pages_body.append(cur_page)

    fig_w_in = max(6.8, min(11.5, total_char_w * 0.088))
    x_edges = [0.0]
    for w in col_widths:
        x_edges.append(x_edges[-1] + w / total_char_w)

    written: list[Path] = []
    out_base.parent.mkdir(parents=True, exist_ok=True)
    for page_idx, p_body in enumerate(pages_body, 1):
        p_title_lines = title_lines if page_idx == 1 else [f"{title_lines[0]} (continued)"]
        hdr_line_h = sum(max(len(it["lines"]) for it in row) + 0.4 for row in headers)
        body_line_h = sum(max(len(it["lines"]) for it in row) + 0.35 for row in p_body)
        p_foot = foot_lines if page_idx == len(pages_body) else []
        total_units = len(p_title_lines) * 1.35 + 1.2 + hdr_line_h + 0.7 + body_line_h + 0.9 + len(p_foot) * 1.05 + 1.2
        fig_h_in = max(2.2, total_units * 0.21)

        fig = plt.figure(figsize=(fig_w_in, fig_h_in), dpi=dpi, facecolor="white")
        ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, total_units)
        ax.axis("off")

        y = total_units - 0.6
        for ln in p_title_lines:
            ax.text(0.005, y, ln, fontsize=9.5, fontweight="bold", fontfamily="sans-serif", va="top", ha="left", color="black")
            y -= 1.25
        y -= 0.35
        ax.plot([0, 1], [y, y], color="black", linewidth=0.9)
        y -= 0.4

        for r_idx, h_row in enumerate(headers):
            need = max(len(it["lines"]) for it in h_row)
            for c_idx, it in enumerate(h_row):
                x0, x1 = x_edges[c_idx], x_edges[c_idx + 1]
                al = it["align"]
                tx = x0 + 0.006 if al == "left" else (x1 - 0.006 if al == "right" else (x0 + x1) / 2.0)
                ha = "left" if al == "left" else ("right" if al == "right" else "center")
                ax.text(tx, y, "\n".join(it["lines"]), fontsize=8.5, fontweight="bold", fontfamily="sans-serif",
                        va="top", ha=ha, color="black", linespacing=1.22)
            y -= need * 1.05 + 0.35
        ax.plot([0, 1], [y, y], color="black", linewidth=0.75)
        y -= 0.45

        for b_row in p_body:
            need = max(len(it["lines"]) for it in b_row)
            for c_idx, it in enumerate(b_row):
                x0, x1 = x_edges[c_idx], x_edges[c_idx + 1]
                al = it["align"]
                indent_pad = 0.018 * it["indent"] if al == "left" else 0.0
                tx = x0 + 0.006 + indent_pad if al == "left" else (x1 - 0.006 if al == "right" else (x0 + x1) / 2.0)
                ha = "left" if al == "left" else ("right" if al == "right" else "center")
                ax.text(tx, y, "\n".join(it["lines"]), fontsize=8.2, fontweight=("bold" if it["bold"] else "normal"),
                        fontfamily="sans-serif", va="top", ha=ha, color="black", linespacing=1.22)
            y -= need * 1.0 + 0.35

        ax.plot([0, 1], [y, y], color="black", linewidth=0.9)
        y -= 0.45
        for ln in p_foot:
            ax.text(0.005, y, ln, fontsize=7.6, fontfamily="sans-serif", va="top", ha="left", color="black")
            y -= 1.02

        target = out_base if page_idx == 1 else out_base.with_name(f"{out_base.stem}_p{page_idx}.png")
        fig.savefig(target, dpi=dpi, facecolor="white")
        plt.close(fig)
        _crop_whitespace(target)
        written.append(target)

    return written


def render_all(project: Path, tables_filter: list[str] | None = None, engine: str = "auto", dpi: int = 220) -> dict:
    entries = _table_entries(project, tables_filter)
    if not entries:
        raise ValueError("No matching tables found in 01_protocol/artifact_plan.json or 04_tables/.")
    qc_results: list[dict] = []
    previews_dir = project / "04_tables" / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    total = len(entries)

    for idx, entry in enumerate(entries, 1):
        tid = str(entry.get("id") or entry.get("sheet") or f"Table_{idx}")
        sheet_name = str(entry.get("sheet") or tid)
        _, xlsx_path = _safe_path(project, str(entry["file"]))
        if not xlsx_path.is_file():
            raise ValueError(f"{tid}: workbook missing at {entry['file']}")
        print(f"[table render {idx}/{total}] {tid} ({entry['file']})", flush=True)

        wb = load_workbook(xlsx_path, data_only=True)
        try:
            ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active
            layout_checks = _inspect_sheet_layout(ws)
            out_base = previews_dir / f"{_slug(tid)}.png"
            written_pages: list[Path] | None = None
            used_engine = "python"
            if engine in {"auto", "excel"}:
                written_pages = _render_excel_com(xlsx_path, ws.title, out_base, dpi)
                if written_pages:
                    used_engine = "excel"
                elif engine == "excel":
                    raise ValueError("Excel COM / pdftoppm unavailable for --engine excel")
            if not written_pages:
                written_pages = _render_python(ws, out_base, dpi)
        finally:
            wb.close()

        rel_pages = [p.relative_to(project).as_posix() for p in written_pages]
        blocking = [c for c in layout_checks if not c["ok"] and c["severity"] == "fail"]
        qc_results.append({
            "id": tid,
            "sheet": ws.title,
            "xlsx": xlsx_path.relative_to(project).as_posix(),
            "xlsx_sha256": _sha256(xlsx_path),
            "engine": used_engine,
            "preview": rel_pages[0],
            "preview_sha256": _sha256(written_pages[0]),
            "pages": rel_pages,
            "ok": not blocking,
            "checks": layout_checks,
        })
        for c in layout_checks:
            tag = "PASS" if c["ok"] else ("FAIL" if c["severity"] == "fail" else "WARN")
            print(f"  [{tag}] {c['check']:<28} {c['detail']}", flush=True)

    qc_path = project / "04_tables" / "qc" / "table_qc_report.json"
    existing_by_id: dict[str, dict] = {}
    if tables_filter and qc_path.is_file():
        try:
            existing_by_id = {t["id"]: t for t in json.loads(qc_path.read_text(encoding="utf-8")).get("tables", []) if t.get("id")}
        except (OSError, json.JSONDecodeError):
            existing_by_id = {}
    for row in qc_results:
        existing_by_id[row["id"]] = row
    merged = list(existing_by_id.values()) if tables_filter else qc_results

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tables": merged,
    }
    atomic_json(qc_path, report)
    print(f"Table QC report written -> {qc_path.relative_to(project).as_posix()} ({len(qc_results)} rendered)", flush=True)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="render all planned tables")
    ap.add_argument("--table", action="append", default=[], help="table id/sheet to render (repeatable)")
    ap.add_argument("--engine", choices=["auto", "excel", "python"], default="auto")
    ap.add_argument("--dpi", type=int, default=220)
    ap.add_argument("--project", type=Path, default=None)
    args = ap.parse_args()
    if not args.all and not args.table:
        ap.error("pass --all or --table <ID>")
    project = args.project.resolve() if args.project else wfpaths.project_dir().resolve()
    try:
        report = render_all(project, tables_filter=args.table if args.table else None, engine=args.engine, dpi=args.dpi)
        fails = sum(1 for row in report["tables"] if not row.get("ok"))
        return 2 if fails else 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"table render error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
