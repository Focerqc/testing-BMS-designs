# Board Boxes on GitHub Pages

`index.html` is the real local dashboard UI running on a published snapshot: board view,
layers, part info, box drawing, undo/redo and Copy Prompt. Annotations save in your
browser only. Fresh KiCad renders need the local dashboard. `news.html` is the project
overview.

Refresh with `python _tools/pcb_dashboard/export_site.py` (KiCad 10 installed), check with
`node _tools/pcb_dashboard/check_hosted.cjs`, then push to `main`.
No reference photos are published; `_reference/racc/` is private.
