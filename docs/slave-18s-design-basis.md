# ADBMS1818 18S slave: design basis

Status: **clean-slate draft, 2026-11-04.** The schematic sheet is empty. This note records
the agreed starting values before capture.

## Scope

- One ADBMS1818 monitoring up to 18 series Li-ion cells (4.2 V max each, 75.6 V stack).
- isoSPI daisy chain: port A in, port B out (ISOMD tied to VREG).
- Passive balancing through the internal S-pin switches.
- Thermistor inputs on GPIOs.
- No power switching and no charge control. Those live in the master.

## Baseline: datasheet Figure 112 (typical application)

| Block | Value | Note |
|---|---|---|
| C-pin series resistor | 10 Ω | Per input, C0–C18. Confirmed by Racc |
| S-pin balance resistor | 33 Ω | ~110 mA at 4.2 V (see sizing) |
| C-to-S filter cap | 100 nF | Per cell |
| V+ filter | 100 Ω + 10 nF | |
| DRIVE regulator | NPN, 100 Ω collector resistor, 1 µF on VREG | |
| VREF1 / VREF2 | 1 µF each | |
| isoSPI termination | 100 Ω | Split 2 × 51 Ω with centre-tap caps (below) |
| IBIAS / ICMP | 1 kΩ + 1 kΩ divider | |
| ISOMD | to VREG | |

## Deviations from Figure 112

1. **isoSPI filtering (Racc's design):** termination split into 2 × 51 Ω with 10 nF from the
   centre point to V−, plus 10 nF on the transformer chip-side centre tap. Keeps isoSPI
   working while the motor runs.
2. **Regulator NPN in a big package.** Dissipation ≈ (V_stack − ~5.6 V) × I_reg. At 18S full
   charge (75.6 V) and an assumed 15–20 mA, that's about 1.0–1.4 W. Use SOT-223 or DPAK on
   copper, V_CEO ≥ 100 V. A SOT-23 (~0.3 W) is not enough.
3. **Thermistors:** 100 kΩ pull-up to VREF2, 100 kΩ NTC, 100 nF on the GPIO (Racc's
   arrangement). Plan 2–3 cell sensors and 1 board sensor.

## Balance resistor sizing

Assumes about 5 Ω of internal switch resistance (to be confirmed from the datasheet).

| R_S | I at 4.2 V | I at 3.7 V | P at 4.2 V |
|---|---|---|---|
| 120 Ω (Racc's board) | ~34 mA | ~30 mA | 0.15 W |
| 47 Ω | ~81 mA | ~71 mA | 0.31 W |
| 39 Ω | ~95 mA | ~84 mA | 0.35 W |
| **33 Ω (Fig. 112)** | **~110 mA** | **~97 mA** | **0.40 W** |

- 0.4 W needs a 2512 (1 W) or two 1206s in parallel (2 × 68 Ω).
- All 18 balancing at once is about 7 W on the board. Firmware should balance odd and even
  cells alternately, or the layout needs copper for heat spreading.

## Open items

- [ ] Build the ADBMS1818 symbol from the datasheet pin table (64-LQFP). KiCad's stock
      library has none.
- [ ] Confirm internal switch on-resistance, maximum balance current per switch, and the
      die thermal limit. Above the limit, use external balance MOSFETs.
- [ ] Confirm VREG current in measure mode to finalise NPN dissipation.
- [ ] Choose the NPN (≥ 100 V, SOT-223/DPAK).
- [ ] Choose the isoSPI transformer (isolation ≥ module-to-module voltage, known pinout).
- [ ] Hot-plug protection for the plug-and-play harness (connector pin order, per-cell clamps).
- [ ] Connector and harness pinout matched to the Funwheel pack.
- [ ] Board outline (the current 120 × 70 mm rectangle is a placeholder).
