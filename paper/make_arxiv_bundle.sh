#!/usr/bin/env bash
# Make the arXiv source bundle from a build of paper/build.sh, and optionally verify it with pdfLaTeX.
#
#   paper/make_arxiv_bundle.sh [BUILD_DIR]      default BUILD_DIR: ./out/paper (must hold pixeltree.tex + pixeltree.bbl)
#
# Output: BUILD_DIR/arxiv_bundle.zip with
#   pixeltree.tex   (with \pdfoutput=1 on its first line, so arXiv uses pdfLaTeX)
#   pixeltree.bbl   (arXiv does not need refs.bib when the .bbl is present)
#   fvextra.sty, xurl.sty  (copied from the local TeX installation when KPSEWHICH finds them; both LPPL)
# No fonts are bundled: under pdfLaTeX the paper uses only standard TeX fonts (Latin Modern, AMS symbols and the
# Arphic "gbsn" CJK font through the CJK package for the two quoted OCR glyphs).
#
# Verification (recommended): PDFLATEX=/path/to/pdflatex KPSEWHICH=/path/to/kpsewhich paper/make_arxiv_bundle.sh
# compiles the unpacked bundle twice in BUILD_DIR/arxiv_check and fails on LaTeX errors or missing glyphs.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUILD="${1:-$REPO/out/paper}"
BUILD="$(cd "$BUILD" && pwd)"
for f in pixeltree.tex pixeltree.bbl; do
  [ -f "$BUILD/$f" ] || { echo "missing $BUILD/$f: run paper/build.sh first" >&2; exit 1; }
done

STAGE="$BUILD/arxiv_bundle"
rm -rf "$STAGE" && mkdir -p "$STAGE"
{ printf '\\pdfoutput=1\n'; cat "$BUILD/pixeltree.tex"; } > "$STAGE/pixeltree.tex"
cp "$BUILD/pixeltree.bbl" "$STAGE/"
KPSEWHICH="${KPSEWHICH:-kpsewhich}"
if command -v "$KPSEWHICH" >/dev/null 2>&1; then
  for sty in fvextra.sty xurl.sty; do
    src="$("$KPSEWHICH" "$sty" || true)"
    [ -n "$src" ] && cp "$src" "$STAGE/" || echo "note: $sty not found locally; arXiv's TeX Live provides it" >&2
  done
fi
rm -f "$BUILD/arxiv_bundle.zip"
(cd "$STAGE" && python3 -c "import sys,zipfile,os;z=zipfile.ZipFile(sys.argv[1],'w',zipfile.ZIP_DEFLATED);[z.write(f) for f in sorted(os.listdir('.'))];z.close()" "$BUILD/arxiv_bundle.zip")
echo "wrote $BUILD/arxiv_bundle.zip:"; (cd "$STAGE" && ls -l)

PDFLATEX="${PDFLATEX:-}"
[ -z "$PDFLATEX" ] && { echo "PDFLATEX not set: bundle not compiled"; exit 0; }
CHECK="$BUILD/arxiv_check"
rm -rf "$CHECK" && mkdir -p "$CHECK"
(cd "$CHECK" && python3 -c "import sys,zipfile;zipfile.ZipFile(sys.argv[1]).extractall('.')" "$BUILD/arxiv_bundle.zip")
for pass in 1 2; do
  (cd "$CHECK" && "$PDFLATEX" -interaction=nonstopmode -halt-on-error pixeltree.tex >/dev/null) || {
    echo "pdflatex FAILED (pass $pass); see $CHECK/pixeltree.log" >&2; grep -n "^!" "$CHECK/pixeltree.log" | head >&2; exit 1; }
done
missing="$(grep -c "Missing character" "$CHECK/pixeltree.log" || true)"
undef="$(grep -cE "Citation .* undefined|Reference .* undefined" "$CHECK/pixeltree.log" || true)"
over="$(grep -c "Overfull \\\\hbox" "$CHECK/pixeltree.log" || true)"
pages="$(pdfinfo "$CHECK/pixeltree.pdf" 2>/dev/null | sed -n 's/^Pages:[[:space:]]*//p')"
echo "pdflatex OK: $CHECK/pixeltree.pdf, pages=${pages:-?}, missing glyphs=$missing, undefined refs=$undef, overfull hboxes=$over"
[ "$missing" = "0" ] && [ "$undef" = "0" ] || exit 1
