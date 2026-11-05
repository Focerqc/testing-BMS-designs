#!/usr/bin/env python3
"""
PCB Dashboard server.
Serves the UI and talks to KiCad through kicad_bridge.py (run with KiCad's own Python).

  python server.py            -> http://localhost:5180
"""
import datetime
import hashlib
import http.server
import json
import mimetypes
import os
import socketserver
import subprocess
import urllib.parse
from PIL import Image
from pypdf import PdfReader, PdfWriter
import tempfile

PORT = int(os.environ.get("DASHBOARD_PORT", "5180"))
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TOOL_DIR, "..", ".."))
KICAD_PYTHON = r"C:\Program Files\KiCad\10.0\bin\python.exe"
KICAD_CLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
BRIDGE = os.path.join(TOOL_DIR, "kicad_bridge.py")
SKIP_DIRS = {"site", "racc", ".git", ".history", "node_modules", ".dashboard_backups", "__pycache__"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

_board_cache = {}  # abs_path -> (mtime, data)


def render_3d_file(board_full, kind="top"):
    suffix = "_3d_iso.png" if kind == "iso" else "_3d_top.png"
    return os.path.splitext(board_full)[0] + suffix


def crop_render_png(out_png, kind="top", force=False):
    """Trim transparent margins so the board fills the image.
    Old kicad-cli renders often keep huge empty borders; stretching those
    to the board outline makes the PCB look tiny / off-center in the UI."""
    try:
        im = Image.open(out_png)
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        bbox = im.getbbox()
        if not bbox:
            return False
        w, h = im.size
        pad = 20 if kind == "iso" else 0
        margins = (bbox[0], bbox[1], w - bbox[2], h - bbox[3])
        # Skip rewrite when already tight (top) or already padded (iso).
        if not force:
            if kind == "top" and max(margins) <= 1:
                return False
            if kind == "iso" and max(margins) <= pad + 1 and min(margins) >= max(0, pad - 2):
                return False
        crop_box = (
            max(0, bbox[0] - pad),
            max(0, bbox[1] - pad),
            min(w, bbox[2] + pad),
            min(h, bbox[3] + pad),
        )
        if crop_box == (0, 0, w, h):
            return False
        im.crop(crop_box).save(out_png)
        return True
    except Exception as e:
        print(f"PIL crop warning: {e}")
        return False


def render_status_entry(out_png, kind):
    if not os.path.isfile(out_png):
        return {"exists": False, "kind": kind} if kind else {"exists": False}
    # Normalize legacy uncropped renders the first time they're opened.
    crop_render_png(out_png, kind=kind)
    mtime = os.path.getmtime(out_png)
    entry = {
        "exists": True,
        "image": rel(out_png),
        "timestamp": datetime.datetime.fromtimestamp(mtime).strftime("%b %d, %I:%M:%S %p"),
        "mtime": mtime,
    }
    if kind:
        entry["kind"] = kind
    return entry


def render_board_3d(board_full, kind="top"):
    if not os.path.isfile(board_full):
        raise FileNotFoundError(f"Board file not found: {board_full}")
    out_png = render_3d_file(board_full, kind=kind)
    if kind == "iso":
        cmd = [
            KICAD_CLI, "pcb", "render",
            "--rotate", "-45,0,45",
            "--width", "4000",
            "--height", "2600",
            "--background", "transparent",
            "-o", out_png,
            board_full
        ]
    else:
        cmd = [
            KICAD_CLI, "pcb", "render",
            "--side", "top",
            "--width", "4000",
            "--height", "2000",
            "--background", "transparent",
            "-o", out_png,
            board_full
        ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0 or not os.path.isfile(out_png):
        raise RuntimeError(f"kicad-cli render failed: {res.stderr or res.stdout}")

    crop_render_png(out_png, kind=kind, force=True)

    mtime = os.path.getmtime(out_png)
    dt = datetime.datetime.fromtimestamp(mtime)
    timestamp_str = dt.strftime("%b %d, %I:%M:%S %p")
    return {
        "status": "ok",
        "kind": kind,
        "image": rel(out_png),
        "timestamp": timestamp_str,
        "mtime": mtime
    }


def schematic_pdf_file(board_full):
    key = hashlib.sha256(os.path.abspath(board_full).encode("utf-8")).hexdigest()[:12]
    return os.path.join(REPO_ROOT, "exports", f"schematic-preview-{key}.pdf")


def render_schematic(board_full):
    if not board_full.lower().endswith(".kicad_pcb"):
        raise ValueError("path must be a .kicad_pcb")
    schematic = os.path.splitext(board_full)[0] + ".kicad_sch"
    if not os.path.isfile(schematic):
        raise FileNotFoundError(f"Matching schematic not found: {rel(schematic)}")
    out_pdf = schematic_pdf_file(board_full)
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    res = subprocess.run(
        [KICAD_CLI, "sch", "export", "pdf", "--output", out_pdf, schematic],
        capture_output=True, text=True, timeout=120,
    )
    if res.returncode != 0 or not os.path.isfile(out_pdf):
        raise RuntimeError(f"kicad-cli schematic export failed: {res.stderr or res.stdout}")
    return {"status": "ok", "pdf": rel(out_pdf), "timestamp": datetime.datetime.fromtimestamp(os.path.getmtime(out_pdf)).strftime("%b %d, %I:%M:%S %p")}


def full_schematic_pdf_file(board_full):
    key = hashlib.sha256(os.path.abspath(board_full).encode("utf-8")).hexdigest()[:12]
    return os.path.join(REPO_ROOT, "exports", f"full-system-schematic-{key}.pdf")


def render_full_schematic(board_full):
    """Export the board's own schematic (all hierarchical sheets) to one PDF."""
    if not board_full.lower().endswith(".kicad_pcb"):
        raise ValueError("path must be a .kicad_pcb")
    schematic = os.path.splitext(board_full)[0] + ".kicad_sch"
    if not os.path.isfile(schematic):
        raise FileNotFoundError("No schematic matches this board")
    output_pdf = full_schematic_pdf_file(board_full)
    os.makedirs(os.path.dirname(output_pdf), exist_ok=True)
    result = subprocess.run([KICAD_CLI, "sch", "export", "pdf", "--output", output_pdf, schematic],
                            capture_output=True, text=True, timeout=120)
    if result.returncode or not os.path.isfile(output_pdf):
        raise RuntimeError(f"Schematic export failed: {result.stderr or result.stdout}")
    return {"status": "ok", "pdf": rel(output_pdf), "pages": len(PdfReader(output_pdf).pages),
            "timestamp": datetime.datetime.fromtimestamp(os.path.getmtime(output_pdf)).strftime("%b %d, %I:%M:%S %p")}


def get_render_3d_status(board_full, kind=None):
    if kind in ("top", "iso"):
        return render_status_entry(render_3d_file(board_full, kind=kind), kind)
    top_png = render_3d_file(board_full, "top")
    iso_png = render_3d_file(board_full, "iso")
    res = {
        "top": render_status_entry(top_png, "top"),
        "iso": render_status_entry(iso_png, "iso"),
    }
    # Nested entries historically omit kind; keep that shape for the UI.
    res["top"].pop("kind", None)
    res["iso"].pop("kind", None)
    res["exists"] = res["top"]["exists"]
    res["image"] = res["top"].get("image")
    res["timestamp"] = res["top"].get("timestamp")
    res["mtime"] = res["top"].get("mtime")
    return res


def safe_path(rel):
    rel = urllib.parse.unquote(rel or "").lstrip("/\\")
    full = os.path.normpath(os.path.join(REPO_ROOT, rel))
    if not full.startswith(REPO_ROOT):
        raise PermissionError("path outside repo")
    return full


def rel(full):
    return os.path.relpath(full, REPO_ROOT).replace("\\", "/")


def walk_files(exts):
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if os.path.splitext(f)[1].lower() in exts:
                yield os.path.join(root, f)


def run_bridge(*args):
    proc = subprocess.run(
        [KICAD_PYTHON, BRIDGE, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    out = proc.stdout
    idx = out.find("@@JSON@@")
    if idx < 0:
        raise RuntimeError((proc.stderr or out or "bridge failed")[-2000:])
    return json.loads(out[idx + len("@@JSON@@"):])


def boxes_file(board_full):
    return os.path.splitext(board_full)[0] + ".boxes.json"


def read_board(full):
    mtime = os.path.getmtime(full)
    cached = _board_cache.get(full)
    if cached and cached[0] == mtime:
        return cached[1]
    data = run_bridge("read", full)
    data["path"] = rel(full)
    _board_cache[full] = (mtime, data)
    return data


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=TOOL_DIR, **kw)

    def log_message(self, fmt, *args):
        try:
            msg = fmt % args
        except Exception:
            msg = str(fmt)
        if "/api/" in msg:
            super().log_message(fmt, *args)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/api/boards":
                boards = sorted(rel(p) for p in walk_files({".kicad_pcb"}))
                boards.sort(key=lambda b: (0 if "slave" in b.lower() else 1, b))
                return self.send_json(boards)

            if u.path == "/api/images":
                imgs = []
                for p in walk_files(IMAGE_EXTS):
                    norm = rel(p).lower()
                    if "_3d_top" in norm or "_3d_iso" in norm or "_3d_bottom" in norm or "/scratch/" in norm or norm.startswith("scratch/") or "test_" in norm or ".tempmediastorage" in norm:
                        continue
                    imgs.append({"path": rel(p), "name": os.path.basename(p),
                                 "kb": round(os.path.getsize(p) / 1024)})
                imgs.sort(key=lambda i: ("_reference" not in i["path"], i["path"]))
                return self.send_json(imgs)

            if u.path == "/api/board":
                full = safe_path(q.get("path", [""])[0])
                return self.send_json(read_board(full))

            if u.path == "/api/boxes":
                bf = boxes_file(safe_path(q.get("path", [""])[0]))
                if not os.path.isfile(bf):
                    return self.send_json({"exists": False})
                with open(bf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["exists"] = True
                return self.send_json(data)

            if u.path == "/api/render_status":
                full = safe_path(q.get("path", [""])[0])
                kind = q.get("kind", [None])[0]
                return self.send_json(get_render_3d_status(full, kind=kind))

            if u.path == "/api/render_3d":
                full = safe_path(q.get("path", [""])[0])
                kind = q.get("kind", ["top"])[0]
                return self.send_json(render_board_3d(full, kind=kind))

            if u.path == "/api/schematic_pdf":
                full = safe_path(q.get("path", [""])[0])
                if not full.lower().endswith(".kicad_pcb"):
                    raise ValueError("path must be a .kicad_pcb")
                pdf = schematic_pdf_file(full)
                if not os.path.isfile(pdf):
                    return self.send_error(404)
                with open(pdf, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", "inline; filename=schematic-preview.pdf")
                self.end_headers()
                self.wfile.write(data)
                return

            if u.path == "/api/full_schematic_pdf":
                full = safe_path(q.get("path", [""])[0])
                if not full.lower().endswith(".kicad_pcb"):
                    raise ValueError("path must be a .kicad_pcb")
                pdf = full_schematic_pdf_file(full)
                if not os.path.isfile(pdf):
                    return self.send_error(404)
                with open(pdf, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", "inline; filename=full-schematic.pdf")
                self.end_headers()
                self.wfile.write(data)
                return

            if u.path == "/api/image":
                full = safe_path(q.get("path", [""])[0])
                if not os.path.isfile(full):
                    return self.send_error(404)
                mime = mimetypes.guess_type(full)[0] or "application/octet-stream"
                with open(full, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": str(e)}, 500)

        if u.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            if u.path == "/api/render_schematic":
                full = safe_path(q.get("path", [""])[0])
                return self.send_json(render_schematic(full))

            if u.path == "/api/render_full_schematic":
                full = safe_path(q.get("path", [""])[0])
                return self.send_json(render_full_schematic(full))

            if u.path == "/api/render_3d":
                full = safe_path(q.get("path", [""])[0])
                kind = q.get("kind", ["top"])[0]
                return self.send_json(render_board_3d(full, kind=kind))

            if u.path == "/api/boxes":
                full = safe_path(q.get("path", [""])[0])
                if not full.lower().endswith(".kicad_pcb"):
                    raise ValueError("path must be a .kicad_pcb")
                bf = boxes_file(full)
                payload.pop("exists", None)
                payload["board"] = rel(full)
                tmp = bf + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=1)
                os.replace(tmp, bf)
                return self.send_json({"status": "ok", "file": rel(bf)})
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": str(e)}, 500)
        self.send_error(404)


def main():
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"PCB Dashboard -> http://localhost:{PORT}   (repo: {REPO_ROOT})")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
