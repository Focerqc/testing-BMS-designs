"""
KiCad bridge for the PCB Dashboard.
Runs under KiCad's bundled Python (needs pcbnew).

  python kicad_bridge.py read  <board.kicad_pcb>                -> JSON on stdout
  python kicad_bridge.py apply <board.kicad_pcb> <changes.json> -> JSON on stdout

changes.json: {"changes": [{"uuid": "...", "x": mm, "y": mm, "rot": deg}, ...]}
"""
import json
import os
import re
import shutil
import sys
import time

import pcbnew

KICAD_SHARE = r"C:\Program Files\KiCad\10.0\share\kicad"
STOCK_3D_DIR = os.path.join(KICAD_SHARE, "3dmodels")


def mm(v):
    return round(pcbnew.ToMM(v), 4)


def pt(p):
    return [mm(p.x), mm(p.y)]


def resolve_model_path(raw, project_dir):
    path = raw
    # Any KICADn_3DMODEL_DIR / KICAD_3DMODEL_DIR -> stock KiCad 10 model dir
    path = re.sub(r"\$\{KICAD\d*_3DMODEL_DIR\}", STOCK_3D_DIR.replace("\\", "/"), path)
    path = path.replace("${KIPRJMOD}", project_dir.replace("\\", "/"))
    path = os.path.expandvars(path)
    if not os.path.isabs(path):
        path = os.path.join(project_dir, path)
    return os.path.normpath(path)


def model_info(fp, project_dir):
    models = []
    for m in fp.Models():
        raw = m.m_Filename
        resolved = resolve_model_path(raw, project_dir)
        exists = os.path.isfile(resolved)
        alt = None
        if not exists:
            base, ext = os.path.splitext(resolved)
            for alt_ext in (".step", ".stp", ".wrl"):
                if alt_ext != ext.lower() and os.path.isfile(base + alt_ext):
                    alt = base + alt_ext
                    break
        models.append({
            "path": raw,
            "resolved": resolved,
            "exists": exists,
            "alt_exists": alt,
            "visible": bool(getattr(m, "m_Show", True)),
        })
    return models


def shape_segments(item):
    """Return list of polylines (each a list of [x,y]) in absolute board mm."""
    st = item.GetShape()
    try:
        if st == pcbnew.SHAPE_T_SEGMENT:
            return [[pt(item.GetStart()), pt(item.GetEnd())]]
        if st == pcbnew.SHAPE_T_RECT:
            corners = [pt(c) for c in item.GetRectCorners()]
            return [corners + [corners[0]]]
        if st == pcbnew.SHAPE_T_POLY:
            ps = item.GetPolyShape()
            out = []
            for i in range(ps.OutlineCount()):
                ol = ps.COutline(i)
                pts = [pt(ol.CPoint(j)) for j in range(ol.PointCount())]
                if pts:
                    out.append(pts + [pts[0]])
            return out
        if st == pcbnew.SHAPE_T_CIRCLE:
            c = item.GetCenter()
            r = item.GetRadius()
            import math
            pts = []
            for k in range(25):
                a = 2 * math.pi * k / 24
                pts.append([mm(c.x + r * math.cos(a)), mm(c.y + r * math.sin(a))])
            return [pts]
        if st == pcbnew.SHAPE_T_ARC:
            return [[pt(item.GetStart()), pt(item.GetArcMid()), pt(item.GetEnd())]]
    except Exception:
        pass
    return []


PAD_SHAPES = {
    getattr(pcbnew, "PAD_SHAPE_RECT", -1): "rect",
    getattr(pcbnew, "PAD_SHAPE_CIRCLE", -2): "circle",
    getattr(pcbnew, "PAD_SHAPE_OVAL", -3): "oval",
    getattr(pcbnew, "PAD_SHAPE_ROUNDRECT", -4): "roundrect",
    getattr(pcbnew, "PAD_SHAPE_TRAPEZOID", -5): "rect",
    getattr(pcbnew, "PAD_SHAPE_CHAMFERED_RECT", -6): "roundrect",
    getattr(pcbnew, "PAD_SHAPE_CUSTOM", -7): "rect",
}


def pad_info(pad):
    try:
        shape = PAD_SHAPES.get(pad.GetShape(pcbnew.F_Cu), "rect")
    except TypeError:
        shape = PAD_SHAPES.get(pad.GetShape(), "rect")
    try:
        size = pad.GetSize(pcbnew.F_Cu)
    except TypeError:
        size = pad.GetSize()
    return {
        "num": pad.GetNumber(),
        "x": mm(pad.GetPosition().x),
        "y": mm(pad.GetPosition().y),
        "w": mm(size.x),
        "h": mm(size.y),
        "angle": round(pad.GetOrientationDegrees(), 3),
        "shape": shape,
        "tht": pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH,
        "net": pad.GetNetname(),
    }


def field_value(fp, name):
    try:
        for f in fp.GetFields():
            if f.GetName().lower() == name.lower():
                return f.GetText()
    except Exception:
        pass
    return ""


def read_board(pcb_path):
    board = pcbnew.LoadBoard(pcb_path)
    project_dir = os.path.dirname(os.path.abspath(pcb_path))
    fab_layers = {pcbnew.F_Fab, pcbnew.B_Fab}
    crt_layers = {pcbnew.F_CrtYd, pcbnew.B_CrtYd}

    footprints = []
    for fp in board.GetFootprints():
        fab, crt = [], []
        for item in fp.GraphicalItems():
            if not isinstance(item, pcbnew.PCB_SHAPE):
                continue
            layer = item.GetLayer()
            if layer in fab_layers:
                fab.extend(shape_segments(item))
            elif layer in crt_layers:
                crt.extend(shape_segments(item))

        pos = fp.GetPosition()
        footprints.append({
            "uuid": fp.m_Uuid.AsString(),
            "ref": fp.GetReference(),
            "value": fp.GetValue(),
            "fpid": str(fp.GetFPID().GetUniStringLibId()),
            "x": mm(pos.x),
            "y": mm(pos.y),
            "rot": round(fp.GetOrientationDegrees(), 3),
            "side": "B" if fp.GetLayer() == pcbnew.B_Cu else "F",
            "locked": fp.IsLocked(),
            "pads": [pad_info(p) for p in fp.Pads()],
            "outline": fab if fab else crt,
            "models": model_info(fp, project_dir),
            "lcsc": field_value(fp, "LCSC") or field_value(fp, "LCSC Part") or field_value(fp, "JLCPCB"),
            "mpn": field_value(fp, "MPN") or field_value(fp, "Manufacturer Part Number"),
        })

    edges = []
    for d in board.GetDrawings():
        if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayer() == pcbnew.Edge_Cuts:
            edges.extend(shape_segments(d))

    tracks = []
    vias = []
    for t in board.GetTracks():
        sp = t.GetStart()
        ep = t.GetEnd()
        layer = board.GetLayerName(t.GetLayer())
        if isinstance(t, pcbnew.PCB_VIA):
            drill = mm(t.GetDrill())
            try:
                width = mm(t.GetWidth(pcbnew.F_Cu))
            except TypeError:
                width = mm(t.GetWidth())
            vias.append({
                "x": mm(sp.x),
                "y": mm(sp.y),
                "drill": drill,
                "width": width,
                "net": t.GetNetname()
            })
        else:
            try:
                w = mm(t.GetWidth())
            except TypeError:
                w = 0.2
            tracks.append({
                "layer": layer,
                "x1": mm(sp.x),
                "y1": mm(sp.y),
                "x2": mm(ep.x),
                "y2": mm(ep.y),
                "w": w,
                "net": t.GetNetname()
            })

    bbox = board.GetBoardEdgesBoundingBox()
    return {
        "path": pcb_path,
        "mtime": os.path.getmtime(pcb_path),
        "edges": edges,
        "bbox": {"x": mm(bbox.GetX()), "y": mm(bbox.GetY()), "w": mm(bbox.GetWidth()), "h": mm(bbox.GetHeight())},
        "footprints": footprints,
        "tracks": tracks,
        "vias": vias,
    }


def apply_changes(pcb_path, changes_path):
    with open(changes_path, "r", encoding="utf-8") as f:
        changes = json.load(f)["changes"]

    project_dir = os.path.dirname(os.path.abspath(pcb_path))
    backup_dir = os.path.join(project_dir, ".dashboard_backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(backup_dir, f"{os.path.splitext(os.path.basename(pcb_path))[0]}.{stamp}.kicad_pcb")
    shutil.copy2(pcb_path, backup)

    board = pcbnew.LoadBoard(pcb_path)
    by_uuid = {fp.m_Uuid.AsString(): fp for fp in board.GetFootprints()}
    applied, missing = [], []
    for ch in changes:
        fp = by_uuid.get(ch["uuid"])
        if fp is None:
            missing.append(ch.get("ref", ch["uuid"]))
            continue
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(float(ch["x"])), pcbnew.FromMM(float(ch["y"]))))
        fp.SetOrientationDegrees(float(ch["rot"]))
        applied.append(fp.GetReference())

    pcbnew.SaveBoard(pcb_path, board)
    return {"status": "ok", "applied": applied, "missing": missing, "backup": backup}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "read":
        result = read_board(sys.argv[2])
    elif cmd == "apply":
        result = apply_changes(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(f"unknown command {cmd}")
    sys.stdout.write("@@JSON@@" + json.dumps(result))
