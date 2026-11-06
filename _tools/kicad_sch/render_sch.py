"""Render a schematic (or a region of it) to PNG: kicad-cli PDF export, then PyMuPDF.
Coordinates are sheet millimetres, the same numbers as in the .kicad_sch file.

usage: python _tools/kicad_sch/render_sch.py OUT.png [--sch FILE] [--region X0 Y0 X1 Y1] [--zoom 3]
Needs PyMuPDF (pip install pymupdf).
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

from kisch import DEFAULT_SCH, KICAD_CLI


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--sch", default=str(DEFAULT_SCH))
    ap.add_argument("--region", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--zoom", type=float, default=3.0)
    a = ap.parse_args()

    pdf = Path(tempfile.gettempdir()) / "render_sch.pdf"
    r = subprocess.run([KICAD_CLI, "sch", "export", "pdf", "--output", str(pdf), a.sch],
                       capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    page = pymupdf.open(pdf)[0]
    k = 72 / 25.4
    clip = pymupdf.Rect(*(v * k for v in a.region)) if a.region else page.rect
    pix = page.get_pixmap(matrix=pymupdf.Matrix(a.zoom, a.zoom), clip=clip)
    pix.save(a.out)
    print(a.out, pix.width, "x", pix.height)


if __name__ == "__main__":
    main()
