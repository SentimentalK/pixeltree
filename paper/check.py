"""Checks for the built paper PDF (standard library + poppler's pdftotext / pdfinfo).

1. page count (printed);
2. overfull horizontal boxes in the LaTeX log (text, tables or code sticking into the margin): fails above --max-overfull-pt;
3. numbers: every number in PAPER.md must appear in the PDF text at least as often (the PDF is generated from PAPER.md,
   so a miss means the conversion dropped or mangled something). Extra numbers in the PDF (section numbers, page
   numbers, bibliography years) are allowed.

Exit code 0 when all checks pass.
"""
import argparse
import collections
import re
import subprocess
import sys

NUM = re.compile(r"\d+(?:[.,]\d+)*")


def numbers(text):
    text = text.replace("­", "")
    out = collections.Counter()
    for m in NUM.finditer(text):
        out[m.group(0).replace(",", "")] += 1
    return out


def markdown_numbers(md):
    md = re.sub(r"\]\([^)]*\)", "]", md)          # link targets are not printed
    md = re.sub(r"<[^>]+>", "", md)
    lines = md.splitlines()
    keep = []
    for i, line in enumerate(lines):
        if line.startswith("#"):
            line = re.sub(r"^#+\s+\d+(\.\d+)*\.?\s*", "", line)   # LaTeX renumbers sections itself
        keep.append(line)
    return numbers("\n".join(keep))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paper", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--max-overfull-pt", type=float, default=1.0)
    a = ap.parse_args()
    ok = True

    info = subprocess.run(["pdfinfo", a.pdf], capture_output=True, text=True, check=True).stdout
    pages = int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1))
    print(f"pages: {pages}")

    log = open(a.log, encoding="utf-8", errors="replace").read()
    over = [float(x) for x in re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide\)", log)]
    big = [x for x in over if x > a.max_overfull_pt]
    print(f"overfull hboxes: {len(over)} (max {max(over) if over else 0:.1f} pt); above {a.max_overfull_pt} pt: {len(big)}")
    if big:
        ok = False

    pdf_text = subprocess.run(["pdftotext", "-layout", a.pdf, "-"], capture_output=True, text=True, check=True).stdout
    want = markdown_numbers(open(a.paper, encoding="utf-8").read())
    have = numbers(pdf_text)
    missing = {k: (v, have.get(k, 0)) for k, v in want.items() if have.get(k, 0) < v}
    print(f"numbers: {sum(want.values())} in PAPER.md ({len(want)} distinct); missing or fewer in PDF: {len(missing)}")
    for k, (w, h) in sorted(missing.items()):
        print(f"  {k}: PAPER.md {w}x, PDF {h}x")
    if missing:
        ok = False
    print("check: OK" if ok else "check: FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
