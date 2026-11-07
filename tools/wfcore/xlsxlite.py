"""Minimal read-only .xlsx reader built on zipfile + ElementTree.

Exists so the gate engine stays dependency-free: gates must run even when the
science virtualenv (openpyxl/pandas) is broken or absent. Reads cell values and
enough style information to verify three-line (booktabs) table rules.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
CELL_RE = re.compile(r"^([A-Z]+)(\d+)$")


def _col_to_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def parse_cell_ref(ref: str) -> tuple[int, int] | None:
    m = CELL_RE.match(str(ref).strip().upper())
    if not m:
        return None
    return int(m.group(2)), _col_to_index(m.group(1))


@dataclass
class Cell:
    ref: str
    row: int
    col: int
    value: str | None
    style: int | None


@dataclass
class BorderSpec:
    top: bool = False
    bottom: bool = False
    left: bool = False
    right: bool = False


@dataclass
class Sheet:
    name: str
    cells: list[Cell] = field(default_factory=list)
    merged_ranges: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def max_row(self) -> int:
        return max((c.row for c in self.cells), default=0)

    @property
    def max_col(self) -> int:
        return max((c.col for c in self.cells), default=0)

    def cell_at(self, row: int, col: int) -> Cell | None:
        for c in self.cells:
            if c.row == row and c.col == col:
                return c
        return None

    def cell_text(self, row: int, col: int) -> str:
        c = self.cell_at(row, col)
        if c is not None and c.value not in (None, ""):
            return str(c.value)
        for r1, c1, r2, c2 in self.merged_ranges:
            if r1 <= row <= r2 and c1 <= col <= c2:
                anchor = self.cell_at(r1, c1)
                if anchor is not None and anchor.value not in (None, ""):
                    return str(anchor.value)
        return ""

    def row_cells(self, row: int) -> list[Cell]:
        return sorted((c for c in self.cells if c.row == row), key=lambda c: c.col)

    def row_text(self, row: int) -> list[str]:
        return [c.value or "" for c in self.row_cells(row)]

    def values(self) -> list[str]:
        return [c.value for c in self.cells if c.value not in (None, "")]


class Workbook:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.sheets: list[Sheet] = []
        self._borders: list[BorderSpec] = []
        self._xf_border: list[int] = []
        self._fonts_bold: list[bool] = []
        self._xf_font: list[int] = []
        self._load()

    # ---- parsing -------------------------------------------------------
    def _load(self) -> None:
        with zipfile.ZipFile(self.path) as zf:
            shared = self._shared_strings(zf)
            self._load_styles(zf)
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            rel_map = {
                el.get("Id"): el.get("Target")
                for el in rels
                if el.get("Id")
            }
            for sh in wb.findall("m:sheets/m:sheet", NS):
                name = sh.get("name", "?")
                rid = sh.get(f"{{{NS['r']}}}id")
                target = rel_map.get(rid, "")
                if not target:
                    continue
                member = "xl/" + target.lstrip("/").removeprefix("xl/")
                if member not in zf.namelist():
                    continue
                self.sheets.append(self._parse_sheet(name, zf.read(member), shared))

    @staticmethod
    def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in zf.namelist():
            return []
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        out = []
        for si in root.findall("m:si", NS):
            out.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        return out

    def _load_styles(self, zf: zipfile.ZipFile) -> None:
        if "xl/styles.xml" not in zf.namelist():
            return
        root = ET.fromstring(zf.read("xl/styles.xml"))
        for f in root.findall("m:fonts/m:font", NS):
            b_el = f.find("m:b", NS)
            self._fonts_bold.append(b_el is not None and b_el.get("val", "1") not in ("0", "false"))
        for b in root.findall("m:borders/m:border", NS):
            spec = BorderSpec()
            for side in ("top", "bottom", "left", "right"):
                el = b.find(f"m:{side}", NS)
                setattr(spec, side, el is not None and el.get("style") not in (None, "none"))
            self._borders.append(spec)
        for xf in root.findall("m:cellXfs/m:xf", NS):
            self._xf_border.append(int(xf.get("borderId", "0")))
            self._xf_font.append(int(xf.get("fontId", "0")))

    def _parse_sheet(self, name: str, blob: bytes, shared: list[str]) -> Sheet:
        sheet = Sheet(name=name)
        root = ET.fromstring(blob)
        for c in root.iter(f"{{{NS['m']}}}c"):
            ref = c.get("r", "")
            m = CELL_RE.match(ref)
            if not m:
                continue
            ctype = c.get("t")
            v = c.find("m:v", NS)
            if ctype == "s" and v is not None and v.text is not None:
                idx = int(v.text)
                val = shared[idx] if 0 <= idx < len(shared) else None
            elif ctype == "inlineStr":
                is_el = c.find("m:is", NS)
                val = "".join(t.text or "" for t in is_el.iter(f"{{{NS['m']}}}t")) if is_el is not None else None
            else:
                val = v.text if v is not None else None
            style = int(c.get("s")) if c.get("s") is not None else None
            sheet.cells.append(
                Cell(ref=ref, row=int(m.group(2)), col=_col_to_index(m.group(1)), value=val, style=style)
            )
        for mc in root.findall("m:mergeCells/m:mergeCell", NS):
            rng = mc.get("ref", "")
            if ":" not in rng:
                continue
            left, right = rng.split(":", 1)
            p1, p2 = parse_cell_ref(left), parse_cell_ref(right)
            if p1 and p2:
                sheet.merged_ranges.append((min(p1[0], p2[0]), min(p1[1], p2[1]),
                                            max(p1[0], p2[0]), max(p1[1], p2[1])))
        return sheet

    # ---- style access --------------------------------------------------
    def border_of(self, cell: Cell) -> BorderSpec:
        if cell.style is None or cell.style >= len(self._xf_border):
            return BorderSpec()
        bid = self._xf_border[cell.style]
        if bid >= len(self._borders):
            return BorderSpec()
        return self._borders[bid]

    def is_bold(self, cell: Cell | None) -> bool:
        if cell is None or cell.style is None or cell.style >= len(self._xf_font):
            return False
        fid = self._xf_font[cell.style]
        return 0 <= fid < len(self._fonts_bold) and self._fonts_bold[fid]

    def sheet(self, name: str) -> Sheet | None:
        for s in self.sheets:
            if s.name == name:
                return s
        return None

    def header_rows(self, sh: Sheet) -> tuple[list[int], int]:
        """Return (header_row_numbers, last_body_row) for three-line or plain sheets."""
        top_rows = [c.row for c in sh.cells if self.border_of(c).top]
        bottom_rows = [c.row for c in sh.cells if self.border_of(c).bottom]
        if top_rows and bottom_rows:
            first_header = min(top_rows)
            last_body = max(bottom_rows)
            smaller_bottoms = [r for r in bottom_rows if first_header <= r < last_body]
            last_header = max(smaller_bottoms) if smaller_bottoms else first_header
            return list(range(first_header, last_header + 1)), last_body
        row1 = [t for t in sh.row_text(1) if t.strip()]
        row2 = [t for t in sh.row_text(2) if t.strip()]
        if len(row1) == 1 and len(row2) >= 2:
            return [2], sh.max_row
        return ([1] if sh.max_row >= 1 else []), sh.max_row

    def column_headers(self, sheet_name: str, cell_ref: str) -> list[str]:
        """Header stack from top to bottom for a body cell, resolving merged headers."""
        sh = self.sheet(sheet_name)
        pos = parse_cell_ref(cell_ref)
        if sh is None or pos is None:
            return []
        row, col = pos
        hdr_rows, last_body = self.header_rows(sh)
        if not hdr_rows or row <= max(hdr_rows) or row > last_body:
            return []
        out: list[str] = []
        for hr in hdr_rows:
            txt = sh.cell_text(hr, col).strip()
            if txt and txt not in out:
                out.append(txt)
        return out

    def row_group_header(self, sheet_name: str, cell_ref: str) -> str:
        """Nearest preceding section/subgroup banner row inside the table body, if any."""
        sh = self.sheet(sheet_name)
        pos = parse_cell_ref(cell_ref)
        if sh is None or pos is None:
            return ""
        row, _ = pos
        hdr_rows, last_body = self.header_rows(sh)
        start = (max(hdr_rows) + 1) if hdr_rows else 2
        if row <= start or row > last_body:
            return ""
        for r in range(row - 1, start - 1, -1):
            c1 = sh.cell_at(r, 1)
            label = (c1.value or "").strip() if c1 else ""
            if not label:
                continue
            other_nonempty = [
                c for c in sh.row_cells(r)
                if c.col > 1 and (c.value or "").strip()
            ]
            if not other_nonempty and self.is_bold(c1):
                return label
        return ""


def numeric_cell_values(path: Path) -> list[tuple[str, str, str]]:
    """-> [(sheet, ref, raw_value)] for cells whose text contains a number."""
    wb = Workbook(path)
    out = []
    for sh in wb.sheets:
        for c in sh.cells:
            if c.value and re.search(r"\d", c.value):
                out.append((sh.name, c.ref, c.value))
    return out
