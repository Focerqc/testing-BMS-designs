"""Export the Board Boxes UI and a read-only snapshot of every board in the repo for Pages."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
UI = Path(__file__).resolve().parent
SITE = ROOT / 'site'
DATA = SITE / 'data'
DATA.mkdir(exist_ok=True)

def write_json(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')

assets = {}
def asset(relative):
    if relative in assets:
        return assets[relative]
    source = ROOT / relative
    # Named by content, not path: a new render gets a new URL, so no browser shows a cached old one.
    name = hashlib.sha256(source.read_bytes()).hexdigest()[:12] + source.suffix
    shutil.copyfile(source, DATA / name)
    assets[relative] = 'data/' + name
    return assets[relative]

boards = {}
SKIP = {'site', 'exports', '_reference', '.git', '.history'}
board_files = sorted(p for p in ROOT.rglob('*.kicad_pcb') if not (SKIP & set(p.relative_to(ROOT).parts)))
KICAD_CLI = r'C:\Program Files\KiCad\10.0\bin\kicad-cli.exe'
for source in board_files:
    relative = source.relative_to(ROOT).as_posix()
    result = subprocess.run([r'C:\Program Files\KiCad\10.0\bin\python.exe', str(UI / 'kicad_bridge.py'), 'read', str(source)], capture_output=True, text=True, encoding='utf-8', check=True)
    board = json.loads(result.stdout.split('@@JSON@@', 1)[1])
    board['path'] = relative
    # Machine-specific model resolution paths are not needed in a public snapshot.
    def sanitize(value):
        if isinstance(value, dict):
            for key in ['resolved', 'alt_exists']:
                value.pop(key, None)
            for child in value.values():
                sanitize(child)
        elif isinstance(value, list):
            for child in value:
                sanitize(child)
    sanitize(board)
    boxfile = source.with_suffix('.boxes.json')
    boxes = json.loads(boxfile.read_text(encoding='utf-8')) if boxfile.exists() else {}
    boxes['exists'] = boxfile.exists()
    renders = {}
    for kind in ['top', 'iso']:
        render = source.with_name(source.stem + '_3d_' + kind + '.png')
        entry = {'exists': render.exists()}
        if render.exists():
            image = render.relative_to(ROOT).as_posix()
            asset(image)
            # Stable copy for the News page (data/ names are content hashes and change).
            (SITE / 'files').mkdir(exist_ok=True)
            shutil.copyfile(render, SITE / 'files' / (source.stem + '-3d-' + kind + '.png'))
            entry.update(image=image, timestamp=datetime.datetime.fromtimestamp(render.stat().st_mtime).strftime('%b %d, %Y %H:%M'))
        renders[kind] = entry
    boards[relative] = dict(board=board, boxes=boxes, renders=renders)

    # Schematic PDF per board, published next to the snapshot.
    schematic = source.with_suffix('.kicad_sch')
    if schematic.exists():
        FILES = SITE / 'files'; FILES.mkdir(exist_ok=True)
        pdf = FILES / (source.stem + '-schematic.pdf')
        subprocess.run([KICAD_CLI, 'sch', 'export', 'pdf', '-o', str(pdf), str(schematic)], check=True, capture_output=True)
        from pypdf import PdfReader
        boards[relative]['schematic'] = dict(pdf='files/' + pdf.name, pages=len(PdfReader(pdf).pages),
                                             timestamp=datetime.datetime.now().strftime('%B %d, %Y'))

# Public snapshot: no reference photos are published (private material stays local).
images = []
write_json(DATA / 'dashboard.json', dict(boards=boards, images=images, assets=assets))
# Content-named data files leave the previous export's copies behind; drop the ones no longer used.
used = {Path(p).name for p in assets.values()} | {'dashboard.json'}
for stale in DATA.iterdir():
    if stale.is_file() and stale.name not in used:
        stale.unlink()

shutil.copyfile(UI / 'style.css', SITE / 'style.css')
js = (UI / 'app.js').read_text(encoding='utf-8')
js = js.replace("'use strict';", "'use strict';\n  const fetch = window.dashboardFetch;")
js = re.sub(r'`/api/image\?path=\$\{encodeURIComponent\((\w+)\)\}(?:&t=\$\{Date.now\(\)\})?`', r'window.dashboardAsset(\1)', js)
js = js.replace('`/api/${pdfEndpoint}?path=${encodeURIComponent(S.boardPath)}&t=${Date.now()}`', 'window.dashboardSchematic(S.boardPath)')
js = js.replace('`/api/image?path=${encodeURIComponent(S.renderIsoPath)}&t=${Date.now()}`', 'window.dashboardAsset(S.renderIsoPath)')
js = js.replace('`saved · ${res.file.split(\'/\').pop()}`', "'saved in this browser'")
js = js.replace('with KiCad… (first load can take ~10 s)', 'from published snapshot…')
js = js.replace('Rendered ${res.timestamp}', 'Published snapshot · ${res.timestamp}')
(SITE / 'app.js').write_text(js, encoding='utf-8')

html = (UI / 'index.html').read_text(encoding='utf-8')
html = html.replace('<div class="actions">', '<div class="actions"><a class="btn btn-ghost btn-sm" href="news.html">News</a>')
html = html.replace('Testing BMS designs</small>', 'Testing BMS designs · published snapshot · saved in this browser</small>')
html = html.replace('<script src="app.js', '<script src="hosted.js"></script>\n  <script src="app.js')
# Pages lets browsers cache files for 10 minutes. With a hand-kept ?v= that didn't change, the live
# site kept running the old app.js after a re-export (2026-11-08: the Lean render was drawn by the
# pre-fix code). A hash of each published file makes every change a new URL.
for name in ['style.css', 'hosted.js', 'app.js']:
    digest = hashlib.sha256((SITE / name).read_bytes()).hexdigest()[:10]
    html, count = re.subn(r'"' + re.escape(name) + r'(\?v=[^"]*)?"', f'"{name}?v={digest}"', html)
    assert count == 1, f'index.html should load {name} once, found {count}'
(SITE / 'index.html').write_text(html, encoding='utf-8')
print('Exported', len(boards), 'boards and', len(assets), 'assets')
