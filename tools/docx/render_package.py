"""
render_package.py - Assemble and render publication-grade Word documents for the submission bundle.

Handles:
1. Dynamically parsing target journal guidelines (font size, line spacing) from guidelines_extract.md.
2. Generating a matched medical reference docx (Times New Roman, pure black, no link underlines, zero outlines).
3. Counting actual unique citations referenced in the text and auto-calibrating Title Page reference count.
4. Assembling the complete manuscript:
   - title_page.md (calibrated reference count, clean metadata)
   - abstract.md (with cleaned Keywords appended at end)
   - introduction.md, methods.md, results.md, discussion.md, statements.md (with centralized Abbreviations)
   - # References heading with ::: {#refs} ::: anchor so Pandoc citeproc places bibliography BEFORE Figure Legends
   - # Figure Legends (stripped of Abbreviations, visual guide only, strictly at manuscript end)
5. Compiling manuscript.docx with pandoc citeproc against refs.bib and journal CSL.
6. Compiling the complete submission suite (manuscript.docx, title_page.docx, cover_letter.docx, supplementary_materials.docx).
7. Deep WordprocessingML purification pipeline:
   - Flattening all hyperlinks to plain text runs (eliminates blue color, underlines, and un-nests breaks)
   - Converting all manual line breaks (<w:br/> without page/column type) to genuine hard paragraphs (<w:p>)
   - Eliminating black square margin artifacts: keepNext, keepLines, and pageBreakBefore strictly cleared (0 occurrences)
   - Eliminating folding triangles: outlineLvl strictly cleared (0 occurrences) and all headings mapped and flattened
     to plain body-level SectionHeading / SubsectionHeading based on Normal (impossible to collapse)
   - Removing residual markdown horizontal rules (---, ***) and VML dividers
   - Preserving styles.xml native numbering tables to prevent 'Style 1' / '样式1' errors
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W_NS, "rel": REL_NS}


def extract_guideline_formatting(guidelines_path: Path) -> tuple[float, str]:
    """Parse guidelines_extract.md for font size and line spacing preferences."""
    body_size = 12.0
    line_spacing = "double"

    if not guidelines_path.exists():
        return body_size, line_spacing

    text = guidelines_path.read_text(encoding="utf-8", errors="ignore").lower()

    if "11 pt" in text or "11-point" in text or "11pt" in text:
        body_size = 11.0
    elif "12 pt" in text or "12-point" in text or "12pt" in text:
        body_size = 12.0

    if "1.5 line" in text or "1.5-spaced" in text or "one and a half" in text:
        line_spacing = "1.5"
    elif "double" in text or "2.0 line" in text:
        line_spacing = "double"
    elif "single" in text:
        line_spacing = "single"

    return body_size, line_spacing


def count_actual_citations(project_dir: Path) -> int:
    """Extract all unique citation keys actually referenced in manuscript prose."""
    manuscript_dir = project_dir / "07_manuscript"
    keys: set[str] = set()
    for name in ("introduction.md", "methods.md", "results.md", "discussion.md", "statements.md"):
        p = manuscript_dir / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            for grp in re.findall(r"\[([^\]]*@[^\]]*)\]", text):
                keys.update(re.findall(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)", grp))
            for single in re.findall(r"(?<!\w)@([A-Za-z][\w:.#$%&+?<>~/-]*)", text):
                keys.add(single)
    return len(keys)


def calibrate_title_page_refcount(title_page_text: str, actual_ref_count: int) -> str:
    """Ensure Title Page states the real number of cited references, not the whole library size."""
    if not title_page_text:
        return title_page_text

    pattern = r"(?i)(\b(?:number\s+of\s+references|references?)\s*:\s*)\d+"
    if re.search(pattern, title_page_text):
        return re.sub(pattern, rf"\g<1>{actual_ref_count}", title_page_text)
    return title_page_text


def sanitize_latex_math_and_dollars(text: str) -> str:
    """Sanitize stray, unclosed LaTeX math dollars ($) to prevent Pandoc from entering
    math mode and swallowing whitespace between words (e.g. ()ateachscreening...).

    1. Converts medical statistical symbols ($p$, $p < 0.05$, $n$, $N$) to standard markdown italics (*p*, *n*).
    2. Strips pseudo-math wrappers where prose words were accidentally enclosed in dollars.
    3. Safely escapes stray unclosed dollars.
    """
    if not text:
        return text

    # 1. Protect currency amounts like $100, $5.50 so they won't trigger math mode
    text = re.sub(r'(?<!\\)\$(\d+(?:,\d+)*(?:\.\d+)?)', r'\\$\1', text)

    paragraphs = text.split('\n\n')
    cleaned_paras = []

    prose_stopwords = {
        'screening', 'each', 'patient', 'patients', 'stage', 'group', 'and', 'or', 'the',
        'with', 'from', 'at', 'in', 'of', 'to', 'for', 'by', 'on', 'filtration', 'cohort',
        'table', 'figure', 'versus', 'vs', 'after', 'before', 'follow', 'visit', 'study',
        'sample', 'size', 'sizes', 'node', 'nodes', 'cascade', 'branching', 'proportion'
    }

    for para in paragraphs:
        p = para

        # Convert common medical italic stats: $p$, $p < 0.05$, $n$, $N$ to markdown italics *p*, *n*
        p = re.sub(r'(?i)(?<!\\)\$([pnN])\s*([<>=]=?)\s*([0-9.]+)(?<!\\)\$', r'*\1* \2 \3', p)
        p = re.sub(r'(?i)(?<!\\)\$([pnN])(?<!\\)\$', r'*\1*', p)
        p = re.sub(r'(?i)(?<!\\)\$([a-zA-Z])(?<!\\)\$', r'*\1*', p)

        # Find any remaining unescaped $...$ pairs
        def fix_math_match(m):
            inner = m.group(1)
            words = inner.split()
            # If inner contains more than 3 words or typical prose words, it's NOT a real formula
            if len(words) > 3 or any(w.lower().strip("(),.:;") in prose_stopwords for w in words):
                return inner  # strip the $ delimiters completely to preserve word spaces!
            return m.group(0)

        p = re.sub(r'(?<!\\)\$([^$\n]+)(?<!\\)\$', fix_math_match, p)

        # Handle unclosed or odd number of $ in paragraph
        unescaped_dollars = [m.start() for m in re.finditer(r'(?<!\\)\$', p)]
        if len(unescaped_dollars) % 2 != 0:
            # Escape all lone unescaped dollars so Pandoc will never swallow text into math mode
            p = re.sub(r'(?<!\\)\$', r'\\$', p)

        cleaned_paras.append(p)

    return '\n\n'.join(cleaned_paras)


def clean_markdown_soft_breaks(text: str) -> str:
    """Strip manual line break triggers and residual horizontal rules from markdown prose."""
    if not text:
        return text
    text = re.sub(r'(?i)<br\s*/?>', '\n', text)
    text = re.sub(r'\\+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    # Strip markdown horizontal dividing lines (---, ***, ___) to eliminate residual Word dividing lines
    text = re.sub(r'(?m)^[ \t]*([-_*])[ \t]*(?:\1[ \t]*){2,}[ \t]*$', '', text)
    return text


def clean_keywords(text: str) -> str:
    """Clean MeSH / code qualifiers from keywords and ensure canonical placement at Abstract end."""
    kw_pattern = r'(?is)(?:#+\s*)?(?:Keywords?|Key\s*words?)(?:\s*\([^)]*\))?:?\s*(.+?)(?=\n\s*#|\Z)'
    m = re.search(kw_pattern, text)
    if not m:
        return text
    raw_kws = m.group(1).strip()

    parts = re.split(r'[;,\n]', raw_kws)
    cleaned = []
    for p in parts:
        p = p.strip().rstrip('.')
        if not p:
            continue
        if '/' in p:
            p = ' '.join([sp.strip() for sp in p.split('/') if sp.strip()])
        p = p.replace('&', 'and')
        words = p.split()
        if words:
            p = words[0].capitalize() + (' ' + ' '.join(words[1:]) if len(words) > 1 else '')
        if p and p not in cleaned:
            cleaned.append(p)

    final_kws = ', '.join(cleaned[:5])
    kw_line = f"**Keywords:** {final_kws}."

    text_without_kw = re.sub(kw_pattern, '', text).strip()
    return text_without_kw + '\n\n' + kw_line


def clean_legend_block(legend_text: str) -> str:
    """Clean figure legends:
    1. Strip duplicate global # Figure Legends heading so it never appears twice.
    2. Format individual headings cleanly: '**Figure 1. Title.** Body'.
    3. Strip duplicate Abbreviations blocks (centralized in Statements).
    4. Sanitize math dollars ($) to prevent swallowing word spaces.
    """
    if not legend_text.strip():
        return ""

    legend_text = sanitize_latex_math_and_dollars(legend_text)

    # 1. Strip any leading global "# Figure Legends" or "## Figure Legends" heading
    text = re.sub(r'(?im)^#+\s*Figure\s+Legends?\s*$', '', legend_text).strip()

    # 2. Split into individual figure blocks
    blocks = re.split(r"(?m)(?=^(?:#+\s*)?Figure\s+[S\d]+)", text)
    cleaned_blocks = []

    for block in blocks:
        b = block.strip()
        if not b:
            continue

        # Discard any block not starting with Figure
        if not re.match(r"^(?:#+\s*)?Figure\s+[S\d]+", b, re.IGNORECASE):
            continue

        # Strip out Abbreviations block from individual legend (centralized in Declarations/Statements)
        b = re.sub(r"(?is)\bAbbreviations?:?\s*.*$", "", b).strip()

        # Format title e.g. "## Figure 1.\n**Title.** Body" -> "**Figure 1. Title.** Body"
        m = re.match(r"^(?:#+\s*)?(Figure\s+[S\d]+)[\.\:]?\s*(.*)", b, re.IGNORECASE | re.DOTALL)
        if m:
            prefix = m.group(1).strip()
            rest = m.group(2).strip()

            # If rest starts with bold title e.g. "**Cohort selection.**\nFlow diagram..."
            bold_m = re.match(r"^\*\*(.+?)\*\*[\.\:]?\s*(.*)", rest, re.DOTALL)
            if bold_m:
                sub_title = bold_m.group(1).rstrip(".")
                body_text = bold_m.group(2).strip()
                b = f"**{prefix}. {sub_title}.** {body_text}" if body_text else f"**{prefix}. {sub_title}.**"
            else:
                b = f"**{prefix}.** {rest}"

        cleaned_blocks.append(b)

    return "\n\n".join(cleaned_blocks)


def purify_docx_xml(root: ET.Element, is_document_stream: bool = True) -> bool:
    """Deeply purify docx OpenXML:

    1. Flatten all hyperlinks to plain text runs (eliminates blue color, underlines, and un-nests breaks)
    2. Strip all outlineLvl, keepNext, keepLines, and pageBreakBefore attributes across all pPr
    3. Map all Heading styles to flat body-level SectionHeading / SubsectionHeading
    4. Split manual line breaks into hard paragraphs
    5. Remove residual horizontal dividing lines (--- or ***)
    """
    ET.register_namespace('w', W_NS)
    modified = False

    # 1. Flatten hyperlinks in all paragraphs
    for p in root.findall(f".//{{{W_NS}}}p"):
        hyperlinks = [c for c in list(p) if c.tag == f"{{{W_NS}}}hyperlink"]
        if hyperlinks:
            modified = True
            for hl in hyperlinks:
                idx = list(p).index(hl)
                p.remove(hl)
                for child in list(hl):
                    # Ensure child runs do not carry hyperlink color or underline
                    rPr = child.find(f"{{{W_NS}}}rPr")
                    if rPr is not None:
                        u = rPr.find(f"{{{W_NS}}}u")
                        if u is not None:
                            rPr.remove(u)
                        color = rPr.find(f"{{{W_NS}}}color")
                        if color is not None:
                            color.set(f"{{{W_NS}}}val", "000000")
                    p.insert(idx, child)
                    idx += 1

    # 2. Strip all pagination and outline control attributes (keepNext, keepLines, pageBreakBefore, outlineLvl)
    # This completely eliminates black square margin indicators and folding triangles.
    for parent in list(root.iter()):
        for tag in ("keepNext", "keepLines", "pageBreakBefore", "outlineLvl"):
            for node in [c for c in list(parent) if c.tag == f"{{{W_NS}}}{tag}"]:
                parent.remove(node)
                modified = True

    # 3. If document stream, map all native Heading styles to flat body-level SectionHeading / SubsectionHeading
    if is_document_stream:
        for p in root.findall(f".//{{{W_NS}}}p"):
            pPr = p.find(f"{{{W_NS}}}pPr")
            if pPr is not None:
                pstyle = pPr.find(f"{{{W_NS}}}pStyle")
                if pstyle is not None:
                    val = pstyle.get(f"{{{W_NS}}}val", "")
                    if re.match(r"(?i)^heading\s*1$", val) or val in ("Heading1", "Title"):
                        pstyle.set(f"{{{W_NS}}}val", "SectionHeading")
                        for r in p.findall(f".//{{{W_NS}}}r"):
                            rPr = r.find(f"{{{W_NS}}}rPr")
                            if rPr is None:
                                rPr = ET.SubElement(r, f"{{{W_NS}}}rPr")
                            if rPr.find(f"{{{W_NS}}}b") is None:
                                ET.SubElement(rPr, f"{{{W_NS}}}b")
                            color = rPr.find(f"{{{W_NS}}}color")
                            if color is None:
                                color = ET.SubElement(rPr, f"{{{W_NS}}}color")
                            color.set(f"{{{W_NS}}}val", "000000")
                        modified = True
                    elif re.match(r"(?i)^heading\s*[2-9]$", val) or re.match(r"^Heading[2-9]$", val) or val == "Subtitle":
                        pstyle.set(f"{{{W_NS}}}val", "SubsectionHeading")
                        for r in p.findall(f".//{{{W_NS}}}r"):
                            rPr = r.find(f"{{{W_NS}}}rPr")
                            if rPr is None:
                                rPr = ET.SubElement(r, f"{{{W_NS}}}rPr")
                            if rPr.find(f"{{{W_NS}}}b") is None:
                                ET.SubElement(rPr, f"{{{W_NS}}}b")
                            color = rPr.find(f"{{{W_NS}}}color")
                            if color is None:
                                color = ET.SubElement(rPr, f"{{{W_NS}}}color")
                            color.set(f"{{{W_NS}}}val", "000000")
                        modified = True

    # 4. Split manual line breaks (<w:br/> not page/column) into genuine hard paragraphs (<w:p>)
    for parent in root.iter():
        p_list = [c for c in list(parent) if c.tag == f"{{{W_NS}}}p"]
        if not p_list:
            continue

        for p in p_list:
            soft_brs = [
                br for br in p.findall(f".//{{{W_NS}}}br")
                if br.attrib.get(f"{{{W_NS}}}type") not in ("page", "column")
            ]
            if not soft_brs:
                continue

            pPr = p.find(f"{{{W_NS}}}pPr")
            pPr_copy = ET.fromstring(ET.tostring(pPr)) if pPr is not None else None

            new_paragraphs = []
            current_p = ET.Element(f"{{{W_NS}}}p")
            if pPr_copy is not None:
                current_p.append(ET.fromstring(ET.tostring(pPr_copy)))

            for child in list(p):
                if child == pPr:
                    continue
                if child.tag == f"{{{W_NS}}}r":
                    rPr = child.find(f"{{{W_NS}}}rPr")
                    current_r = ET.Element(f"{{{W_NS}}}r")
                    if rPr is not None:
                        current_r.append(ET.fromstring(ET.tostring(rPr)))

                    for r_elem in list(child):
                        if r_elem == rPr:
                            continue
                        if r_elem.tag == f"{{{W_NS}}}br" and r_elem.attrib.get(f"{{{W_NS}}}type") not in ("page", "column"):
                            # Close current run & paragraph
                            if len(current_r) > (1 if rPr is not None else 0):
                                current_p.append(current_r)
                            if len(current_p) > (1 if pPr_copy is not None else 0):
                                new_paragraphs.append(current_p)

                            # Start fresh hard paragraph
                            current_p = ET.Element(f"{{{W_NS}}}p")
                            if pPr_copy is not None:
                                current_p.append(ET.fromstring(ET.tostring(pPr_copy)))
                            current_r = ET.Element(f"{{{W_NS}}}r")
                            if rPr is not None:
                                current_r.append(ET.fromstring(ET.tostring(rPr)))
                        else:
                            current_r.append(r_elem)

                    if len(current_r) > (1 if rPr is not None else 0):
                        current_p.append(current_r)
                else:
                    current_p.append(child)

            if len(current_p) > (1 if pPr_copy is not None else 0):
                new_paragraphs.append(current_p)

            if new_paragraphs:
                idx = list(parent).index(p)
                parent.remove(p)
                for offset, np in enumerate(new_paragraphs):
                    parent.insert(idx + offset, np)
                modified = True

    # 5. Remove residual horizontal dividing lines (e.g. from markdown --- or ***)
    for parent in list(root.iter()):
        p_list = [c for c in list(parent) if c.tag == f"{{{W_NS}}}p"]
        for p in p_list:
            p_str = ET.tostring(p, encoding="utf-8").decode("utf-8")
            # If paragraph contains VML hr rect or border divider with no genuine text
            if 'o:hr="t"' in p_str or ('w:val="single"' in p_str and not p.findall(f".//{{{W_NS}}}t")):
                parent.remove(p)
                modified = True

    return modified


def purify_styles_xml(root: ET.Element) -> bool:
    """Purify styles.xml:
    1. Strip all keepNext, keepLines, pageBreakBefore, and outlineLvl across all styles.
    2. Ensure SectionHeading and SubsectionHeading are defined (based on Normal, zero outline).
    3. Strictly preserve numPr for list paragraphs to prevent Style 1 / 样式1 corruption.
    """
    ET.register_namespace('w', W_NS)
    modified = False

    # 1. Strip pagination and outline control attributes across all styles & docDefaults
    for parent in list(root.iter()):
        for tag in ("keepNext", "keepLines", "pageBreakBefore", "outlineLvl"):
            for node in [c for c in list(parent) if c.tag == f"{{{W_NS}}}{tag}"]:
                parent.remove(node)
                modified = True

    # 2. Ensure SectionHeading and SubsectionHeading exist
    existing_ids = {s.attrib.get(f"{{{W_NS}}}styleId", "") for s in root.findall(f".//{{{W_NS}}}style")}
    if "SectionHeading" not in existing_ids:
        sh = ET.SubElement(root, f"{{{W_NS}}}style", {
            f"{{{W_NS}}}type": "paragraph",
            f"{{{W_NS}}}styleId": "SectionHeading",
        })
        ET.SubElement(sh, f"{{{W_NS}}}name", {f"{{{W_NS}}}val": "SectionHeading"})
        ET.SubElement(sh, f"{{{W_NS}}}basedOn", {f"{{{W_NS}}}val": "Normal"})
        ET.SubElement(sh, f"{{{W_NS}}}next", {f"{{{W_NS}}}val": "Normal"})
        ET.SubElement(sh, f"{{{W_NS}}}uiPriority", {f"{{{W_NS}}}val": "1"})
        ET.SubElement(sh, f"{{{W_NS}}}qFormat")
        ppr_el = ET.SubElement(sh, f"{{{W_NS}}}pPr")
        ET.SubElement(ppr_el, f"{{{W_NS}}}spacing", {
            f"{{{W_NS}}}before": "240",
            f"{{{W_NS}}}after": "80",
            f"{{{W_NS}}}line": "480",
            f"{{{W_NS}}}lineRule": "auto",
        })
        rpr_el = ET.SubElement(sh, f"{{{W_NS}}}rPr")
        fonts_el = ET.SubElement(rpr_el, f"{{{W_NS}}}rFonts", {
            f"{{{W_NS}}}ascii": "Times New Roman",
            f"{{{W_NS}}}hAnsi": "Times New Roman",
            f"{{{W_NS}}}eastAsia": "Times New Roman",
            f"{{{W_NS}}}cs": "Times New Roman",
        })
        ET.SubElement(rpr_el, f"{{{W_NS}}}b")
        ET.SubElement(rpr_el, f"{{{W_NS}}}bCs")
        ET.SubElement(rpr_el, f"{{{W_NS}}}color", {f"{{{W_NS}}}val": "000000"})
        ET.SubElement(rpr_el, f"{{{W_NS}}}sz", {f"{{{W_NS}}}val": "28"})
        ET.SubElement(rpr_el, f"{{{W_NS}}}szCs", {f"{{{W_NS}}}val": "28"})
        modified = True

    if "SubsectionHeading" not in existing_ids:
        ssh = ET.SubElement(root, f"{{{W_NS}}}style", {
            f"{{{W_NS}}}type": "paragraph",
            f"{{{W_NS}}}styleId": "SubsectionHeading",
        })
        ET.SubElement(ssh, f"{{{W_NS}}}name", {f"{{{W_NS}}}val": "SubsectionHeading"})
        ET.SubElement(ssh, f"{{{W_NS}}}basedOn", {f"{{{W_NS}}}val": "Normal"})
        ET.SubElement(ssh, f"{{{W_NS}}}next", {f"{{{W_NS}}}val": "Normal"})
        ET.SubElement(ssh, f"{{{W_NS}}}uiPriority", {f"{{{W_NS}}}val": "2"})
        ET.SubElement(ssh, f"{{{W_NS}}}qFormat")
        ppr_el = ET.SubElement(ssh, f"{{{W_NS}}}pPr")
        ET.SubElement(ppr_el, f"{{{W_NS}}}spacing", {
            f"{{{W_NS}}}before": "180",
            f"{{{W_NS}}}after": "60",
            f"{{{W_NS}}}line": "480",
            f"{{{W_NS}}}lineRule": "auto",
        })
        rpr_el = ET.SubElement(ssh, f"{{{W_NS}}}rPr")
        fonts_el = ET.SubElement(rpr_el, f"{{{W_NS}}}rFonts", {
            f"{{{W_NS}}}ascii": "Times New Roman",
            f"{{{W_NS}}}hAnsi": "Times New Roman",
            f"{{{W_NS}}}eastAsia": "Times New Roman",
            f"{{{W_NS}}}cs": "Times New Roman",
        })
        ET.SubElement(rpr_el, f"{{{W_NS}}}b")
        ET.SubElement(rpr_el, f"{{{W_NS}}}bCs")
        ET.SubElement(rpr_el, f"{{{W_NS}}}color", {f"{{{W_NS}}}val": "000000"})
        ET.SubElement(rpr_el, f"{{{W_NS}}}sz", {f"{{{W_NS}}}val": "24"})
        ET.SubElement(rpr_el, f"{{{W_NS}}}szCs", {f"{{{W_NS}}}val": "24"})
        modified = True

    return modified


def post_process_docx(docx_path: Path) -> None:
    """Purify generated docx file in-place:
    - Flatten hyperlinks to plain text
    - Eliminate soft breaks (down arrows) and convert to hard paragraphs
    - Remove all outlineLvl attributes (0 occurrences)
    - Remove all keepNext, keepLines, pageBreakBefore attributes (0 occurrences, no black squares)
    - Map all Heading styles to flat body-level SectionHeading / SubsectionHeading
    - Ensure styles.xml retains perfect integrity (no 'Style 1' error)
    """
    if not docx_path.exists():
        return

    temp_buffer = io.BytesIO()

    with zipfile.ZipFile(docx_path, 'r') as zin:
        with zipfile.ZipFile(temp_buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                content = zin.read(item.filename)
                if item.filename == "word/styles.xml":
                    try:
                        root = ET.fromstring(content)
                        if purify_styles_xml(root):
                            content = ET.tostring(root, encoding="utf-8")
                    except Exception:
                        pass
                elif item.filename in ("word/document.xml",) or bool(
                    re.match(r"^word/(header|footer|footnotes|endnotes)\d*\.xml$", item.filename)
                ):
                    try:
                        root = ET.fromstring(content)
                        if purify_docx_xml(root, is_document_stream=(item.filename == "word/document.xml")):
                            content = ET.tostring(root, encoding="utf-8")
                    except Exception:
                        content = re.sub(rb'<w:br(?:\s*/>|\s+w:type="textWrapping"\s*/>)', b'', content)
                elif item.filename.endswith(".xml"):
                    # For any other XML in package, strip pagination and outline control attributes
                    try:
                        root = ET.fromstring(content)
                        modified = False
                        for parent in list(root.iter()):
                            for tag in ("keepNext", "keepLines", "pageBreakBefore", "outlineLvl"):
                                for node in [c for c in list(parent) if c.tag == f"{{{W_NS}}}{tag}"]:
                                    parent.remove(node)
                                    modified = True
                        if modified:
                            content = ET.tostring(root, encoding="utf-8")
                    except Exception:
                        pass

                zout.writestr(item, content)

    docx_path.write_bytes(temp_buffer.getvalue())

    # Self-validation assertion: verify 0 occurrences of black-square and folding attributes
    with zipfile.ZipFile(docx_path, 'r') as z:
        for n in z.namelist():
            if n.endswith(".xml"):
                txt = z.read(n).decode("utf-8", errors="ignore")
                for attr in ("keepNext", "keepLines", "pageBreakBefore", "outlineLvl"):
                    cnt = txt.count(attr)
                    if cnt > 0:
                        raise ValueError(f"DOCX post-processing leak in {docx_path.name}: {n} retains {cnt} occurrences of '{attr}'")


def assemble_manuscript_md(project_dir: Path) -> Path:
    """Combine sections into a unified markdown file ready for pandoc.
    Prioritizes journal-adapted text in 08_submission/adapted_manuscript/
    over frozen canonical base files in 07_manuscript/.
    """
    manuscript_dir = project_dir / "07_manuscript"
    adapted_dir = project_dir / "08_submission" / "adapted_manuscript"
    figures_dir = project_dir / "05_figures"

    def read_part(name: str) -> str:
        # Priority 1: Check journal-specific adaptation sandbox
        if adapted_dir.exists():
            for cand in (adapted_dir / f"adapted_{name}", adapted_dir / name):
                if cand.exists():
                    txt = cand.read_text(encoding="utf-8", errors="ignore").strip()
                    txt = sanitize_latex_math_and_dollars(txt)
                    return clean_markdown_soft_breaks(txt)

        # Priority 2: Fallback to frozen canonical 07_manuscript
        p = manuscript_dir / name
        if not p.exists():
            return ""
        txt = p.read_text(encoding="utf-8", errors="ignore").strip()
        txt = sanitize_latex_math_and_dollars(txt)
        return clean_markdown_soft_breaks(txt)

    # Count real citations
    real_refs = count_actual_citations(project_dir)

    title_page = calibrate_title_page_refcount(read_part("title_page.md"), real_refs)
    abstract = clean_keywords(read_part("abstract.md"))
    intro = read_part("introduction.md")
    methods = read_part("methods.md")
    results = read_part("results.md")
    discussion = read_part("discussion.md")
    statements = read_part("statements.md")

    # Figure legends at the end of manuscript
    legends_file = figures_dir / "legends.md"
    legends = ""
    if legends_file.exists():
        raw_legends = legends_file.read_text(encoding="utf-8", errors="ignore").strip()
        cleaned_legends = clean_legend_block(clean_markdown_soft_breaks(sanitize_latex_math_and_dollars(raw_legends)))
        if cleaned_legends:
            legends = "# Figure Legends\n\n" + cleaned_legends

    # Combine with Pandoc ::: {#refs} anchor
    # This guarantees that Pandoc citeproc places the bibliography inside # References,
    # and keeps # Figure Legends strictly as the final section at the very end!
    parts = [
        title_page,
        abstract,
        intro,
        methods,
        results,
        discussion,
        statements,
        "# References\n\n::: {#refs}\n:::",
    ]

    combined = "\n\n".join([p for p in parts if p])

    if legends:
        combined += "\n\n" + legends + "\n"

    # Final pass of soft-break and math cleaning
    combined = sanitize_latex_math_and_dollars(combined)
    combined = clean_markdown_soft_breaks(combined)

    # If adapted_dir exists or we are in submission stage, output to adapted_manuscript
    if adapted_dir.exists():
        out_path = adapted_dir / "manuscript_assembled.md"
    else:
        out_path = manuscript_dir / "manuscript_assembled.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(combined, encoding="utf-8")
    return out_path


def render_all(project_dir: Path, csl_path: Path | None = None) -> int:
    guidelines_path = project_dir / "08_submission" / "guidelines_extract.md"
    body_size, line_spacing = extract_guideline_formatting(guidelines_path)

    # 1. Build matched reference docx
    ref_builder = ROOT / "tools" / "docx" / "build_template.py"
    base_docx = ROOT / "tools" / "templates" / "base_ref.docx"
    cache_dir = project_dir / "08_submission" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    med_ref_docx = cache_dir / "med_reference.docx"

    cmd_template = [
        sys.executable, str(ref_builder),
        "--base", str(base_docx),
        "--out", str(med_ref_docx),
        "--font", "Times New Roman",
        "--size", str(body_size),
        "--spacing", line_spacing,
    ]
    subprocess.run(cmd_template, check=True)

    # 2. Assemble manuscript markdown
    assembled_md = assemble_manuscript_md(project_dir)

    # 3. Render manuscript.docx
    bundle_dir = project_dir / "08_submission" / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manuscript_docx = bundle_dir / "manuscript.docx"
    bib_file = project_dir / "06_refs" / "refs.bib"

    pandoc_cmd = [
        "pandoc",
        str(assembled_md),
        f"--reference-doc={med_ref_docx}",
        "-o", str(manuscript_docx),
    ]
    if bib_file.exists():
        pandoc_cmd.extend(["--citeproc", f"--bibliography={bib_file}"])
    if csl_path and csl_path.exists():
        pandoc_cmd.append(f"--csl={csl_path}")

    print(f"Rendering manuscript.docx via Pandoc (Font=Times New Roman, Size={body_size}pt, Spacing={line_spacing})...")
    subprocess.run(pandoc_cmd, check=True)

    # Post-process docx
    post_process_docx(manuscript_docx)
    print(f"Rendered & purified (no soft arrows, no outlines, plain hyperlinks): {manuscript_docx}")

    # 4. Render title_page.docx (standalone for journals requiring detached front matter)
    title_page_md = project_dir / "07_manuscript" / "title_page.md"
    if title_page_md.exists():
        tp_raw = title_page_md.read_text(encoding="utf-8", errors="ignore")
        real_refs = count_actual_citations(project_dir)
        tp_text = calibrate_title_page_refcount(tp_raw, real_refs)
        tp_text = clean_markdown_soft_breaks(sanitize_latex_math_and_dollars(tp_text))
        temp_tp_md = cache_dir / "clean_title_page.md"
        temp_tp_md.write_text(tp_text, encoding="utf-8")

        title_page_docx = bundle_dir / "title_page.docx"
        cmd_tp = [
            "pandoc", str(temp_tp_md),
            f"--reference-doc={med_ref_docx}",
            "-o", str(title_page_docx),
        ]
        subprocess.run(cmd_tp, check=True)
        post_process_docx(title_page_docx)
        print(f"Rendered & purified: {title_page_docx}")

    # 5. Render cover_letter.docx
    cover_letter_md = bundle_dir / "cover_letter.md"
    if not cover_letter_md.exists():
        cover_letter_md = project_dir / "08_submission" / "cover_letter.md"
    if cover_letter_md.exists():
        cl_raw = cover_letter_md.read_text(encoding="utf-8", errors="ignore")
        cl_text = clean_markdown_soft_breaks(sanitize_latex_math_and_dollars(cl_raw))
        temp_cl_md = cache_dir / "clean_cover_letter.md"
        temp_cl_md.write_text(cl_text, encoding="utf-8")

        cover_letter_docx = bundle_dir / "cover_letter.docx"
        cmd_cl = [
            "pandoc", str(temp_cl_md),
            f"--reference-doc={med_ref_docx}",
            "-o", str(cover_letter_docx),
        ]
        subprocess.run(cmd_cl, check=True)
        post_process_docx(cover_letter_docx)
        print(f"Rendered & purified: {cover_letter_docx}")

    # 6. Render supplementary_materials.docx
    supp_methods_md = project_dir / "07_manuscript" / "supplementary_methods.md"
    if supp_methods_md.exists():
        supp_raw = supp_methods_md.read_text(encoding="utf-8", errors="ignore")
        supp_text = clean_markdown_soft_breaks(sanitize_latex_math_and_dollars(supp_raw))
        temp_supp_md = cache_dir / "clean_supp.md"
        temp_supp_md.write_text(supp_text, encoding="utf-8")

        supp_docx = bundle_dir / "supplementary_materials.docx"
        cmd_supp = [
            "pandoc", str(temp_supp_md),
            f"--reference-doc={med_ref_docx}",
            "-o", str(supp_docx),
        ]
        subprocess.run(cmd_supp, check=True)
        post_process_docx(supp_docx)
        print(f"Rendered & purified: {supp_docx}")

    print("\nAll submission bundle Word documents rendered and purified successfully.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Render publication-grade Word submission bundle.")
    parser.add_argument("--project", type=Path, default=Path("project"))
    parser.add_argument("--csl", type=Path, default=None)
    args = parser.parse_args()

    return render_all(args.project, args.csl)


if __name__ == "__main__":
    sys.exit(main())
