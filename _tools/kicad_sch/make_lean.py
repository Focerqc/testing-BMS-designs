"""Derive the 18S Lean schematic (no hot-plug protection) from the 18S Guard schematic.

Lean = Guard minus:
  F100-F118  tap fuses        -> connector pins land straight on CELLn (TAPn renamed CELLn)
  F119       V+ supply fuse   -> VBAT_F renamed CELL18
  F120       V- supply fuse   -> CELL0 renamed V- (C0 sense and V- share the bottom tap)
  D101-D118  zener clamps between neighbouring C pins
  D301       V+ TVS (no fuse ahead of it any more, so a shorted TVS would short the stack)
  C101-C118  C-pin filter caps (the 10 ohm series resistors R100-R118 stay)

Labels sitting on a removed part's pin ends are deleted with it. The Guard file is never
written. Re-run after any Guard schematic change, then:
  kicad-cli sch upgrade --force <lean sch>
  python _tools/kicad_sch/check_slave18s.py --variant lean

usage: python _tools/kicad_sch/make_lean.py [--dry]
"""
import argparse
import re
import sys

from kisch import ROOT, load, symbols

GUARD = ROOT / "slave-18s" / "adbms1818-slave-18s.kicad_sch"
LEAN_DIR = ROOT / "slave-18s-lean"
LEAN = LEAN_DIR / "adbms1818-slave-18s-lean.kicad_sch"

REMOVE = ({f"F1{n:02d}" for n in range(21)} | {f"D1{n:02d}" for n in range(1, 19)}
          | {"D301"} | {f"C1{n:02d}" for n in range(1, 19)})


DROP_TEXT = tuple(f'(text "{h}' for h in ("ZENER CLAMPS", "TAP FUSES", "C101-C118", "SUPPLY FUSES"))
RETEXT = {
    '"ADBMS1818 18S slave module"': '"ADBMS1818 18S slave module - Lean (no hot-plug protection)"',
    "TAPn = connector side of fuse F1nn, CELLn = after it. V- (chip ground) has its own fuse F120.":
        "18S Lean: no fuses, clamps or C-pin caps; generated from slave-18s by make_lean.py, do not edit by hand. "
        "C0 sense and V- share the bottom tap (J1.1).",
}


def rename(name):
    m = re.fullmatch(r"TAP(\d+)", name)
    if m:
        name = f"CELL{m.group(1)}"
    return {"VBAT_F": "CELL18", "CELL0": "V-"}.get(name, name)


def top_blocks(text):
    """(start, end, head) for each depth-1 s-expression of the file."""
    depth, start, i, n = 0, None, 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
            if depth == 2:
                start = i
        elif c == ")":
            if depth == 2:
                yield start, i + 1, text[start + 1:start + 40].split(None, 1)[0]
            depth -= 1
        i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    text = GUARD.read_text(encoding="utf-8")
    syms = {s["ref"]: s for s in symbols(load(GUARD))}
    missing = REMOVE - set(syms)
    if missing:
        sys.exit(f"parts not in the Guard schematic: {sorted(missing)}")
    dead_ends = {(round(p["ex"], 2), round(p["ey"], 2)) for r in REMOVE for p in syms[r]["pins"].values()}

    out, last, gone = [], 0, {"symbol": 0, "label": 0, "wire": 0, "text": 0}
    for s, e, head in top_blocks(text):
        blk = text[s:e]
        drop = False
        if head == "symbol":
            m = re.search(r'\(property "Reference" "([^"]+)"', blk)
            drop = bool(m and m.group(1) in REMOVE)
        elif head == "label":
            m = re.search(r"\(at ([-\d.]+) ([-\d.]+)", blk)
            drop = (round(float(m.group(1)), 2), round(float(m.group(2)), 2)) in dead_ends
        elif head == "text":
            drop = blk.startswith(DROP_TEXT)
        elif head == "wire":
            pts = re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", blk)
            drop = any((round(float(x), 2), round(float(y), 2)) in dead_ends for x, y in pts)
        if drop:
            gone[head] += 1
            j = e
            while j < len(text) and text[j] in " \t":
                j += 1
            if text[j:j + 2] == "\r\n":
                j += 2
            elif text[j:j + 1] == "\n":
                j += 1
            out.append(text[last:s].rstrip(" \t")); last = j
            continue
        if head == "label":
            blk2 = re.sub(r'^\(label "([^"]+)"', lambda m: f'(label "{rename(m.group(1))}"', blk)
            if blk2 != blk:
                out.append(text[last:s]); out.append(blk2); last = e
    out.append(text[last:])
    lean = "".join(out).replace('(project "adbms1818-slave-18s"', '(project "adbms1818-slave-18s-lean"')

    for old, new in RETEXT.items():
        if old not in lean:
            sys.exit(f"text not found in Guard: {old[:60]}")
        lean = lean.replace(old, new)
    print("removed", gone)
    if a.dry:
        return
    LEAN.write_text(lean, encoding="utf-8", newline="")
    print("wrote", LEAN)


if __name__ == "__main__":
    main()
