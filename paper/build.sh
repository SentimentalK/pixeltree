#!/usr/bin/env bash
# Build the arXiv-style PDF of PAPER.md:  PAPER.md --(pandoc + filter.lua)--> pixeltree.tex --(tectonic)--> pixeltree.pdf
#
#   paper/build.sh [OUT_DIR]          default OUT_DIR: ./out/paper (git-ignored)
#
# Tools (user-level binaries, no sudo): pandoc >= 3.1 and tectonic >= 0.15, found on PATH or given as
#   PANDOC=/path/to/pandoc TECTONIC=/path/to/tectonic paper/build.sh
# Author line: PAPER_AUTHOR="Name (Affiliation)"; default = the GitHub owner of the 'origin' remote.
# Without tectonic the script stops after writing pixeltree.tex (compile it on Overleaf with XeLaTeX, see
# paper/SUBMISSION_NOTES.md). After compiling, paper/check.py checks page count, overfull boxes and numbers.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
OUT="${1:-$REPO/out/paper}"
PANDOC="${PANDOC:-pandoc}"
TECTONIC="${TECTONIC:-tectonic}"
PYTHON="${PYTHON:-python3}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

if [ -z "${PAPER_AUTHOR:-}" ]; then
  origin="$(git -C "$REPO" remote get-url origin 2>/dev/null || true)"
  PAPER_AUTHOR="$(printf '%s' "$origin" | sed -n 's#.*github\.com[:/]\([^/]*\)/.*#\1#p')"
  PAPER_AUTHOR="${PAPER_AUTHOR:-Author}"
fi

"$PANDOC" "$REPO/PAPER.md" \
  --from markdown+lists_without_preceding_blankline-auto_identifiers-implicit_figures \
  --to latex --standalone \
  --lua-filter "$HERE/filter.lua" \
  --include-in-header "$HERE/preamble.tex" \
  --include-after-body "$HERE/backmatter.tex" \
  --columns 40 \
  -V documentclass=article -V fontsize=11pt -V papersize=a4 \
  -V geometry:margin=2.5cm -V colorlinks=true -V linkcolor=blue -V urlcolor=blue -V citecolor=blue \
  -V numbersections=true \
  -M author="$PAPER_AUTHOR" -M date="$(git -C "$REPO" log -1 --format=%cs -- PAPER.md 2>/dev/null || date +%F)" \
  -o "$OUT/pixeltree.tex"
cp "$HERE/refs.bib" "$OUT/refs.bib"
echo "wrote $OUT/pixeltree.tex"

if ! command -v "$TECTONIC" >/dev/null 2>&1; then
  echo "tectonic not found: stopping after the .tex (compile pixeltree.tex + refs.bib with XeLaTeX + BibTeX)" >&2
  exit 0
fi
(cd "$OUT" && "$TECTONIC" --keep-logs --keep-intermediates pixeltree.tex)
echo "wrote $OUT/pixeltree.pdf"
"$PYTHON" "$HERE/check.py" --paper "$REPO/PAPER.md" --pdf "$OUT/pixeltree.pdf" --log "$OUT/pixeltree.log"
