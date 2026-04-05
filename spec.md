# LLUPS — Lithium Li-ion Universal Power Supply

## Overview

A compact PCB module providing regulated power from two 18650 Li-ion cells, charged via USB-C with passthrough (load-sharing) capability. Designed as a reusable power building block for downstream projects.

---

## Cell Configuration

- **Two 18650 cells in parallel (1S2P)**
  - Nominal voltage: 3.7V
  - Fully charged: 4.2V
  - Operating cutoff: 3.3V (voltage supervisor disables boost); hard safety floor: 2.8V (protection IC)
  - Combined capacity: ~5000–7000 mAh depending on cells
- Parallel simplifies charging (single-cell charger IC) and balancing is not required
- Through-hole 18650 holders with spring contacts (Keystone 1042 or equivalent)

### Why parallel and not series

A 1S2P configuration allows the use of a single-cell charger IC, avoids the need for cell balancing, and keeps the base voltage low enough that a boost stage is the natural path to 5V. Future variants that need higher output voltages (9V, 12V, etc.) simply swap or cascade the boost converter — the charging and protection subsystems remain unchanged.

### Cutoff Rationale — Two-Tier Protection

A single protection IC with a 3.0V threshold proved difficult to source affordably (most commodity protection ICs use 2.4–2.8V thresholds). Instead, the design uses a **two-tier architecture**:

1. **Voltage supervisor (LN61CN3302MR-G)** — monitors VBAT and disables the boost converter at **3.3V** via its EN pin. This is the normal operating cutoff. The 3.3V threshold was chosen to provide 300mV of margin above the protection IC's 3.0V release voltage, preventing oscillation at the threshold boundary.
2. **Protection IC (HY2113-KB5B)** — hard safety floor at **2.8V** overdischarge detection (3.0V release). Disconnects the cell entirely via dual N-FET. This should never trigger in normal operation; it exists to prevent cell damage if the supervisor fails or parasitic drain depletes the cell while idle.

This approach is both cheaper (~$0.14 combined vs ~$0.40 for a single 3.0V protection IC) and more robust (two independent protection layers).

The 3.3V operating cutoff was chosen based on:

- **Minimal capacity loss**: Only ~5–8% of rated capacity exists below 3.3V
- **Significant cycle life benefit**: ~50%+ more charge cycles compared to the datasheet floor of 2.5V
- **Boost converter practicality**: At <3.0V input, a boost to 5V at 1A demands >1.8A input at poor efficiency — the converter is already struggling
- **Industry alignment**: Quality power banks, EV battery packs, and regulated consumer electronics use 2.8–3.2V cutoffs
- **No oscillation**: The 300mV gap between the supervisor cutoff (3.3V) and the protection IC release (3.0V) ensures the boost converter stays off until the cell has charged well past the safety floor release point

---

## USB-C Input

- **USB-C receptacle** (USB 2.0 footprint, mid-mount or SMD)
- **CC1/CC2 pull-down resistors**: 5.1 kΩ each to GND — negotiates default 5V from any USB-C source
- **VBUS input range**: 4.5–5.5V (no USB-PD negotiation in v1)
- **ESD protection**: TVS diode array on VBUS and CC lines (e.g., USBLC6-2SC6)
- **Input VBUS fuse or PTC**: ~2A rated resettable fuse on VBUS

### Future: USB-PD

A future revision may add a USB-PD sink controller (e.g., FUSB302 or STUSB4500) to negotiate higher input voltages/currents for faster charging. The spec should not preclude this — route CC1/CC2 to pads or a header in addition to the pull-down resistors so a PD controller can be added in a rev.

---

## Charging

- **Charger IC**: Single-cell Li-ion charger with integrated power path / load sharing
  - Recommended: **BQ24072 / BQ24073** (TI) or **MCP73871** (Microchip)
  - These ICs manage simultaneous charging and system load from a single input
- **Charge current**: Programmable via resistor, target **1A–2A** (appropriate for 2P cells)
- **Charge termination**: CC/CV profile, 4.2V per cell, termination at C/10
- **Charge status indicators**: Two LEDs (charging / done) driven by charger IC status pins
- **NTC thermistor input**: 10 kΩ NTC placed between cells for thermal monitoring during charge; charger suspends if temperature is out of range

---

## Power Path / Passthrough

When USB-C is connected:

1. System load is powered from USB (minus charger overhead)
2. Remaining current charges the battery
3. If USB is removed, battery seamlessly takes over (no dropout, no switch glitch)

This is handled natively by the recommended charger ICs (BQ24072 has an integrated power-path FET). No additional external switch is needed.

---

## Protection

All protections apply to the parallel cell pack (treated as a single cell):

| Feature | Implementation |
|---|---|
| **Overcharge** | Charger IC terminates at 4.2V |
| **Over-discharge (operating)** | Voltage supervisor disables boost at 3.3V |
| **Over-discharge (safety)** | Protection IC, hard cutoff at 2.8V (3.0V release) |
| **Overcurrent (discharge)** | Protection IC, trip at ~4–6A |
| **Short circuit** | Protection IC, fast trip <1 ms |
| **Thermal (charge)** | NTC input on charger IC |
| **Thermal (board)** | Optional: second NTC + comparator to cut output |
| **Reverse polarity (cells)** | Mechanical keying of holders; optional series MOSFET |

- **Protection IC**: **HY2113-KB5B** (HYCON, 2.8V overdischarge detection, 3.0V release, SOT-23-6)
  - Paired with dual N-FET (FS8205 or equivalent)
  - Sits between cell negative terminal and system ground
  - Controls low-side N-FET pair for charge/discharge enable
  - Provides overcharge (4.25V), overcurrent (150mV), and short-circuit protection
- **Voltage supervisor**: **LN61CN3302MR-G** (NATLINEAR, 3.3V threshold, SOT-23-3)
  - Open-drain active-low output connects to EN net
  - When VBAT < 3.3V, output pulls low → boost converter and LDO disabled
  - When VBAT > 3.3V, output is high-Z → existing pullup on EN keeps boost running
  - 2µA quiescent current, does not meaningfully affect standby power

---

## Voltage Regulation

### 5V Rail — Boost Converter

- **Topology**: Synchronous boost (step-up)
- **Input**: 3.3–4.2V (from cell pack, post-protection; supervisor cuts off at 3.3V)
- **Output**: 5.0V ±2%
- **Current**: ≥1A continuous at 3.3V input (worst case)
- **Recommended ICs**: **TPS61023** (TI), **MT3608** (Aerosemi), or **SY8088**
- **Inductor**: Shielded power inductor, 2.2–4.7 µH, rated for peak current
- **Output capacitance**: Low-ESR ceramic, ≥22 µF on output
- **Enable pin**: Active-high, controlled by voltage supervisor (LN61C) open-drain output with pullup to VSYS. Supervisor pulls EN low when VBAT drops below 3.3V, shutting down boost and preventing deep discharge.

### 3.3V Rail — LDO from 5V

- **Input**: 5V rail (from boost)
- **Output**: 3.3V ±2%
- **Current**: ≥500 mA
- **Recommended ICs**: **AP2112K-3.3** (Diodes Inc.), **XC6220B331** (Torex), or **AMS1117-3.3**
- **Decoupling**: Per IC datasheet, typically 1 µF in + 1 µF out ceramic minimum

### Output Enable

- A single active-high **EN** signal (exposed on output header) controls the boost converter enable. When EN is low, both 5V and 3.3V rails are off and the module is in low-power standby (charger still operates). This allows an external MCU or switch to control power.

---

## Connectors and Headers

| Connector | Purpose | Pins |
|---|---|---|
| **J1** — USB-C | Charge input | VBUS, GND, CC1, CC2, shield |
| **J2** — Output header | Regulated power out | 5V, 3.3V, GND, EN, VBAT (raw) |
| **J3** — Battery sense (optional) | Debug / monitoring | VBAT, NTC, CHRG_STAT |

- **Output header pitch**: 2.54 mm (0.1") for breadboard compatibility, or 1.27 mm castellated edge pads for SMD mounting — **TBD based on form factor goals**
- **VBAT raw pin**: Direct battery voltage output (post-protection, pre-boost) for applications that want to do their own conversion

---

## Test Points

Expose the following as labeled test pads:

- VBUS (USB input)
- VBAT (battery voltage)
- 5V (boost output)
- 3.3V (LDO output)
- GND
- CHRG (charge status)

---

## Board Constraints

- **Assembly**: Designed for reflow soldering; all packages are reflow-compatible
- **Packages**: BGA, QFN, DFN all acceptable; prefer smallest suitable package
- **Layers**: 2-layer PCB (cost optimization; 4-layer if routing demands it)
- **Dimensions**: Minimize footprint; target roughly 50 mm × 30 mm excluding cell holders (TBD after layout)
- **Copper weight**: 1 oz outer layers minimum; 2 oz preferred for power traces
- **Power trace widths**: Sized for 2A+ continuous (≥1 mm for 1 oz Cu, calculator-verified)
- **Passives**: 0402 preferred for density; 0201 acceptable where needed
- **Ground plane**: Unbroken ground fill on bottom layer; via stitching to top ground where possible
- **Thermal relief**: Charger IC and boost IC thermal/exposed pads should have adequate thermal vias to ground plane
- **Mounting**: Two M2 or M2.5 mounting holes in opposite corners

---

## Design-for-Future

These are not in scope for v1, but the design should not preclude them:

1. **Higher voltage boost** — The boost converter footprint and feedback network should allow swapping to a higher-voltage part (e.g., 9V, 12V) by changing the feedback resistor divider. Consider adding a second unpopulated divider footprint.
2. **USB-PD input** — CC lines routed to breakout pads (see USB-C section).
3. **Series cell configuration (2S)** — A future board variant could use 2S with a balancing charger (e.g., BQ25887) and a buck converter instead of boost. This would be a separate PCB revision, not a BOM swap.
4. **Battery fuel gauge** — Footprint/I²C header for a fuel gauge IC (e.g., MAX17048) could be added.
5. **Load disconnect** — High-side load switch on output for hard power cut (vs. just disabling boost).

---

## BOM Philosophy

- Prefer widely available parts (LCSC / JLCPCB parts library where possible)
- Select the best-fit package for density and thermal performance — no hand-soldering constraints
- All ICs should have a second-source or pin-compatible alternative noted

---

## Success Criteria

- [ ] USB-C input charges both cells at ≥1A with thermal protection active
- [ ] Passthrough: system load runs uninterrupted when USB is connected or disconnected
- [ ] 5V output holds regulation from full charge (4.2V) down to supervisor cutoff (3.3V)
- [ ] 3.3V output stable under 500 mA load
- [ ] Voltage supervisor disables boost at 3.3V; protection IC disconnects cells at 2.8V as safety floor
- [ ] Overcurrent and short-circuit protection functional via HY2113 + FS8205
- [ ] Quiescent current in standby (EN low, no USB) < 50 µA
- [ ] Board fits within target dimensions with clean layout
