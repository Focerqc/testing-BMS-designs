"""Per-part purpose and possible issues for Board Boxes Info mode.

The text lives in part_notes.json next to this file. Both the local server
and the public snapshot export call notes_for_board(), so the two stay the same.
"""
import json
import re
from pathlib import Path

NOTES_FILE = Path(__file__).with_name('part_notes.json')
_cache = None


def _load():
    global _cache
    if _cache is None:
        _cache = json.loads(NOTES_FILE.read_text(encoding='utf-8'))
    return _cache


def variant_for(board_path):
    """Which note list applies to a board file, judged by its name."""
    name = Path(str(board_path)).name.lower()
    if 'lean' in name:
        return 'lean'
    if name.startswith('adbms1818-slave-18s'):
        return 'guard'
    return None


def notes_for_board(board_path, refs):
    """Map each reference designator on the board to {purpose, issues}.

    The board's own variant list is tried first, then the shared list. The first
    entry whose pattern matches the whole reference wins. Refs with no match are
    left out, and the dashboard says so.
    """
    data = _load()
    variant = variant_for(board_path)
    if variant is None:
        return {}
    rules = [(re.compile(r['match']), r) for r in data.get(variant, [])]
    rules += [(re.compile(r['match']), r) for r in data.get('shared', [])]
    out = {}
    for ref in refs:
        for pattern, rule in rules:
            if pattern.fullmatch(ref):
                out[ref] = {'purpose': rule['purpose'], 'issues': list(rule.get('issues', []))}
                break
    return out
