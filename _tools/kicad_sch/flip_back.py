"""Flip footprints to the back side (B.Cu) in place, keeping each one's position (2026-11-09).

Lean puts every test point (bare 1.5 mm pads) on the back so the front keeps its room for the
circuit. A flip changes the footprint's layer, its pad and graphic layers and mirrors its text,
so it goes through pcbnew (KiCad's own Flip) instead of a one-line text edit. Footprints that
are already on the back are left alone, so running it twice changes nothing.

  "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" _tools/kicad_sch/flip_back.py [--variant lean | --pcb FILE] REF... | --test-points

pcbnew does the flip and saves a temporary copy; only the flipped footprints' blocks are taken
from it and spliced into the board file (LF line endings kept), so the diff is those parts alone.
Close KiCad first.
"""
import argparse
import re
import sys
import uuid
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kisch import VARIANTS  # noqa: E402


def flip_to_back(pcb, refs):
    """Flip REFS (or every TP<n> if refs is None) to B.Cu; returns (flipped, already_back, missing)."""
    board = pcbnew.LoadBoard(str(pcb))
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    if refs is None:
        refs = sorted((r for r in fps if re.fullmatch(r"TP\d+", r)), key=lambda r: int(r[2:]))
    flipped, back, missing = [], [], []
    for r in refs:
        fp = fps.get(r)
        if fp is None:
            missing.append(r)
        elif fp.GetLayer() == pcbnew.B_Cu:
            back.append(r)
        else:
            try:
                fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
            except AttributeError:      # older API: Flip(centre, flip_left_right: bool)
                fp.Flip(fp.GetPosition(), True)
            flipped.append(r)
    if flipped:
        tmp = pcb.with_name(pcb.stem + ".flip.tmp")
        pcbnew.SaveBoard(str(tmp), board)
        new = tmp.read_text(encoding="utf-8").replace("\r\n", "\n")
        tmp.unlink()
        for stray in (tmp.with_suffix('.kicad_pro'), tmp.with_suffix('.kicad_prl')):   # pcbnew writes a project beside the copy
            stray.unlink(missing_ok=True)
        splice(pcb, new, set(flipped))
    return flipped, back, missing


def blocks(text):
    """{ref: (start, end)} of each top-level footprint block."""
    out = {}
    for m0 in re.finditer(r"^\t\(footprint ", text, re.M):
        s = m0.start()
        e = close_of(text, s)       # not "up to the next footprint": the last one would swallow the file's tail
        m = re.search(r'\(property "Reference" "([^"]+)"', text[s:e])
        out[m.group(1)] = (s, e)
    return out


def close_of(text, s):
    """Index just past the ')' (and its newline) that closes the s-expression starting at TEXT[s]."""
    depth, i, n = 0, s, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 2 if text[i + 1:i + 2] == "\n" else i + 1
        i += 1
    raise ValueError("unbalanced footprint block")


def splice(pcb, new_text, refs):
    """Put the flipped footprint blocks of NEW_TEXT into the board file; nothing else changes
    (pcbnew re-formats the whole file, which would bury the flip in a 5000-line diff)."""
    old = pcb.read_text(encoding="utf-8").replace("\r\n", "\n")
    ob, nb = blocks(old), blocks(new_text)
    keep = [old[s:e] for r, (s, e) in ob.items() if r not in refs]
    taken = set(re.findall(r'\(uuid "([^"]+)"', old[:min(s for s, _ in ob.values())] + "".join(keep)))
    out, last = [], 0
    for ref in sorted(refs, key=lambda r: ob[r][0]):
        s, e = ob[ref]
        blk = new_text[nb[ref][0]:nb[ref][1]]
        # pcbnew hands a footprint's uuid-less items ids that another part already owns; KiCad then
        # drops the later duplicates when it loads the board (9 parts vanished in a first try)
        def fresh(m):
            if m.group(1) in taken:
                return f'(uuid "{uuid.uuid4()}")'
            taken.add(m.group(1))
            return m.group(0)
        blk = re.sub(r'\(uuid "([^"]+)"\)', fresh, blk)
        out.append(old[last:s])
        out.append(blk)
        last = e
    out.append(old[last:])
    pcb.write_text("".join(out), encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("refs", nargs="*")
    ap.add_argument("--test-points", action="store_true", help="every TP<n> footprint")
    ap.add_argument("--pcb", help="board file (default: the Lean board)")
    a = ap.parse_args()
    if not a.refs and not a.test_points:
        sys.exit("give REFs or --test-points")
    pcb = Path(a.pcb) if a.pcb else VARIANTS["lean"].with_suffix(".kicad_pcb")
    if list(pcb.parent.glob("~*.lck")):
        sys.exit("KiCad has the board open (lock file). Close it first.")
    flipped, back, missing = flip_to_back(pcb, None if a.test_points else a.refs)
    print(f"flipped to the back: {', '.join(flipped) or '-'}; already on the back: {len(back)}"
          + (f"; NOT FOUND: {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
