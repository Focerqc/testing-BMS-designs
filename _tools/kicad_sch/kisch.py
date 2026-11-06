"""Minimal read-only KiCad 10 schematic reader: placed symbols with pin end points,
labels, wires and no-connect flags. Shared by the other scripts in this folder.

Pin end points follow KiCad's transform: library coordinates are y-up, the sheet is
y-down, then mirror, then rotation (counter-clockwise on screen).
"""
import math
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCH = ROOT / "slave-18s" / "adbms1818-slave-18s.kicad_sch"
KICAD_CLI = os.environ.get("KICAD_CLI", r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")


def tokenize(s):
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            yield c
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while s[j] != '"':
                if s[j] == "\\":
                    buf.append(s[j + 1]); j += 2
                else:
                    buf.append(s[j]); j += 1
            yield ("S", "".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and s[j] not in " \t\r\n()":
                j += 1
            yield ("A", s[i:j])
            i = j


def parse(s):
    stack = [[]]
    for t in tokenize(s):
        if t == "(":
            stack.append([])
        elif t == ")":
            x = stack.pop()
            stack[-1].append(x)
        else:
            stack[-1].append(t[1])
    return stack[0][0]


def kids(node, name):
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def kid(node, name):
    k = kids(node, name)
    return k[0] if k else None


def load(path=DEFAULT_SCH):
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


def lib_pins(libsym):
    """{pin_number: dict(name, type, x, y, angle, len, unit)} in library coordinates (y up)."""
    pins = {}
    for sub in kids(libsym, "symbol"):
        m = re.search(r"_(\d+)_(\d+)$", sub[1])
        unit = int(m.group(1)) if m else 0
        for p in kids(sub, "pin"):
            at = kid(p, "at")
            ln = kid(p, "length")
            pins[kid(p, "number")[1]] = dict(
                type=p[1], name=kid(p, "name")[1], x=float(at[1]), y=float(at[2]),
                angle=float(at[3]) if len(at) > 3 else 0.0,
                len=float(ln[1]) if ln else 0.0, unit=unit)
    return pins


def _orient(x, y, rot, mirror):
    """Library vector (y up) -> sheet vector (y down), mirror, then CCW rotation."""
    y = -y
    if mirror == "x":
        y = -y
    elif mirror == "y":
        x = -x
    a = math.radians(rot)
    return x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a)


def outward(pin, sym):
    """Sheet direction ('right'/'up'/'left'/'down') pointing away from the symbol body."""
    a = math.radians(pin["angle"])
    dx, dy = _orient(math.cos(a), math.sin(a), sym["rot"], sym["mirror"])  # into the body
    ox, oy = -dx, -dy
    if abs(ox) > abs(oy):
        return "right" if ox > 0 else "left"
    return "down" if oy > 0 else "up"


def symbols(tree):
    libs = {s[1]: s for s in kids(kid(tree, "lib_symbols"), "symbol")}
    out = []
    for s in kids(tree, "symbol"):
        lib_id = kid(s, "lib_id")[1]
        at = kid(s, "at")
        sx, sy = float(at[1]), float(at[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        mir = kid(s, "mirror")
        props = {p[1]: p[2] for p in kids(s, "property")}
        unit = int(kid(s, "unit")[1]) if kid(s, "unit") else 1
        sym = dict(ref=props.get("Reference"), value=props.get("Value"), lib_id=lib_id,
                   x=sx, y=sy, rot=rot, mirror=mir[1] if mir else None, props=props, pins={})
        ls = libs.get(lib_id)
        if ls is not None:
            for num, p in lib_pins(ls).items():
                if p["unit"] not in (0, unit):
                    continue
                dx, dy = _orient(p["x"], p["y"], rot, sym["mirror"])
                sym["pins"][num] = dict(p, ex=round(sx + dx, 4), ey=round(sy + dy, 4))
        out.append(sym)
    return out


def labels(tree):
    out = []
    for kind in ("label", "global_label", "hierarchical_label"):
        for l in kids(tree, kind):
            at = kid(l, "at")
            out.append(dict(kind=kind, name=l[1], x=float(at[1]), y=float(at[2]),
                            angle=float(at[3]) if len(at) > 3 else 0.0))
    return out


def wires(tree):
    return [[(float(p[1]), float(p[2])) for p in kids(kid(w, "pts"), "xy")] for w in kids(tree, "wire")]


def no_connects(tree):
    return [(float(kid(n, "at")[1]), float(kid(n, "at")[2])) for n in kids(tree, "no_connect")]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="List placed symbols (and pins for refs matching --pins).")
    ap.add_argument("--sch", default=str(DEFAULT_SCH))
    ap.add_argument("--pins", help="regex of references whose pin end points to print, e.g. '^(U1|Q301)$'")
    a = ap.parse_args()
    t = load(a.sch)
    for s in sorted(symbols(t), key=lambda s: s["ref"] or ""):
        print(f"{s['ref']:7} {s['value'] or '':16} {s['lib_id']:30} at=({s['x']},{s['y']}) rot={s['rot']:g} mirror={s['mirror']}")
        if a.pins and re.match(a.pins, s["ref"] or ""):
            for num, p in sorted(s["pins"].items(), key=lambda kv: (len(kv[0]), kv[0])):
                print(f"    pin {num:>3} {p['name']:10} {p['type']:14} end=({p['ex']},{p['ey']}) out={outward(p, s)}")
    print(f"labels {len(labels(t))}  wires {len(wires(t))}  no-connects {len(no_connects(t))}")
