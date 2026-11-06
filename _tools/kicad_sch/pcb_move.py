"""Move PCB footprints by editing only their `(at x y [rot])` line in the .kicad_pcb.

Pads, text and graphics inside a footprint are stored relative to it, so a translation
needs no other change, and the diff stays one line per moved part (the MCP board tools
rewrite the whole file). Rotation is kept unless the map gives one.

usage: python _tools/kicad_sch/pcb_move.py MOVES.json [--pcb FILE] [--dry]
MOVES.json: {"U1": [75, 40], "J1": [8, 5, 90], ...}   (mm, board coordinates)
Close KiCad first: an open PCB Editor will not see the change and saving from it
overwrites it.
"""
import argparse
import json
import re
import sys

from kisch import DEFAULT_SCH

AT = re.compile(r"^(\t\t\(at )([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)(?=\r?$)", re.M)


def fmt(v):
    return f"{round(float(v), 4):g}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("moves")
    ap.add_argument("--pcb", default=str(DEFAULT_SCH.with_suffix(".kicad_pcb")))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    moves = json.load(open(a.moves, encoding="utf-8"))
    text = open(a.pcb, encoding="utf-8", newline="").read()

    starts = [m.start() for m in re.finditer(r"^\t\(footprint ", text, re.M)] + [len(text)]
    out, last, done = [], 0, set()
    for s, e in zip(starts, starts[1:]):
        block = text[s:e]
        ref = re.search(r'\(property "Reference" "([^"]+)"', block).group(1)
        if ref not in moves:
            continue
        m = AT.search(block)
        x, y, *rot = moves[ref]
        r = fmt(rot[0]) if rot else m.group(4)
        new = f"{m.group(1)}{fmt(x)} {fmt(y)}{' ' + r if r and float(r) else ''})"
        out.append(text[last:s + m.start()] + new)
        last = s + m.end()
        done.add(ref)
    out.append(text[last:])
    missing = sorted(set(moves) - done)
    if missing:
        sys.exit(f"not on the board: {missing}")
    print(f"moved {len(done)} footprints" + (" (dry run)" if a.dry else ""))
    if not a.dry:
        open(a.pcb, "w", encoding="utf-8", newline="").write("".join(out))


if __name__ == "__main__":
    main()
