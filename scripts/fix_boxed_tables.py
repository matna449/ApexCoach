#!/usr/bin/env python3
"""Convert pandoc's single-cell HTML tables back into readable Markdown.

The Apex Coach .docx source uses single-cell bordered boxes (in Word) to set
off diagrams, pseudocode, JSON payloads, and short callout rules. Pandoc has
no pipe-table representation for multi-paragraph cells, so it emits raw
<table><td><p>line</p><p>line</p>...</table> blocks. Two problems follow:

1. Structurally, that HTML needs converting to a fenced code block (for
   diagrams/code/pseudocode) or a blockquote (for short bold-label callouts).
2. Pandoc's docx->HTML reader collapses runs of internal whitespace to a
   single space, which destroys column alignment in diagrams and Python
   indentation in code samples.

For (2), this script cross-references a whitespace-preserving `textutil
-convert txt` dump of the same .docx (passed as a sidecar file) and, for each
boxed block, swaps in the exact-whitespace version from that dump when it can
find a confident anchor match. It falls back to the (whitespace-collapsed)
pandoc text, with a warning, when no match is found.

Run via scripts/convert_docs.sh, not directly.
"""
import html
import re
import sys
from typing import List, Optional

BLOCK_RE = re.compile(
    r'<table>\n<colgroup>\n<col style="width: 100%" />\n</colgroup>\n'
    r"<tbody>\n<tr>\n<td>(.*?)</td>\n</tr>\n</tbody>\n</table>",
    re.S,
)


def norm(line: str) -> str:
    line = line.replace("**", "").strip()
    return re.sub(r"\s+", " ", line).lower()


def cell_lines(cell: str) -> List[str]:
    paras = re.findall(r"<p>(.*?)</p>", cell, re.S)
    lines = []
    for p in paras:
        p = p.replace("<strong>", "**").replace("</strong>", "**")
        p = p.replace("<em>", "*").replace("</em>", "*")
        lines.append(html.unescape(p))
    return lines


def find_exact_block(txt_lines: List[str], cell_lines: List[str]) -> Optional[List[str]]:
    """Locate the exact-whitespace source for a pandoc cell.

    Pandoc collapses a cell's internal blank paragraphs, so the cell's line
    sequence may not be contiguous in the textutil dump. Walk forward from
    each anchor candidate, matching the full normalized content sequence
    while freely skipping blank lines in the txt source (they're gaps pandoc
    swallowed) — this both recovers those gaps and disambiguates anchors
    that recur (e.g. multiple blocks starting with "{").
    """
    wanted = [norm(l) for l in cell_lines if l.strip() != ""]
    if not wanted:
        return None

    matches = []
    for start, line in enumerate(txt_lines):
        if norm(line) != wanted[0]:
            continue
        k = 1
        i = start + 1
        end = start
        while i < len(txt_lines) and k < len(wanted):
            if txt_lines[i].strip() == "":
                i += 1
                continue
            if norm(txt_lines[i]) == wanted[k]:
                k += 1
                end = i
                i += 1
            else:
                break
        if k == len(wanted):
            matches.append((start, end))

    if len(matches) != 1:
        return None

    start, end = matches[0]
    return txt_lines[start : end + 1]


def render(match: "re.Match", txt_lines: List[str], warnings: List[str]) -> str:
    lines = cell_lines(match.group(1))
    if not lines:
        return ""

    if lines[0].startswith("**") and lines[0].endswith("**") and len(lines[0]) < 60:
        label = lines[0]
        body = lines[1:]
        quoted = "\n>\n".join(
            "\n".join(f"> {ln}" for ln in para.split("\n")) for para in body
        )
        return f"> {label}\n>\n{quoted}" if quoted else f"> {label}"

    exact = find_exact_block(txt_lines, lines)
    if exact is not None:
        lines = exact
    else:
        warnings.append(lines[0][:60])

    return "```\n" + "\n".join(lines) + "\n```"


def convert(md_path: str, txt_path: str) -> None:
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    with open(txt_path, encoding="utf-8") as f:
        txt_lines = f.read().splitlines()

    warnings: List[str] = []
    text = BLOCK_RE.sub(lambda m: render(m, txt_lines, warnings), text)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(text)

    if warnings:
        print(f"  [fix_boxed_tables] {md_path}: no unique whitespace-exact match for "
              f"{len(warnings)} block(s), used collapsed-whitespace fallback:", file=sys.stderr)
        for w in warnings:
            print(f"    - {w!r}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: fix_boxed_tables.py <doc.md> <doc.txt>", file=sys.stderr)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
