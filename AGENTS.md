# Working in testing-BMS-designs

Read README.md and `docs/slave-18s-design-basis.md` before design work.

- Current target: ADBMS1818 **18S** slave module. The master is out of scope for now.
- Baseline circuit: ADBMS1818 datasheet Figure 112 (typical application). Write every
  deviation into the design basis with a reason.
- Keep the extra isoSPI filtering (split termination + centre-tap caps) from Racc's
  reference. It is there for motor noise, even though the datasheet figure lacks it.
- Never invent pin numbers. Build symbols and footprints from the manufacturer's pin
  table and cross-check against the exported netlist.
- `_reference/racc/` is private. Never publish it, copy it into `site/`, or remove it
  from `.gitignore`.
- Keep the Board Boxes toolbars and features intact when changing the dashboard.
- Keep documentation commits separate from schematic and PCB commits.

## KiCad MCP (mixelpixx KiCAD-MCP-Server at C:\Users\quinn\KiCAD-MCP-Server)

Configured for this repo in `.mcp.json`. Tips from its docs (HEADLESS_AUTHORING, KNOWN_ISSUES):

- **kicad-cli is ground truth.** When a skip-based MCP tool disagrees with ERC, a
  render or the netlist, believe `kicad-cli`.
- **Per-sheet recipe:** `create_schematic` -> `batch_add_and_connect` (net names, symbol
  origins on a 2.54 mm grid, parts ~12.7 mm apart) -> `batch_add_no_connects` ->
  `run_erc` -> export SVG and actually look at it.
- **Done means:** 0 ERC errors with warnings triaged, the render eyeballed, and the
  netlist checked for any pin you are unsure about. Never trust "connected N pins" alone.
- **Grid:** the connection grid is 1.27 mm. One off-grid origin can break junctions on the
  whole sheet. Use `lint_offgrid` (fix sub-0.5 mm offenders); never snap inside `lib_symbols`.
- **ERC:** run on the root sheet for hierarchical designs. Report coordinates are mm/100.
  "Symbol doesn't match library" and "library not in configuration" are cosmetic.
- **Power flags:** exactly one driver per power net design-wide. Rails fed only by
  connectors or passives need one `PWR_FLAG`.
- **Vendor symbols:** flat SnapEDA/SamacSys symbols break skip-based tools; run
  `repair_flat_symbols` first. Vendor output pins are often typed `passive`.
- **Deleting a wired part leaves its labels behind.** Clean them up.
- **SWIG backend:** KiCad's UI will not show MCP edits until you reload (File > Revert).
  Zone fill via SWIG can segfault; let KiCad fill zones when the board is opened.
- **`.kicad_pro` net classes:** edit by JSON read-modify-write, not through the pcbnew model.
- JLCPCB API keys are not set; the local parts DB in `~/.kicad-mcp/data` still works.

### What went wrong while wiring the slave (2026-11-05, MCP v2.7.0)

- **Eeschema may have the file open.** If `~<name>.kicad_sch.lck` exists, Eeschema has it
  open. It won't see edits made on disk, and saving from it overwrites them. Tell the user
  before editing; they reload with File > Revert.
- **`batch_connect` labels face into the part.** `get_pin_angle` already returns the
  outward angle, and `batch_connect` flips it again (`python/commands/schematic_batch.py`,
  the `{0: 180, 90: 270, ...}` map). The connections are right, but the text runs across
  the part. Run `_tools/kicad_sch/orient_labels.py` after every batch.
- **`connect_to_net`** draws its 2.54 mm stub in the right direction but always places the
  label at angle 0 (text to the right). Read in the source; not used here.
- **30 s timeout, but the work keeps going.** Node abandons `batch_connect` after 30 s,
  while the Python worker keeps rewriting the whole file once per label (about 1 s each on
  a 300 kB sheet; the file is briefly 0 bytes between writes). Keep batches to about 15
  labels. After a timeout, leave the file alone until it has been unchanged for 30 s, then
  count the labels.
- **Every MCP edit rewrites the whole file** in its own format, with float noise like
  `78.74000000000001`. Run `kicad-cli sch upgrade --force <sch>` after each MCP batch. You
  get KiCad's own format (the netlist was checked identical), small diffs, and a load test
  for free: it fails if the file is broken.
- **`add_schematic_component` flips field positions in y.** A new PWR_FLAG showed its
  `#FLG` reference, with both fields below the flag. Hide the reference and put Value
  3.81 mm above the pin, as KiCad's library does.
- **`move_schematic_component` leaves labels behind** at the old pin points, and they
  float. Use `_tools/kicad_sch/shift_group.py`, or delete the labels, move, and reconnect.
- **Raw newlines break text items.** Inside a KiCad string, write `\n` (backslash-n). A
  real line break makes the file fail to load.
- **ERC facts:** passive pins satisfy `input` pins. `power_in` needs a `power_out` pin or a
  PWR_FLAG. PWR_FLAG pins don't appear in the netlist, so check them with ERC
  (`power_pin_not_driven`). Run `kicad-cli sch erc --severity-all`; clean prints "Found 0
  violations". A copy outside the project folder adds `lib_symbol_issues` and
  `footprint_link_issues` warnings because its libraries aren't found. That's the copy,
  not the design.
- **Readability:** on vertical parts the labels are vertical text. Check the render for
  labels in the same column running end to end (`S1` over `CELL10` read as one string)
  and for labels running into heading text.
- `lint_offgrid` and `list_floating_labels` worked and agreed with kicad-cli.

### What went wrong bringing the slave to the PCB (2026-11-05)

- **Don't use MCP `sync_schematic_to_board`.** It reported success, but its nets lacked
  the `/` prefix KiCad gives local labels (`V-` vs `/V-`), and it skipped LCSC/MPN: 289
  parity errors. It also wrote `top_level_sheets` into the `.kicad_pro`. Ask the user to
  press F8 in the PCB Editor (default options -> **Update PCB** -> Close -> click once to drop
  the parts -> Ctrl+S -> close KiCad). The dialog first lists the changes; nothing is applied
  until **Update PCB** is pressed (status bar "Pads 0" means not yet).
- **Moving footprints:** use `_tools/kicad_sch/pcb_move.py` (edits only each footprint's
  `(at ...)` line; pads and text inside are relative). The MCP board tools rewrite the whole
  file through SWIG.
- **KiCad local history:** saving creates `slave-18s/.history/` (gitignored), which holds a
  second `.kicad_pcb`. Every board scan must skip `.history`. `export_site.py` now does.
- **Saving from KiCad** writes its default `erc`/DRC settings into the `.kicad_pro`
  (about 350 lines). That's harmless; re-run `check_slave18s.py` to confirm ERC is still clean.
- **3D renders** for the dashboard: call `render_board_3d()` from
  `_tools/pcb_dashboard/server.py` (same kicad-cli options and crop as the UI button). Run it
  in the background, since it takes over a minute.

### Helper scripts (`_tools/kicad_sch/`)

| Script | Use |
|---|---|
| `check_slave18s.py` | kicad-cli netlist + ERC check of the slave against its wiring table. Exit 0 = pass. Run after every schematic edit (`--blocks 1 2` for part of it, `--erc` to list violations) |
| `make_lean.py` | Writes `slave-18s-lean/` schematic from Guard (drops fuses, clamps, TVS, C-pin caps, J6/J7 and, since 2026-11-10, the test points; swaps in 120 ohm 1206 balance, 0603 series resistors, M2 holes; F120 becomes the net tie NT1, CELL0 to V-). Never hand-edit Lean's schematic; re-run after Guard edits, then `kicad-cli sch upgrade --force` and `check_slave18s.py --variant lean` |
| `orient_labels.py` | Writes the file: turns pin labels to face outward and rounds coordinates (`--dry` to preview) |
| `shift_group.py DX DY REF...` | Writes the file: moves parts together with their labels and no-connect flags |
| `render_sch.py OUT.png --region X0 Y0 X1 Y1` | PNG of the sheet or a region (sheet mm) via kicad-cli PDF + PyMuPDF |
| `kisch.py --pins REGEX` | Lists parts, pin end points (mm) and which way each pin faces |
| `check_pcb_parity.py` | PCB vs schematic: every footprint and its name, every pad's net vs the kicad-cli netlist, every footprint on F.Cu (single-sided; on Lean the test-point pads TP1-TP14 must be on B.Cu), DRC schematic parity. `--variant lean` for Lean. Exit 0 = pass. Run after any PCB or schematic change |
| `pcb_move.py MOVES.json` | Writes the PCB: sets footprint positions from `{"REF": [x, y(, rot)]}`. `--variant lean` for Lean. Close KiCad first |
| `make_rules.py` | Writes the net classes into the `.kicad_pro` and generates the `.kicad_dru` (stack banks, isoSPI barrier, mounting-hole keep-out) from the board's nets. `--variant lean` for Lean. `--check` = files current and kicad-cli really loads the rules. Run after any net is added or renamed. Close KiCad first |
| `flip_back.py REF... \| --test-points` | Writes the PCB: flips footprints to B.Cu in place through pcbnew and splices only their blocks into the file (the diff stays those parts; a whole-file pcbnew save re-formats 5000 lines). Idempotent. `lean_place.py` runs it for TP1-TP14. KiCad's Python, KiCad closed |
| `lean_place.py` | Writes the Lean PCB: outline + every footprint from the knobs at its top (shrink trial). Run with KiCad's Python (`"C:\Program Files\KiCad\10.0\bin\python.exe"`), KiCad closed. `--dry` to report only, `--drc` for a kicad-cli DRC count. Reports courtyard overlaps and parts off the outline |

Wiring recipe that worked: back up the sheet -> MCP `batch_connect` (about 15 labels) ->
if it timed out, wait for the file to settle -> `kicad-cli sch upgrade --force` ->
`orient_labels.py` -> `upgrade --force` again -> `check_slave18s.py` -> render the region
and look -> `lint_offgrid` + `list_floating_labels` -> commit the schematic alone.

### Adding the protection parts (2026-11-06)

- **A script that writes symbols and pin-end labels straight into the `.kicad_sch` worked**
  better than MCP batches for 58 parts: copy the lib symbol from KiCad's own `.kicad_sym`,
  put each label exactly on the pin end, then `upgrade --force` -> `orient_labels.py` ->
  `check_slave18s.py`. The checker, not the script, is what proves it.
- **Symbol field angles are relative to the symbol.** On a part rotated 270 (a vertical
  diode), Reference/Value need `(at x y 90)` to read horizontally; with 0 they come out
  vertical and on top of each other. Render and look.
- **F8 doesn't delete removed parts by default.** Its "Delete footprints with no symbols" box is
  off; tick it when the schematic lost parts (Lean, 2026-11-06: 58 leftovers, removed afterwards from
  the unrouted file). KiCad also saved that board with CRLF line endings (a 71k-line diff); the
  committed boards are LF, so convert back before committing.
- **After F8, check the user really saved.** Run `check_pcb_parity.py` only after they say
  KiCad is closed; an unsaved F8 leaves the old board on disk. F8 drops new parts in a pile,
  partly outside the outline; group them with `pcb_move.py` and check courtyards with
  pcbnew (`GetCourtyard(F_CrtYd).BBox()`), all pairs.
- **Changing a footprint size (0603 -> 1206) breaks the old grouping**: the R100 row
  overlapped itself (17 shorting items) until it was respaced.
- `kicad-cli pcb export svg` needs `--exclude-drawing-sheet`, or the title block covers
  the board picture.

### Design rules (2026-11-06)

- **kicad-cli silently ignores the whole `.kicad_dru` if one rule has a syntax error**: no
  message, DRC just runs without custom rules. `make_rules.py --check` appends a canary rule
  to a temp copy and fails unless it fires. Never hand-edit the `.kicad_dru`.
- Custom rules are checked in both A/B orders and between pads of the same footprint; the
  last matching rule wins, so the isoSPI barrier rules sit after the stack rules.
- `A.NetName == '/ISOA_L*'` wildcards, `A.intersectsCourtyard('T501')`, `disallow zone` and
  `creepage` all work in kicad-cli 10. `disallow zone` flags copper zones, not keepout areas.
- NC pins get nets named `unconnected-(T501-LINE_CT-Pad5)` on the board. Rules that say "every
  other net" must account for them.

### Shrink trial (2026-11-08)

- **F8 does not replace the footprint of a locked part.** It updates the fields (Value, LCSC)
  and leaves the old footprint. Unlock first: delete `(locked yes)` from that footprint in the
  `.kicad_pcb` (KiCad closed), then F8 again.
- **KiCad saved the board with CRLF line endings again.** Convert to LF before committing.
  (`grep -c $'\r'` miscounts in this shell; count `\r` bytes with Python instead.)
- **pcbnew keeps the board file open on Windows.** Writing it from the same KiCad Python process
  after `LoadBoard` fails with Errno 22; drop the board object first (`lean_place.py` does).
- **Check which project the F8 was run in (2026-11-09).** An F8 meant for Lean was run in Guard. The
  F8 report shows it: Guard's lists F1xx/D1xx and `Pulse_HM2113ZNL`, Lean's lists NT1 and
  `Bourns_SM91502AL`. A no-change F8 save still rewrites the board (CRLF, formatting) and reorders
  the net classes in the `.kicad_pro`, which makes `make_rules.py --check` fail; `git checkout` both.
- **Part swaps for Lean only** go in `make_lean.py`'s `SWAP` table, not in the Lean schematic.
- **Lean test points were bare pads on the back (2026-11-09; removed from Lean 2026-11-10, the
  flipping traps below still hold).** `SWAP` turns TP1-TP10 (Keystone loops)
  into the TP11-TP14 pad; the board needs an F8 after `make_lean.py`. Two traps found while flipping:
  slicing footprint blocks "up to the next footprint" makes the last one swallow the file's tail, and
  pcbnew gives uuid-less items ids another part already owns, after which KiCad silently drops 9
  footprints on load (count them with pcbnew, not just by grep).
- **The MCP's JLCPCB parts DB** (`~/.kicad-mcp/data/jlcpcb_parts.db`) was an empty 48 kB file.
  `download_jlcpcb_database` fetched CDFER's catalog but couldn't replace the file because other
  sessions' MCP servers hold it open (WinError 32); it was filled in place instead (501k in-stock
  parts, 2026-11-08). It lists only parts in stock, so a missing LCSC number may just be out of stock.
