"""Sandbox HOME contents (documents, synthetic pictures, a 3-page PDF) shared by every app, and orphan cleanup."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

SENTENCES = [
    "The quarterly report is ready for review.",
    "Please update the meeting notes before Friday.",
    "Drag the window to the left side of the screen.",
    "The accessibility tree exposes roles, names and states.",
    "A short paragraph keeps the text area busy.",
    "Open the preferences dialog to change the theme.",
    "Save the document before closing the editor.",
    "The file manager lists folders and files in a grid.",
    "Type a few lines so the text box contains content.",
    "The calculator evaluates simple arithmetic expressions.",
    "Use the keyboard shortcut to open a new window.",
    "The terminal runs safe read only commands here.",
    "Reports and notes live in the documents folder.",
    "Images in the pictures folder are synthetic.",
    "The clock shows the current local time.",
    "Scroll the list to see the remaining entries.",
    "This sentence is plain ASCII on purpose.",
    "Labels inside buttons are absorbed by their parent.",
    "The probe reports the true surface geometry.",
    "Matching uses the AT-SPI window extents as a key.",
]


def _write_pdf(path, pages):
    """Write a small text-only PDF (Helvetica, one block of lines per page)."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    for i, lines in enumerate(pages):
        page_id, content_id = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_id} 0 R")
        body = ["BT /F1 14 Tf 72 720 Td 20 TL"]
        for line in lines:
            body.append("(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
        body.append("ET")
        stream = "\n".join(body).encode("latin-1", "replace")
        objs[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
                         f"/Resources << /Font << /F1 3 0 R >> >> >>").encode()
        objs[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    objs[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for num in sorted(objs):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    Path(path).write_bytes(bytes(out))


def prepare_sandbox(home):
    """Fill the sandbox HOME with the files and synthetic pictures the apps need."""
    home = Path(home)
    for rel in ("Documents/reports", "Projects/vax-demo/notes", "Pictures", "Music",
                "Videos", "Downloads"):
        (home / rel).mkdir(parents=True, exist_ok=True)
    notes = "\n".join(f"Line {i:02d}: {SENTENCES[i % len(SENTENCES)]}" for i in range(20))
    (home / "Documents" / "notes.txt").write_text(notes + "\n")
    (home / "Documents" / "reports" / "weekly-report.txt").write_text(
        "Weekly report\n" + "\n".join(SENTENCES[:8]) + "\n")
    (home / "Projects" / "vax-demo" / "notes" / "meeting-notes.txt").write_text(
        "Meeting notes\n" + "\n".join(SENTENCES[8:14]) + "\n")
    rng = np.random.default_rng(7)
    for i in range(3):
        h, w = 600, 800
        grad = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
        img = np.zeros((h, w, 3), np.uint8)
        for c in range(3):
            img[:, :, c] = np.clip(grad + (c + 1) * 20 + i * 30, 0, 255)
        for _ in range(5):
            x0, y0 = int(rng.integers(0, w - 120)), int(rng.integers(0, h - 120))
            x1, y1 = x0 + int(rng.integers(40, 120)), y0 + int(rng.integers(40, 120))
            color = tuple(int(v) for v in rng.integers(0, 256, 3))
            if rng.random() < 0.5:
                cv2.rectangle(img, (x0, y0), (x1, y1), color, -1)
            else:
                cv2.circle(img, ((x0 + x1) // 2, (y0 + y1) // 2),
                           min(60, (x1 - x0) // 2), color, -1)
        cv2.imwrite(str(home / "Pictures" / f"sample_{i}.png"), img)
    _write_pdf(home / "Documents" / "sample.pdf",
               [["Quarterly report", ""] + SENTENCES[i * 6:i * 6 + 12] for i in range(3)])
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-nodes", "-keyout", "/dev/null", "-out", str(home / "Documents" / "sample-cert.pem"),
         "-days", "365", "-subj", "/C=US/O=Vax Demo Org/OU=Docs/CN=vax-demo.example.com"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def reap_sandbox(sandbox):
    """Kill orphans (portal- or bus-activated apps) that still run with the sandbox HOME."""
    needle = f"HOME={Path(sandbox).resolve() / 'home'}".encode()
    victims = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if needle in (entry / "environ").read_bytes().split(b"\0"):
                victims.append(int(entry.name))
        except OSError:
            continue
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in victims:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                continue
        if sig == signal.SIGTERM and victims:
            time.sleep(0.5)
    return len(victims)

