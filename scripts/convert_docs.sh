#!/usr/bin/env bash
# Regenerate docs/*.md from the .docx source documents at the repo root.
# The .docx files are the authored source; the .md files are a generated,
# GitHub-readable mirror. Run this after editing any .docx, then commit
# both together so README.md's doc table and the docs/ mirror never drift.
#
# Uses pandoc for structure (headings, tables) and macOS's `textutil` as a
# whitespace-preserving side source for diagrams/code/pseudocode boxes,
# since pandoc's docx reader collapses internal spacing in table cells.
# textutil is macOS-only; without it, boxed blocks still convert but may
# lose column alignment (see fix_boxed_tables.py warnings).
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v pandoc &>/dev/null; then
  echo "pandoc is required: brew install pandoc" >&2
  exit 1
fi

mkdir -p docs
tmp_txt="$(mktemp)"
trap 'rm -f "$tmp_txt"' EXIT

for docx in ApexCoach_PRD_v1.0 ApexCoach_SDD_v1.0 ApexCoach_API_Integration_Contract_v1.0 ApexCoach_Logic_Algorithm_Spec_v1.0; do
  pandoc "${docx}.docx" -f docx -t gfm --wrap=preserve -o "docs/${docx}.md"
  python3 scripts/fix_markdown_headings.py "docs/${docx}.md"

  if command -v textutil &>/dev/null; then
    textutil -convert txt -stdout "${docx}.docx" >"$tmp_txt"
  else
    : >"$tmp_txt"
  fi
  python3 scripts/fix_boxed_tables.py "docs/${docx}.md" "$tmp_txt"
  echo "converted ${docx}.docx -> docs/${docx}.md"
done
