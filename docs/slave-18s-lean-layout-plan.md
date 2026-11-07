# 18S Lean: PCB layout plan

Status: **plan only, 2026-11-06.** Nothing in this file has been placed or routed yet. You do
the placement and routing in KiCad. Each step says what to do, why, what to look for, and
which check to run. Tick the boxes as you go.

Read with: `AGENTS.md`, `docs/slave-18s-design-basis.md` ("Variants", "Balance resistor
sizing", "Net classes and clearance rules", "Placement checklist").

## What the Lean board is (facts this plan relies on)

- **93 footprints** after F8: the 92 circuit parts plus the net tie NT1 (step 5). The board
  file still holds Guard's 150, because F8 hasn't been run on it yet.
- **One cell channel is just two resistors:** R1nn (10 Ω 1206, CELLn → Cn_F → U1 C pin) and
  R2nn (balance, CELLn → Sn → U1 S pin). There are no C1xx caps, zeners or fuses. Tap traces run
  straight from J1/J5 to the channel.
- **C0 is special:** J1.1 and R100 pin 1 are on **CELL0**, a net of their own. CELL0 meets V−
  (the chip ground: EP, cap returns, the pour) at exactly one point, the **net tie NT1** right
  next to J1.1. Because they are two nets, KiCad's DRC flags any other copper joining them as a
  short. So the rule "C0 sense on its own trace" is enforced by DRC while you route (step 5).
  (Until 2026-11-06, `make_lean.py` merged CELL0 into V−, and DRC couldn't see the difference.)
- **U1 stays where it is** (75, 40), rotated 270°. The isoSPI ports on the right were placed on
  purpose (design basis, "isoSPI ports moved next to U1"). With that rotation U1's cell pins sit
  like this (pad centres, mm):

  | U1 side | Pins | Nets, in pin order | Span |
  |---|---|---|---|
  | Top (y = 34.3) | 1 to 16, right to left | V+, C18, S18, C17 … S12, C11 | x 78.8 → 71.3 |
  | Left (x = 69.3) | 17 to 32, top to bottom | S11, C10, S10 … S4, C3 | y 36.3 → 43.8 |
  | Bottom (y = 45.7) | 33 to 38, left to right | S3, C2, S2, C1, S1, C0 | x 71.3 → 73.8 |
  | Bottom, then right | 39 to 64 | GPIO1–9, VREG, DRIVE … V−, isoSPI | |

- **The connector row is fixed** (top edge): J1 (C0 at x = 31 … C9 at x = 49), J5 (C9 at 54.5 …
  C18 at 72.5), J2 at 79. Cell numbers rise left to right.

**The key insight for placement:** walk anticlockwise around U1 from the bottom-left corner:
C0 → up the left side → along the top → C18 at the top right. That is the **same order** as the
connector pins left to right. So if the 18 channels sit in an "L" around U1's top-left corner,
in order, with their harness ends facing out, every tap trace nests inside the one before it and
**no ratsnest line has to cross another**. C0's tap is the outermost (longest) and C18's the
innermost (shortest).

```
 y=0 ┌──────────────────────────────────────────────────────────────────────┐
     │ H4     [J1  C0 ……… C9][J5  C9 ……… C18]  [J2 NTC]                 H3  │ connectors (fixed)
     │  C0┐ C1┐…   tap traces nest, C0 outermost                            │
 ~12 │    │   │      ┌─ top row: ch 18…12, harness end UP ─┐                │
     │    │   │      │  R2 (hot) outer row                 │                │
     │  left column  │  R1 inner row                       │        T601 J4 │ port B, OUT
     │  ch 11…1, 0   │          ┌──────────┐               │                │
     │  harness end  │          │ U1 (75,40)│               │        T501 J3 │ port A, IN
     │  LEFT: R2 out,│          └──────────┘                                │
     │  R1 in, → U1  │  bottom: GPIO caps, VREG/VREF caps, R401/R402        │
     │               Q301 + VCOLL copper      NTC parts (R7xx/C7xx/TH701)    │
 70  │ H1                   TP1…TP10 along the bottom edge               H2  │
     └──────────────────────────────────────────────────────────────────────┘
```

This is a starting floorplan, not a rule. You'll move it around in step 3. What has to stay
true: the channels follow the anticlockwise order, the R2s are the outermost parts (heat away
from U1), and the R1s are the innermost (next to their C pin, Racc's method).

## Step 0: prerequisites

### 0a. Tooling (done 2026-11-06, not yet committed)

| Script | Today | Change |
|---|---|---|
| `make_lean.py` | Merges CELL0 into V− | Keeps CELL0 and puts a net tie **NT1** (CELL0 to V−) where F120 was, so DRC can enforce the C0 sense (step 5). This is a schematic change: its own commit, and the Lean wiring table in `check_slave18s.py` follows |
| `check_pcb_parity.py` | Works on Lean already with `--sch …lean.kicad_sch --pcb …lean.kicad_pcb` | Add `--variant guard\|lean` (same as `check_slave18s.py`). Add one layout check: **every footprint on F.Cu** (the single-sided rule) |
| `make_rules.py` | Hard-wired to Guard's `.kicad_pro`/`.kicad_pcb`/`.kicad_dru` | Add `--variant`. The net classifier already handles Lean's nets (no TAPn or VBAT_F; CELL0 lands in bank 0, CELL18 in bank 6). Lean's `.kicad_dru` is currently a stale copy of Guard's, so regenerate it after F8 |
| `pcb_move.py` | Has `--pcb` | Add `--variant` as a shortcut |
| `export_site.py`, dashboard | Already find every `.kicad_pcb` | No change needed (see "Board Boxes and the variants" below) |

### 0b. Clean starting point (done 2026-11-06, commit `PCB (Lean): F8 drops …`)

**Lesson from doing it:** F8's option **"Delete footprints with no symbols"** is off by
default. Without it, F8 updates nets and adds new parts but leaves removed parts on the board.
Tick it whenever the schematic lost parts. (This time the 58 leftovers were removed from the
file afterwards, and the parity check proved the result: 93/93.)

1. Commit the step 0a work first, as three commits (tools, Lean schematic, docs), so the Lean
   PCB commits contain only the PCB.
2. Open `slave-18s-lean/adbms1818-slave-18s-lean.kicad_pro` → PCB Editor → **F8**, default
   options. The dialog lists 58 deletions (F100–F120, D101–D118, D301, C101–C118), one
   addition (NT1) and the net renames. Press **Update PCB** → Close → click once to drop NT1
   → **Ctrl+S** → close KiCad.
3. Tell me it's closed. I run `check_pcb_parity.py --variant lean` (expect 93 footprints,
   0 mismatches, 0 parity) and `make_rules.py --variant lean`, then `--check`.
4. **Commit:** `PCB (Lean): F8 drops the protection parts`.

**Why the order matters:** `make_rules.py` builds the rules from the nets on the board, so it has
to run after F8. Otherwise it would write rules for nets Lean doesn't have.

## Step 1: fixed parts (connectors, holes, isoSPI, U1)

These keep their Guard positions. The job here is to **lock** them, not to move them.

- In KiCad: select J1, J5, J2, J3, J4, J6, J7, T501, T601, U1, H1–H4 → right-click → **Lock**
  (or press L). Locked parts can't be dragged by accident while you work around them.
- **What to look for:** nothing new. Open the 3D viewer (Alt+3) once to get your bearings:
  where each connector's plug goes and which way U1 pin 1 faces (the dot is top right).
- **Check:** DRC (Inspect → Design Rules Checker, "Refill all zones" ticked). Expect 0 errors,
  plus unconnected items and silk warnings, which are fine at this stage.

## Step 2: clear the deck

F8 leaves the old Guard grouping with gaps where the 58 parts were. Rather than nudging that,
start clean: **I generate a `pcb_move.py` JSON that parks every unlocked part in a staging grid
below the board** (y ≈ 80–120), sorted by group (R1xx, R2xx, supply, isoSPI passives, NTC, TPs).
You then pull parts onto the board one group at a time. With nothing else on the board, the
ratsnest of the group you're working on is easy to read.

- **Check:** `check_pcb_parity.py --variant lean` (moves never change nets, but it's cheap
  and confirms the file loads).
- **Done 2026-11-06.** Staging rows start at y = 78 mm, top to bottom: balance R201–R218
  (2 × 9), cell series R100–R118 (2 rows), supply (Q301 first), isoSPI A then B, NTC pairs
  + TH701, TP1–TP10 then TP11–TP14. 0 courtyard overlaps, parity PASS, DRC 0 errors.
  **In KiCad:** hover a part and press **M** to move it. To bring a whole row, drag a
  selection box over it on empty board (left to right selects only parts fully inside),
  then press **M**.

## Step 3: one cell channel, done properly

Pick **channel 14** (top row, middle of J5). It sits in the simple straight part of the L, away
from the corner.

1. Drag R114 and R214 onto the board, between J5 pin 6 (C14, x ≈ 64.5) and U1's top side
   (pins 10/11: C14_F, S14).
2. **Orientation:** both resistors vertical (rotate 90°), harness pad (CELL14) **up** toward
   the connector, chip pad **down** toward U1.
3. **Position:** R214 (balance, hot) in the outer row, about 12–14 mm above U1's top pins.
   R114 (10 Ω) in the inner row, about 4–6 mm above the pins, next to its C pin.
4. **Left/right order:** along U1's top edge, going right to left, the pins read C14, S14, C13,
   S13 … So in each channel the R1 (C) sits to the **right** of the Sn trace's path, and the
   next channel down (13) sits to the left. Get this right once and the 17 copies inherit it.
5. **Pitch:** the channel's width along the row sets the pitch for all 18. Design it around
   the **2512 envelope** (6.3 × 3.2 mm body, about 7.3 × 3.9 mm courtyard), even if you later fit a
   47 Ω 1210 or 2010. Starting point: **4.5 mm pitch**. That leaves about 0.6 mm between
   neighbouring 2512 courtyards for one tap trace to pass. Write the pitch down: step 4 uses it.
6. **Route this one channel** (front layer): tap trace J5.6 → R214 harness pad → down to
   R114 harness pad (both CELL14, HV_CELL 0.25 mm). Then R114 → C14_F pin (0.25 mm) and
   R214 → S14 (BALANCE 0.30 mm, neck to 0.3 at the pin, which is already the pad width).
   Ratsnest for this channel: zero lines left.

**Why this shape:**
- R1 sits next to the C pin (Racc's method): in Guard the R1/C1 pair is the anti-alias filter
  and it only works close to the pin. Lean has no C1, but keeping R1 close keeps the
  high-impedance node short. Stay in the habit for when the C1 caps come back.
- R2 outermost: 0.22–0.26 W each. The heat should spread into the board, not into U1
  (balancing is derated to 80 mA once the die is above 85 °C).
- The Sn trace carries the balance current. Cn_F carries µA. So the long fan-in leg belongs to
  Sn (wide), and the short one to Cn_F.

**What to look for:** press **`** (backtick, highlight net) on CELL14 and S14 in turn: each should
be one clean path. Check the courtyards in 3D: the 2512 is visibly the big part.

**Check:** DRC. Expect no clearance errors around channel 14.

## Step 4: repeat the channel 18 times

Three ways to do it:

| Method | How | Verdict |
|---|---|---|
| Manual | Move each part with **M**, or use Edit → Move Exactly (Shift+M) with the offset typed in | Fine for 3 parts, error-prone for 36, and has to be redone when the package changes |
| KiCad's own tools | "Create array" makes **new** copies (unannotated, no nets): wrong for parts that already exist. Multichannel / "Repeat layout" needs one hierarchical sheet per channel, and our schematic is flat | Not usable here |
| **Script → `pcb_move.py` JSON** | I read the position and rotation of R114/R214 from the board, then generate positions for all 36 resistors: top row ch 18…12 at your pitch along x, left column ch 11…1 at the same pitch along y (the channel cell turned 90°, harness end left), and a 45° corner cell for ch 11/12 | **Recommended** |

**Why the script:** it is exact and repeatable. It also lives in the repo as one function of
(pitch, row y, column x), so when the balance package or pitch changes in the shrink pass you
change one number and re-run it, rather than re-placing 36 parts. That's the whole reason to plan
for a package change now.

Workflow: close KiCad → I run it with `--dry` and show you the list → `pcb_move.py` → you
reopen and look. **Placement repeats; routing doesn't.** Every channel's fan-in to U1 has a
different length and angle, so you route those by hand. Only the short in-cell link
(R2 harness pad → R1 harness pad) repeats exactly.

**Channel 0 (R100 only)** goes at the bottom of the left column, next to U1 pin 38, harness
pad toward J1.1. There is no R2 for channel 0. NT1 goes beside J1.1 (step 5).

**What to look for:**
- Ratsnest: the tap lines from J1/J5 fan into the L **without crossing**. A crossing means two
  channels are swapped or one is flipped (rotate it 180°).
- Banks: channels sit next to adjacent cells, so neighbours are ≤ 25 V apart (0.2 mm). The one
  place far-apart nets meet is the **corner** where the left column turns into the top row:
  keep ch 1–2 (bank 0) and ch 12–14 (bank 4) apart. Their outer ends shouldn't be neighbours.
- The left column (ch 1–11 + ch 0) at 4.5 mm is about 54 mm tall: y ≈ 12–66. That fits, just.
  If it doesn't, the corner cells can fan at 45°, or a few low channels (0–2) can fold onto U1's
  bottom side, where their pins already are.

**Check:** `check_pcb_parity.py --variant lean`, then DRC. Expect 0 clearance/courtyard
errors. **Commit:** `PCB (Lean): cell channels placed`.

## Step 5: the C0 sense (R100 to J1.1)

The rule: **CELL0 copper (J1.1 → R100 pin 1) is one dedicated trace, and V− touches it
only at the net tie NT1.**

**What a net tie is:** a footprint with two pads (one per net) joined by a small copper
bridge. It's the only place KiCad allows two different nets to touch. It goes in the BOM as
nothing: it is just copper on the board. Anywhere else, CELL0 copper touching V− copper is a
DRC **short** error.

1. Place **NT1** right beside J1.1, its CELL0 pad toward the J1.1 pad and its V− pad toward
   the board. Join the CELL0 pad to J1.1 with the shortest, widest trace you can (about
   1–2 mm).
2. Route **R100 pad 1 → J1.1** on its own 0.25 mm trace on the front. It ends at the J1.1
   pad, not at NT1.
3. The V− pour (step 8) connects to NT1's V− pad. It stays away from the CELL0 trace by
   itself: different net, so the zone fill keeps clearance.

**Why:** Figure 99 of the datasheet. While measuring, R100 carries no current (DCP = 0 pauses
balancing), so any voltage on its trace is error on cell 1. If supply current (up to 35 mA) shared
even 20 mm of 0.25 mm 1 oz copper (about 40 mΩ), cell 1 would read about 1.4 mV off. With the
tie at J1.1, the only shared copper is the 1–2 mm from the J1.1 pad to NT1: a few µV. While
cell 1 balances, its current returns through R100 and this trace (≤ 89 mA), which is fine for
0.25 mm. This is the same split Guard makes at J1.1 (fuse F100 to the sense, F120 to V−); Lean
replaces F120 with the tie.

**Check:** DRC. A `shorting_items` error means V− copper touches CELL0 somewhere other than
NT1. An unconnected item on CELL0 or V− means the trace or the tie isn't joined yet.

## Step 6: supply (Q301, R301/R302, C301–C305) and U1's bottom side

1. **C303 (VREG 1 µF)** first: on the U1 pin 48 corner, the shortest loop to V−. Then
   C304/C305 (VREF1/2) at pins 51/50 on the right side, and R401/R402 at IBIAS/ICMP (57/58).
2. **R301 + C301** (V+ filter) at pin 1, the top-right corner. Its feed comes from CELL18:
   take it off the ch 18 tap trace or J5.10 directly.
3. **Q301** below U1 (as in Guard, around (60, 58)), with R302/C302 at the collector and the
   emitter (VREG) trace to C303.
4. **VCOLL copper:** reserve a rectangle around Q301's tab, about **25 × 25 mm on both layers**.
   The tab is the heat path: 52 × 52 mm 2 oz gives Tj ≈ 92 °C at 1.6 W, and 25 × 25 mm 1 oz gives
   about 150 °C (the limit). This copper is bank 6 (top of stack), so the rules keep 0.6 mm to
   banks 0–4 and nothing low-voltage may sit inside it.

**What to look for:** VREG and VREF caps within about 2 mm of their pins, with a direct via to
the back V− pour beside each cap's V− pad.

**Check:** DRC. **Commit** (or batch with step 7).

## Step 7: isoSPI passives, NTC, test points

- **isoSPI:** R501/R502/C501/C502 and R601/R602/C601/C602 in the column at x ≈ 90, between U1
  and each transformer's chip side, as in Guard. Keep both 51 Ω resistors of a port in line
  with the pair, and the CM/CT caps right at their node. **Nothing else** in the U1 →
  transformer → connector corridor.
- **NTC:** R701–R704 and C701–C704 next to GPIO1–4 (pins 39–42, U1's bottom side). J2's traces
  run down from the top edge. **TH701** (onboard NTC) somewhere representative of board
  temperature, but **not** in the R2 band: next to it, it reads balance heat, not cell heat.
- **Test points:** TP1–TP10 along the bottom edge, ≥ 5 mm apart (hook clips), silk labels.
  Lean keeps TP11–TP14 (bare HV pads on VCOLL, C6_F, C12_F, C18_F): put them by their nets,
  in the channel L and in the Q301 copper, away from the low-voltage loops.

**Check:** `check_pcb_parity.py --variant lean`, DRC, then a **3D render** (dashboard button,
or I run `render_board_3d()` in the background). Look for: TP loops reachable, plugs not
blocked, nothing tall between the GH connectors and the board edge. **Commit:** `PCB (Lean):
placement complete`. Tick the matching boxes in the design basis placement checklist (doc
commit, separate).

## Step 8: routing

### Order (most constrained first)

1. **isoSPI pairs**: chip side (IPA/IMA, IPB/IMB) and line side. Short, side by side, front
   layer, no vias except the one J3/J6 needs (their pins are in opposite order, so one line net
   has to change layer **inside** the port's own area). Use the differential-pair router (6).
2. **U1 fan-out**: 0.5 mm pitch. One trace leaves each pad straight out about 1 mm before it
   turns. The router follows the net class: HV_CELL 0.25 and BALANCE 0.30 at the pads. A 0.30
   track between neighbouring 0.30 pads doesn't fit, which is why each pin gets its own short
   escape straight out.
3. **Cell fan-in** (Sn and Cn_F from each channel to its pin): in order, channel by channel,
   front layer. This is where the "no crossings" placement pays off. If you need a via, the
   placement is wrong.
4. **Tap traces** (J1/J5 → channels), front, nested, C0 outermost.
5. **C0 sense trace and NT1** (step 5).
6. **Supply** (V+, VCOLL, DRIVE, VREG), then **NTC/GPIO**, last the **test points**.
7. **Pours** last (below), then refill (B).

### Rules of thumb for this 2-layer board

- **Front = signals. Back = V− pour**, as unbroken as possible. That makes the back a heat
  spreader and a low-impedance return. Short back-side jumps are fine (two vias, a few mm) where
  something must cross, but every back-side trace cuts the pour. Keep jumps short and run them
  in the same direction.
- **No pour, no foreign tracks** under T501/J3/J6 or T601/J4/J7 (the rules file flags it).
  Draw a **keepout area** (no copper pour, no tracks) on both layers over each port's line side.
  DRC then shows the barrier as a shape, and the pour won't creep in.
- **The V− pour** must keep 0.6 mm from banks 2+ and 2.0 mm from the isoSPI line side. The custom
  rules do this automatically when the zone fills; you don't set it on the zone. Leave the zone's
  own clearance at the default.
- **U1 EP:** the footprint's 16 thermal vias take heat to the back pour. Make sure the back pour
  covers the area under U1 solidly (no traces under the EP on the back).
- **Balance resistor heat:** each R2 pad is its own net (CELLn / Sn), so they can't share a
  pour. Use (a) the back V− pour under the whole R2 band (heat crosses the 1.6 mm FR4 and spreads)
  and (b) fat pads: a small front-layer zone per pad, same net, about 2 × the pad area. Don't
  add V− vias inside the R2 band, where they would only make clearance problems.
- **Q301:** VCOLL zones on both layers with 10–20 stitching vias (0.6/0.3 mm) through the tab
  area. The back VCOLL zone needs a **higher priority** than the V− pour, so the pour flows
  around it.
- **Tap traces as the fuse:** the design basis says Lean's thin traces act as the fuse
  (Racc). Open question: should each tap get a deliberate neck (for example 0.2 mm × 5 mm near
  the connector) so the fusing point is known and is not under U1? Decide before routing the
  taps; it's a design-basis entry, not a layout whim.
- **Angles and stubs:** 45° only, no acute corners, no stubs. The router's walkaround mode
  (not shove) is easier while learning.

### KiCad keys you'll use most

**X** route, **6** diff-pair route, **V** via while routing, **/** flip posture, **W/Shift+W**
cycle track widths (leave on "use net class"), **`** highlight net, **B** refill zones,
**D** drag a track keeping 45°, **E** properties, **L** lock.

## Step 9: checkpoints and commits

| When | Run | Pass means |
|---|---|---|
| After every session in KiCad (KiCad closed, saved) | `check_pcb_parity.py --variant lean` | PASS: footprints, pad nets, parity, all on F.Cu |
| After F8 or any net change | `make_rules.py --variant lean` then `--check` | rules: OK (canary fired) |
| After each placement step | DRC in KiCad, or `kicad-cli pcb drc --severity-all` | 0 errors. Unconnected and silk warnings allowed until the end |
| After placement, and at the end of routing | 3D render (top + iso) | Eyeballed: plugs, TPs, clearances, labels |
| End of routing | DRC with zones refilled, `--schematic-parity` | 0 errors, 0 unconnected, silk triaged |

**Commits:** one PCB commit per finished step (`PCB (Lean): …`) holding only
`slave-18s-lean/*.kicad_pcb` (plus the `.kicad_pro`/`.kicad_dru` when `make_rules.py` changed them).
Script changes go in their own `Tools:` commits. Design-basis updates (positions, checklist
ticks, decisions) go in separate `Docs:` commits. Re-export the site after the placement
commit, not before (next section).

## Board Boxes and the variants

- **Local dashboard:** already shows both. `/api/boards` walks the repo for every
  `.kicad_pcb`, so `slave-18s-lean/adbms1818-slave-18s-lean.kicad_pcb` is in the board dropdown
  next to Guard. Boxes (`<board>.boxes.json`), 3D renders (`<board>_3d_top/iso.png`) and the
  schematic PDF are all stored per board, so Lean gets its own annotations and renders without
  touching Guard's.
- **Hosted site:** published with Lean on 2026-11-06 (step 2 state: staged parts below the
  outline, top render made without them so it matches the outline). Re-export after each
  placement commit: `export_site.py` → `node check_hosted.cjs` → push `site/`.
- **Layout practice card** (left sidebar): "Lay out the 18-channel L" draws the R2xx/R1xx boxes
  for steps 3–4 from U1's pads (pitch, top-arm count, R2 package), and a short guide covers
  steps 3–7. On the hosted site boxes save in the browser only, so use **Save .txt** to keep
  work and **Open .txt** to load it back (locally too, before Copy Prompt).
- **Small improvement worth making:** the dropdown shows raw paths. A label map
  (`slave-18s/…` → "18S Guard", `slave-18s-lean/…` → "18S Lean") in `app.js` would make the
  hosted page clearer. The toolbars and features stay as they are.

## Step 10 (later): the shrink pass

Do this after the first Lean board has been on the bench, not before. Shrinking without the
measurements below is guessing.

**What shrinks the board most, roughly in order:**

1. **Balance package and channel pitch.** The L of 18 channels is the largest block on the
   board. Going from 2512 (4.5 mm pitch) to a 1210 or 2010 (about 3.2–3.5 mm pitch) shortens
   both arms by roughly a quarter. With 47 Ω the per-resistor power is 0.22 W: that's 90 % of a
   1206 (no), 45 % of a 1210 (0.5 W), about 30 % of a 2010 (0.75 W). A wide-terminal 1218/0612
   (1 W, heat goes out through the long side) is worth a look for heat per mm². Changing the
   package is a Guard schematic edit → `make_lean.py` → F8. KiCad footprints are centred, so
   the parts stay put and only the pitch number in the step-4 script changes.
2. **Connectors.** J1 + J5 side by side take about 45 mm of edge. Options: put them on two
   edges (J5 on the right edge feeding the top row), or a 2-row header (check its voltage
   rating against 75.6 V and the 1 mm J1/J5 rule). Drop the DNP PH alternates J6/J7 if the
   GH cables work.
3. **Q301 copper.** This one sets a floor: the copper can only shrink as far as the measured
   Q301 temperature allows (or use the DPAK fallback ZXTN4004K, 33 °C/W on 50 × 50 mm).
4. **Outline and holes.** Fit to the carrier and the ENNOID master's mounting, then re-place
   H1–H4 (the 4.5 mm keep-out rule still applies).

**Measure before shrinking:**

- Balance heat: all 18 cells balancing at the chosen R2 for 30 min on the bench, no airflow.
  Log the R2 band temperature (thermocouple or IR camera), U1 die temperature (ITMP) and TH701.
  That says whether the R2 band can get denser and whether odd/even balancing is mandatory.
- Q301 temperature at full stack voltage (75.6 V) with isoSPI active.
- Whether 47 Ω's balance current is enough for the pack (the R2 value decision itself).
- Actual area used: I can print each group's courtyard bounding box from the board, so you
  can see where the space goes.
- Carrier constraints: slave pitch on the carrier, connector access from above, screw
  positions.
