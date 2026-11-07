# Master: ENNOID Master-XLITE-ISC (bought, not designed here)

Decision 2026-11-06: the slave in `slave-18s/` works under a bought ENNOID master,
the **Master-XLITE-ISC** (supplied by a friend). This repo doesn't design a master. The
standard Master-XLITE would work the same way: it differs in connectors (JST PH 2.0 mm
instead of GH 1.25 mm), uses two-sided assembly, and adds a push-button with LED, I²C
display bus and pre-discharge/discharge outputs.

Sources:
- Pinout sheet `Master-XLITE-ISC-PINOUT.pdf` (3 pages), kept locally as
  `_reference/datasheets/ENNOID_Master-XLITE-ISC_pinout.pdf`. It is ENNOID's document, so
  it is gitignored like the other vendor datasheets and is not published.
- Product page: https://www.ennoid.me/bms/master-xlite (read 2026-11-06).

## How the system fits together

```
 charger --XT30--> [ Master-XLITE-ISC ] --XT30--> pack (BAT+ / BAT-)
                    |  charge FETs, CAN (GH 4P), Bluetooth, VESC Tool
                    |
                    +-- isoSPI (JST GH 2P, 2 wires, <= 2 m per hop)
                          |
                    [ this 18S slave ]  J3 = isoSPI A (IN, from master)
                          |             J4 = isoSPI B (OUT, to next slave)
                          +-- next slave ... (up to 20 slaves)
                          |
                    cell taps J1/J5 + NTCs J2 --> pack harness
```

- **Master** (charge only): charger and battery XT30s, the charge MOSFETs, pack and charger
  voltage, charge current, SoC/SoH, isolated CAN (default ID 10), Bluetooth, buzzer, status
  LED, auto wake/shutdown. Firmware is ENNOID's VESC-Tool-compatible BMS firmware (6.06 adds
  "Support for parallel packs and 18s slaves").
- **Slave** (this repo): measures cells, balances, reads thermistors, and passes isoSPI on.
  No pack current, no XT30s, no FETs. That's why the XT30 step was dropped on 2026-11-06.

## What the pinout sheet says that matters for the slave

| Item | ENNOID | This slave | Status |
|---|---|---|---|
| isoSPI connector | JST GH 2P on master and ENNOID 18S slaves | J3/J4 JST GH 2P vertical (BM02B-GHS-TBT, C161690), PH 2P alternates J6/J7 (DNP) | Done 2026-11-06 |
| isoSPI pin polarity | labelled on master silk (not readable in the PDF) | pin 1 = +, pin 2 = − | **Open:** confirm with the master's cable / footprint |
| Thermistor default | NTC 100 kΩ, B 4250 | 100 kΩ pull-ups + TH701 NCP18WF104F12RB (100 k, B 4250) | Matches |
| C0 | "C0 correspond to the slave negative voltage reference" | TAP0 / V− | Matches |
| Cells per slave | 3 minimum; unused top inputs bridged to the top cell (14S example: C14–C18 shorted) | 18 | OK |
| Balance connector | JST GH 13P + 6P (GH is rated 50 V) | J1/J5 JST PH 10P + 10P (PH 100 V, ≤ 37.8 V per header) | Keep PH on purpose |
| Slaves per chain | up to 20, ≤ 2 m between slaves | — | OK |

VESC Tool settings from the sheet's 32S example (14S + 18S slaves): "First monitoring IC cell
num", "Last monitoring IC cell num", "Cell num", "monitoring IC num". For one 18S slave this
should be 18 / 18 / 18 / 1 (not yet tried).

## Firmware: the ADBMS1818 should work as an LTC6813-1 (checked 2026-11-06)

Sources:
- Public source: https://github.com/EnnoidMe/ENNOID-BMS-Firmware, branch `ENNOID`
  (commit 5811327, 2022-08-24), file `Drivers/SWDrivers/Src/driverSWLTC6804.c`, plus
  `Modules/Src/modPowerElectronics.c` and `Modules/Src/modConfig.c`.
- The master's binary, `ENNOID-BMS.bin` (6.06, 99,340 bytes), kept locally as
  `_reference/firmware/ENNOID-BMS.bin`. It is ENNOID's build, so `_reference/firmware/` is
  gitignored and never published. **The binary is newer than the public source**, so the
  check below is about the source, not the exact code on the master.

The driver supports `CELL_MON_LTC6813_1` (it then also writes configuration group B and reads
cell groups E/F and aux group D). Every command code it sends was compared with ADBMS1818
Table 52 (Rev. B, p. 61–62). All match:

| Command | Firmware (CC, hex) | Table 52 |
|---|---|---|
| WRCFGA / WRCFGB / RDCFGA | 0x001 / 0x024 / 0x002 | same |
| RDCVA–F | 0x004, 0x006, 0x008, 0x00A, 0x009, 0x00B | same |
| RDAUXA–D | 0x00C, 0x00E, 0x00D, 0x00F | same |
| RDSTATA / RDSTATB | 0x010 / 0x012 | same |
| ADCV | 0x260 + MD·0x80 + DCP·0x10 + CH | same layout |
| ADOW | 0x228 + MD·0x80 + PUP·0x40 + DCP·0x10 + CH | same layout |
| ADAX | 0x460 + MD·0x80 + CHG | same layout |
| ADCVAX | 0x46F + MD·0x80 + DCP·0x10 | same layout |
| CLRCELL / CLRAUX / CLRSTAT | 0x711 / 0x712 / 0x713 | same |

The configuration bytes also line up with Tables 54/55 (GPIO1–5, REFON, ADCOPT in CFGAR0;
DCC13–16 and GPIO6–9 in CFGBR0; DCC17/18 in CFGBR1). Normal cell conversions use DCP = 0, so
balancing pauses during measurement, as the design basis asks.

**Conclusion:** no custom master firmware is expected. In VESC Tool, pick the **LTC6813-1**
cell-monitor type. The remaining proof is a bench test with one slave.

### What the firmware does with the GPIOs

- `modPowerElectronicsCellMonitorsInit()` writes **GPIO1–GPIO9 = 1** (pull-down **off**, the
  comment says "false = pull down") and leaves DCC0 = 0 (GPIO9 pull-down off). REFON = 1, so
  VREF2 stays up for the NTC pull-ups.
- Temperatures: ADAX with all channels; the driver converts the first *N* aux codes as NTCs,
  where *N* is "NTC sensors per module" in VESC Tool (default 1). Aux order is GPIO1, GPIO2,
  GPIO3 (group A), then GPIO4, GPIO5, VREF2 (group B). So **N = 4 reads GPIO1–GPIO4**, which is
  exactly this slave's three cell NTCs plus TH701. Don't set N above 4: input 5 would be
  GPIO5 (tied low, see below) and input 6 is VREF2, not a thermistor.
- Default NTC settings are 100 kΩ, B 4250, 100 kΩ pull-up: the same as the slave.
- `tempEnableMaskBattery` (default 0xFFFF) counts every aux sensor as a battery temperature.
  To treat TH701 (GPIO4, sensor index 3) as a board temperature instead, clear bit 3 there and
  set bit 4 in `tempEnableMaskBMS` (BMS sensor *k* = aux sensor *k − 1*). Try on the bench.

Because the firmware never turns the pull-downs on, the slave's unused GPIO5–9 would float.
Proposed fix in the design basis ("Configuration and unused pins"): tie them to V−.

## Open questions

- Whether the last slave's port B needs anything when nothing is plugged into J4.
- Bench test: one slave, VESC Tool set to LTC6813-1, 18 / 18 / 18 / 1, NTC sensors = 4.
