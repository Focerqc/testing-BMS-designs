"""Derive the 18S Lean schematic (no hot-plug protection) from the 18S Guard schematic.

Lean = Guard minus:
  F100-F118  tap fuses        -> connector pins land straight on CELLn (TAPn renamed CELLn)
  F119       V+ supply fuse   -> VBAT_F renamed CELL18
  F120       V- supply fuse   -> net tie NT1 in its place: CELL0 (J1.1 + the C0 sense R100) meets
                                 V- only there, so DRC flags any other copper joining them
  D101-D118  zener clamps between neighbouring C pins
  D301       V+ TVS (no fuse ahead of it any more, so a shorted TVS would short the stack)
  C101-C118  C-pin filter caps (the 10 ohm series resistors R100-R118 stay)
  J6, J7     DNP JST PH alternates to the isoSPI GH plugs J3/J4: both ports only fit the
             70 mm board without them (2026-11-09 shrink trial, try 2)
  TP1-TP14   test points: the working reference board has none, the nets can be probed on a
             resistor or capacitor pad, and the board sits flat on a carrier (2026-11-10, try 3)

and with these parts swapped (SWAP below, same nets):
  R201-R218  balance 33 ohm 2512 (1 W) -> 120 ohm 1206 (0.25 W): about 31 mA and 0.12 W per
             cell instead of 89 mA and 0.26 W (2026-11-10, try 3; was 33 ohm 2010 in tries 1-2)
  R100-R118  10 ohm series 1206 -> 0603: they carry the balance current, now about 10 mW each
             (2026-11-10, try 3)
  T501, T601 isoSPI transformer Pulse HM2113ZNL -> Bourns SM91502AL (same pin functions:
             chip 1-2CT-3, line 6-5CT-4 through the built-in choke; 1000 VDC working; half the area)
  H1-H4      mounting holes M3 (3.2 mm) -> M2 (2.2 mm) (2026-11-10, try 3)
  R302       Q301 collector resistor 100 ohm 0805 -> 1 kohm 2512 (1 W): at 75.6 V and about 22 mA
             it takes about 0.5 W, so Q301 drops from about 1.5 W to about 1.05 W. At 45 V and the
             35 mA peak the collector is still 10 V above V- (datasheet p. 71: >= 6 V). Claude's
             proposal, approved by the user 2026-11-10; a deviation from the datasheet's 100 ohm

Labels sitting on a removed part's pin ends are deleted with it. The Guard file is never
written. Re-run after any Guard schematic change, then:
  kicad-cli sch upgrade --force <lean sch>
  python _tools/kicad_sch/check_slave18s.py --variant lean

usage: python _tools/kicad_sch/make_lean.py [--dry]
"""
import argparse
import re
import sys
import uuid
from pathlib import Path

from kisch import KICAD_CLI, ROOT, load, symbols

GUARD = ROOT / "slave-18s" / "adbms1818-slave-18s.kicad_sch"
LEAN_DIR = ROOT / "slave-18s-lean"
LEAN = LEAN_DIR / "adbms1818-slave-18s-lean.kicad_sch"

REMOVE = ({f"F1{n:02d}" for n in range(21)} | {f"D1{n:02d}" for n in range(1, 19)}
          | {"D301"} | {f"C1{n:02d}" for n in range(1, 19)} | {"J6", "J7"}
          | {f"TP{n}" for n in range(1, 15)})

# F120 (V- supply fuse) becomes the net tie NT1 at the same spot. KiCad keeps CELL0 and V- as
# two nets; on the PCB the net-tie footprint is the only place they may touch.
TIE, TIE_REF = "F120", "NT1"
TIE_FP = "NetTie:NetTie-2_SMD_Pad0.5mm"
TIE_HALF = 2.54          # Device:NetTie_2 pin ends at +-2.54 mm (Device:Fuse: +-3.81 mm)
DEVICE_SYM = Path(KICAD_CLI).parents[1] / "share" / "kicad" / "symbols" / "Device.kicad_sym"


# Lean-only part swaps: ref -> {property: (Guard value, Lean value)}. The Guard value must match,
# so a Guard change can't slip through unnoticed.
R2_1206 = {
    "Value": ("33 1W", "120"),
    "Footprint": ("Resistor_SMD:R_2512_6332Metric", "Resistor_SMD:R_1206_3216Metric"),
    "Description": ("33 ohm 1% 1 W 2512 thick film (Extended)", "120 ohm 1% 250 mW 1206 thick film (Basic)"),
    "LCSC": ("C53728", "C17909"),
    "MPN": ("25121WF330JT4E", "1206W4F1200T5E"),
}
R1_0603 = {
    "Footprint": ("Resistor_SMD:R_1206_3216Metric", "Resistor_SMD:R_0603_1608Metric"),
    "Description": ("10 ohm 1% 250 mW 1206 thick film (Basic)", "10 ohm 1% 100 mW 0603 thick film (Basic)"),
    "LCSC": ("C17903", "C22859"),
    "MPN": ("1206W4F100JT5E", "0603WAF100JT5E"),
}
HOLE_M2 = {
    "Value": ("M3", "M2"),
    "Footprint": ("MountingHole:MountingHole_3.2mm_M3", "MountingHole:MountingHole_2.2mm_M2"),
    "Description": ("Mounting hole 3.2 mm, M3, NPTH, no annular ring", "Mounting hole 2.2 mm, M2, NPTH, no annular ring"),
}
XFMR_BOURNS = {
    "Value": ("HM2113ZNL", "SM91502AL"),
    "Footprint": ("slave18s:Pulse_HM2113ZNL", "slave18s:Bourns_SM91502AL"),
    "Description": ("Pulse BMS transformer 1:1, CT, CMC, 4300 Vrms, 1000 VDC working (Extended)",
                    "Bourns BMS transformer 1:1, CT, CMC, 4300 VDC hi-pot, 1000 VDC working (Extended)"),
    "LCSC": ("C5730533", "C915690"),
    "MPN": ("HM2113ZNLT", "SM91502ALE"),
}
R302_1K = {
    "Value": ("100", "1k 1W"),
    "Footprint": ("Resistor_SMD:R_0805_2012Metric", "Resistor_SMD:R_2512_6332Metric"),
    "Description": ("100 ohm 1% 125 mW 150 V 0805 (Basic)", "1 kohm 1% 1 W 200 V 2512 thick film (Extended)"),
    "LCSC": ("C17408", "C54315"),
    "MPN": ("0805W8F1000T5E", "25121WF1001T4E"),
    "Note": ("Top of stack to NPN collector",
             "Top of stack to NPN collector. 18S Lean: 1 kohm takes ~0.5 W off Q301 at 75.6 V, 22 mA"),
}
SWAP = ({f"R2{n:02d}": R2_1206 for n in range(1, 19)} | {f"R1{n:02d}": R1_0603 for n in range(19)}
        | {"T501": XFMR_BOURNS, "T601": XFMR_BOURNS} | {f"H{n}": HOLE_M2 for n in range(1, 5)} | {"R302": R302_1K})
# R2's Note carries the Guard power figure (which itself ignores the 10 ohm in the loop)
NOTE_SUB = {f"R2{n:02d}": ("~0.4 W at 4.2 V", "~0.12 W at 4.2 V") for n in range(1, 19)}


def swap_part(blk, ref):
    for prop, (old, new) in SWAP[ref].items():
        o = f'(property "{prop}" "{old}"'
        if o not in blk:
            sys.exit(f"{ref}: {o} not found in Guard; update SWAP")
        blk = blk.replace(o, f'(property "{prop}" "{new}"')
    if ref in NOTE_SUB:
        old, new = NOTE_SUB[ref]
        if blk.count(old) != 1:
            sys.exit(f"{ref}: Note text {old!r} not found in Guard; update NOTE_SUB")
        blk = blk.replace(old, new)
    return blk


DROP_TEXT = tuple(f'(text "{h}' for h in ("ZENER CLAMPS", "TAP FUSES", "C101-C118", "SUPPLY FUSES",
                                             "TEST POINTS"))
RETEXT = {
    '"R201-R218: 33 ohm 1 W balance, cell n node (before 10 ohm) to Sn"':
        '"R201-R218: 120 ohm 1206 balance, cell n node (before 10 ohm) to Sn"',
    '"MOUNTING HOLES  H1-H4: M3, no copper': '"MOUNTING HOLES  H1-H4: M2, no copper',
    '"ADBMS1818 18S slave module"': '"ADBMS1818 18S slave module - Lean (no hot-plug protection)"',
    "TAPn = connector side of fuse F1nn, CELLn = after it. V- (chip ground) has its own fuse F120.":
        "18S Lean: no fuses, clamps or C-pin caps; generated from slave-18s by make_lean.py, do not edit by hand. "
        "C0 sense (CELL0, J1.1) and V- meet only at net tie NT1, which replaces F120.",
}


def rename(name):
    m = re.fullmatch(r"TAP(\d+)", name)
    if m:
        name = f"CELL{m.group(1)}"
    return {"VBAT_F": "CELL18"}.get(name, name)


def tie_symbol(blk):
    """F120's symbol block -> NT1 (Device:NetTie_2, turned vertical like F120)."""
    new_id = lambda m: f'(uuid "{uuid.uuid5(uuid.NAMESPACE_URL, m.group(1) + TIE_REF)}")'
    blk = re.sub(r'\(uuid "([^"]+)"\)', new_id, blk)
    blk = blk.replace('(lib_id "Device:Fuse")', '(lib_id "Device:NetTie_2")')
    blk = re.sub(r"^(\t\t\(at [-\d.]+ [-\d.]+) 0\)", r"\1 270)", blk, count=1, flags=re.M)
    for k in ("in_bom", "in_pos_files"):
        blk = blk.replace(f"({k} yes)", f"({k} no)")
    # Reference/Value: field angles are relative to the symbol, 90 reads horizontally at 270
    blk = re.sub(r'(\(property "(?:Reference|Value)" "[^"]*"\s*\(at [-\d.]+ [-\d.]+) 0\)', r"\1 90)", blk)
    for old, new in ((f'"Reference" "{TIE}"', f'"Reference" "{TIE_REF}"'),
                     (f'(reference "{TIE}")', f'(reference "{TIE_REF}")'),
                     ('"Value" "250mA"', '"Value" "NetTie_2"'),
                     ('"Footprint" "Fuse:Fuse_1206_3216Metric"', f'"Footprint" "{TIE_FP}"')):
        if old not in blk:
            sys.exit(f"{TIE}: {old} not found")
        blk = blk.replace(old, new)
    blk = re.sub(r'"Description" "[^"]*"', '"Description" "Net tie: CELL0 (C0 sense, J1.1) to V-. '
                 'Place next to J1.1; the only copper where the two nets meet"', blk)
    blk = re.sub(r'"Note" "[^"]*"', '"Note" "18S Lean: replaces the V- supply fuse F120"', blk)
    blk = re.sub(r'\n\t\t\(property "(?:LCSC|MPN)" "[^"]*".*?\n\t\t\)', "", blk, flags=re.S)
    return blk


def nettie_lib():
    """Device:NetTie_2 from KiCad's own library, named as lib_symbols needs it."""
    lib = DEVICE_SYM.read_text(encoding="utf-8")
    i = lib.index('\n\t(symbol "NetTie_2"')
    j = lib.index('\n\t(symbol "', i + 5)
    return lib[i:j].replace('(symbol "NetTie_2"', '(symbol "Device:NetTie_2"', 1).replace("\n", "\n\t")


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
    dead_ends = {(round(p["ex"], 2), round(p["ey"], 2)) for r in REMOVE - {TIE}
                 for p in syms[r]["pins"].values()}
    f = syms[TIE]
    if f["rot"] or f["mirror"] or f["lib_id"] != "Device:Fuse":
        sys.exit(f"{TIE} is no longer an unrotated Device:Fuse; update tie_symbol()")
    # labels on F120's pin ends move onto NT1's (shorter) pins, same side
    tie_moves = {(round(p["ex"], 2), round(p["ey"], 2)):
                 (f["x"], round(f["y"] + TIE_HALF * (1 if p["ey"] > f["y"] else -1), 2))
                 for p in f["pins"].values()}

    out, last, gone = [], 0, {"symbol": 0, "label": 0, "wire": 0, "text": 0}
    for s, e, head in top_blocks(text):
        blk = text[s:e]
        drop = False
        if head == "symbol":
            m = re.search(r'\(property "Reference" "([^"]+)"', blk)
            if m and m.group(1) == TIE:
                out.append(text[last:s]); out.append(tie_symbol(blk)); last = e
                continue
            drop = bool(m and m.group(1) in REMOVE)
            if m and m.group(1) in SWAP:
                out.append(text[last:s]); out.append(swap_part(blk, m.group(1))); last = e
                gone["swapped"] = gone.get("swapped", 0) + 1
                continue
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
            m = re.search(r"\(at ([-\d.]+) ([-\d.]+)", blk2)
            to = tie_moves.get((round(float(m.group(1)), 2), round(float(m.group(2)), 2)))
            if to:
                blk2 = blk2[:m.start()] + f"(at {to[0]:g} {to[1]:g}" + blk2[m.end():]
                gone["tie label moved"] = gone.get("tie label moved", 0) + 1
            if blk2 != blk:
                out.append(text[last:s]); out.append(blk2); last = e
    out.append(text[last:])
    lean = "".join(out).replace('(project "adbms1818-slave-18s"', '(project "adbms1818-slave-18s-lean"')
    if '(symbol "Device:NetTie_2"' not in lean:
        k = lean.index("(lib_symbols") + len("(lib_symbols")
        lean = lean[:k] + nettie_lib() + lean[k:]

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
