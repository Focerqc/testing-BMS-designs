"""Move a group of placed symbols by (DX, DY) mm together with their fields and with every
local label and no-connect flag sitting on one of their pin ends.

Why: KiCad MCP move_schematic_component moves the symbol but leaves the labels at the old
pin positions (they become floating). Keep DX/DY multiples of 2.54 mm, then run
`kicad-cli sch upgrade --force` and lint_offgrid.

usage: python _tools/kicad_sch/shift_group.py DX DY REF [REF ...] [--sch FILE]
"""
import argparse
import re

from kisch import DEFAULT_SCH, load, symbols


def fmt(v):
    return f"{round(v, 4):g}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dx", type=float)
    ap.add_argument("dy", type=float)
    ap.add_argument("refs", nargs="+")
    ap.add_argument("--sch", default=str(DEFAULT_SCH))
    a = ap.parse_args()
    refs = set(a.refs)

    pts = {(round(p["ex"], 2), round(p["ey"], 2))
           for s in symbols(load(a.sch)) if s["ref"] in refs for p in s["pins"].values()}
    txt = open(a.sch, encoding="utf-8").read()

    out, pos, moved = [], 0, 0
    for m in re.finditer(r'\t\(symbol\n\t\t\(lib_id "[^"]+"\)\n', txt):
        start = m.start()
        end = txt.index("\n\t)\n", start) + 4
        block = txt[start:end]
        rm = re.search(r'\(property "Reference" "([^"]+)"', block)
        if not rm or rm.group(1) not in refs:
            continue
        head, sep, tail = block.partition("\t\t(instances")
        head = re.sub(r"\(at ([-\d.]+) ([-\d.]+)",
                      lambda q: f"(at {fmt(float(q.group(1)) + a.dx)} {fmt(float(q.group(2)) + a.dy)}", head)
        out += [txt[pos:start], head + sep + tail]
        pos = end
        moved += 1
    out.append(txt[pos:])
    txt = "".join(out)

    n = 0

    def shift(q):
        nonlocal n
        x, y = float(q.group(2)), float(q.group(3))
        if (round(x, 2), round(y, 2)) not in pts:
            return q.group(0)
        n += 1
        return f"{q.group(1)}{fmt(x + a.dx)} {fmt(y + a.dy)}"

    txt = re.sub(r'(\((?:label "[^"]*"|no_connect)\s*\(at )([-\d.]+) ([-\d.]+)', shift, txt)
    open(a.sch, "w", encoding="utf-8", newline="").write(txt)
    print(f"symbols moved: {moved}/{len(refs)}; labels/no-connects moved: {n}")
    if moved != len(refs):
        print("WARN: some references were not found (the file must be in KiCad's own format: "
              "run kicad-cli sch upgrade --force first)")


if __name__ == "__main__":
    main()
