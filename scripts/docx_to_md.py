"""Minimal DOCX -> Markdown converter (no external deps).

Reads word/document.xml from a .docx (a zip), and emits Markdown preserving
headings, lists, and tables. Intended for the FretWise reference specs.
"""

from __future__ import annotations

import re
import sys
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _text_of(node: ET.Element) -> str:
    """Concatenate all w:t runs under a paragraph/cell node."""
    parts: list[str] = []
    for t in node.iter(f"{W}t"):
        parts.append(t.text or "")
        # tabs inside runs
    # handle explicit tabs/breaks roughly
    txt = "".join(parts)
    return txt.strip()


def _style(p: ET.Element) -> str:
    ppr = p.find(f"{W}pPr")
    if ppr is None:
        return ""
    st = ppr.find(f"{W}pStyle")
    if st is None:
        return ""
    return st.get(f"{W}val", "")


def _is_list(p: ET.Element) -> bool:
    ppr = p.find(f"{W}pPr")
    return ppr is not None and ppr.find(f"{W}numPr") is not None


def _heading_level(style: str) -> int:
    m = re.match(r"(?:Heading|Titre)(\d)", style, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if style.lower() in ("title", "titre"):
        return 1
    return 0


def convert(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(f"{W}body")
    out: list[str] = []

    for child in list(body):
        tag = child.tag
        if tag == f"{W}p":
            style = _style(child)
            text = _text_of(child)
            lvl = _heading_level(style)
            if lvl:
                # Demote by one level so the manually-added title block is the
                # document's single H1 (satisfies markdownlint MD025).
                if text:
                    out.append(f"{'#' * min(lvl + 1, 6)} {text}")
                continue
            if _is_list(child):
                if text:
                    out.append(f"- {text}")
                continue
            out.append(text)  # may be empty -> blank line
        elif tag == f"{W}tbl":
            rows: list[list[str]] = []
            for tr in child.findall(f"{W}tr"):
                cells = [_text_of(tc) for tc in tr.findall(f"{W}tc")]
                rows.append(cells)
            if rows:
                ncol = max(len(r) for r in rows)
                rows = [r + [""] * (ncol - len(r)) for r in rows]
                out.append("| " + " | ".join(rows[0]) + " |")
                out.append("| " + " | ".join(["---"] * ncol) + " |")
                for r in rows[1:]:
                    out.append("| " + " | ".join(c.replace("\n", " ") for c in r) + " |")
                out.append("")

    # collapse 3+ blank lines into 1
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md


if __name__ == "__main__":
    src = sys.argv[1]
    dst = sys.argv[2]
    with open(dst, "w", encoding="utf-8") as f:
        f.write(convert(src))
    print(f"wrote {dst}")
