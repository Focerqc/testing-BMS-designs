"""Turn every local label that sits on a pin end so its text points away from the symbol,
and round label coordinates (removes float noise such as 78.74000000000001).

Why: KiCad MCP batch_connect (v2.7.0) writes every label facing INTO its part.
get_pin_angle() already returns the outward angle and batch_connect flips it again
(python/commands/schematic_batch.py, the {0: 180, 90: 270, ...} map).

Label anchors never move, so connectivity cannot change. Labels that are not on a pin end
(e.g. at a wire end) are left alone and listed. Re-save with
`kicad-cli sch upgrade --force` afterwards.

KiCad label spin in the file:  right = angle 0 'left bottom'    up   = angle 90  'left bottom'
                               left  = angle 180 'right bottom' down = angle 270 'right bottom'
usage: python _tools/kicad_sch/orient_labels.py [--sch FILE] [--dry]
"""
import argparse
import re

from kisch import DEFAULT_SCH, load, outward, symbols

SPIN = {"right": (0, "left bottom"), "up": (90, "left bottom"),
        "left": (180, "right bottom"), "down": (270, "right bottom")}
LABEL = re.compile(r'(\(label "(?P<name>[^"]*)"\s*\(at )(?P<x>[-\d.]+) (?P<y>[-\d.]+) (?P<a>[-\d.]+)\)'
                   r'(?P<mid>.*?)\(justify (?P<j>[a-z ]+)\)', re.S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sch", default=str(DEFAULT_SCH))
    ap.add_argument("--dry", action="store_true", help="report only")
    a = ap.parse_args()

    ends = {}
    for s in symbols(load(a.sch)):
        for p in s["pins"].values():
            ends.setdefault((round(p["ex"], 2), round(p["ey"], 2)), []).append((s["ref"], outward(p, s)))
    txt = open(a.sch, encoding="utf-8").read()
    changed, offpin = 0, []

    def fix(m):
        nonlocal changed
        x, y = float(m["x"]), float(m["y"])
        xs, ys = f"{round(x, 4):g}", f"{round(y, 4):g}"
        hits = ends.get((round(x, 2), round(y, 2)))
        if not hits:
            offpin.append((m["name"], x, y))
            return f'{m.group(1)}{xs} {ys} {m["a"]}){m["mid"]}(justify {m["j"]})'
        if len({h[1] for h in hits}) > 1:
            print("WARN: pins facing different ways share this point:", m["name"], x, y, hits)
        ang, just = SPIN[hits[0][1]]
        if int(float(m["a"])) != ang or m["j"] != just or xs != m["x"] or ys != m["y"]:
            changed += 1
        return f'{m.group(1)}{xs} {ys} {ang}){m["mid"]}(justify {just})'

    new = LABEL.sub(fix, txt)
    print(f"labels turned/rounded: {changed}; not on a pin end: {len(offpin)}")
    for o in offpin:
        print("  off-pin (left alone):", o)
    if not a.dry and new != txt:
        open(a.sch, "w", encoding="utf-8", newline="").write(new)


if __name__ == "__main__":
    main()
