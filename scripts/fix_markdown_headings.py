#!/usr/bin/env python3
"""Promote bold pseudo-headings in pandoc-converted docx output to real Markdown headings.

The Apex Coach .docx source docs use bold-text paragraphs instead of Word
heading styles, so pandoc emits `**1.2 Title**` instead of `## 1.2 Title`.
This rewrites those lines into real ATX headings so GitHub renders a proper
outline and anchors. Run via scripts/convert_docs.sh, not directly.
"""
import re
import sys

NUMBERED = [
    (re.compile(r"^\*\*(\d+\.\d+\.\d+)\s+(.+)\*\*$"), r"#### \1 \2"),
    (re.compile(r"^\*\*(\d+\.\d+)\s+(.+)\*\*$"), r"### \1 \2"),
    (re.compile(r"^\*\*(\d+)\.\s+(.+)\*\*$"), r"## \1. \2"),
]
ROADMAP_VERSION = re.compile(r"^\*\*(v\d+(\.\d+)?\s*—.+)\*\*$")
GENERIC_BOLD_LINE = re.compile(r"^\*\*([^*]+)\*\*$")
TITLE_LINE = re.compile(r"^\*\*APEX COACH\*\*$")


def convert(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    out = []
    title_seen = False
    subtitle_done = False
    for line in lines:
        if not title_seen and TITLE_LINE.match(line):
            out.append("# Apex Coach")
            title_seen = True
            continue

        if title_seen and not subtitle_done and line.strip() and not line.startswith(("|", "*")):
            out.append(f"## {line.strip()}")
            subtitle_done = True
            continue

        matched = False
        for pattern, repl in NUMBERED:
            if pattern.match(line):
                out.append(pattern.sub(repl, line))
                matched = True
                break
        if matched:
            continue

        if ROADMAP_VERSION.match(line):
            out.append(ROADMAP_VERSION.sub(r"### \1", line))
            continue

        if GENERIC_BOLD_LINE.match(line) and line not in ("**", ""):
            out.append(GENERIC_BOLD_LINE.sub(r"#### \1", line))
            continue

        out.append(line)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


if __name__ == "__main__":
    for path in sys.argv[1:]:
        convert(path)
