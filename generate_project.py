#!/usr/bin/env python3
"""Generate LLUPS KiCad 9 project files from spec."""
import uuid, json, os, re, sys

KICAD_SYM_DIR = "/usr/share/kicad/symbols"
PROJECT_DIR = "/home/jason/Documents/LLUPS"
PROJECT_NAME = "LLUPS"
ROOT_UUID = str(uuid.uuid4())

def uid():
    return str(uuid.uuid4())

# ============================================================
# Symbol extraction from KiCad libraries
# ============================================================
def extract_symbol(lib_path, sym_name):
    with open(lib_path) as f:
        text = f.read()
    for marker in [f'\n\t(symbol "{sym_name}"\n', f'\n\t(symbol "{sym_name}"']:
        pos = text.find(marker)
        if pos != -1:
            break
    else:
        print(f"WARNING: {sym_name} not found in {lib_path}", file=sys.stderr)
        return None
    pos += 1
    depth = 0
    for i in range(pos, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[pos:i+1]
    return None

def qualify_symbol(raw, sym_name, lib_prefix):
    q = raw.replace(f'(symbol "{sym_name}"', f'(symbol "{lib_prefix}:{sym_name}"', 1)
    return q

def get_extends_base(raw):
    m = re.search(r'\(extends "([^"]+)"\)', raw)
    return m.group(1) if m else None

def extract_properties(sym_text):
    """Extract all top-level (property ...) blocks from a symbol."""
    props = {}
    i = 0
    while True:
        idx = sym_text.find('(property "', i)
        if idx == -1:
            break
        name_start = idx + len('(property "')
        name_end = sym_text.find('"', name_start)
        name = sym_text[name_start:name_end]
        depth = 0
        for j in range(idx, len(sym_text)):
            if sym_text[j] == '(':
                depth += 1
            elif sym_text[j] == ')':
                depth -= 1
                if depth == 0:
                    props[name] = sym_text[idx:j+1]
                    i = j + 1
                    break
        else:
            break
    return props

def resolve_extends(lib_path, sym_name, base_name):
    """Resolve an 'extends' symbol by merging base graphics with derived properties."""
    base_raw = extract_symbol(lib_path, base_name)
    derived_raw = extract_symbol(lib_path, sym_name)
    if base_raw is None or derived_raw is None:
        return None
    # Take base symbol and rename all occurrences of base name to derived name
    resolved = base_raw.replace(base_name, sym_name)
    # Replace properties with derived symbol's properties
    derived_props = extract_properties(derived_raw)
    resolved_props = extract_properties(resolved)
    for name, prop_text in derived_props.items():
        if name in resolved_props:
            resolved = resolved.replace(resolved_props[name], prop_text)
    return resolved

CUSTOM_SYMBOLS = {
    "Battery_Management:HY2113": '''(symbol "Battery_Management:HY2113"
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(property "Reference" "U"
			(at -7.62 6.35 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify left)
			)
		)
		(property "Value" "HY2113"
			(at 7.62 6.35 0)
			(effects
				(font
					(size 1.27 1.27)
				)
			)
		)
		(property "Footprint" "Package_TO_SOT_SMD:SOT-23-6"
			(at 0 0 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Datasheet" "https://www.hycontek.com/wp-content/uploads/DS-HY2113_EN.pdf"
			(at 0 1.27 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Description" "1-Cell Li-ion/Li-Polymer Battery Protection IC, SOT-23-6"
			(at 0 0 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "ki_keywords" "battery protection li-ion li-po hycon"
			(at 0 0 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(symbol "HY2113_0_1"
			(rectangle
				(start -7.62 5.08)
				(end 7.62 -5.08)
				(stroke
					(width 0.254)
					(type default)
				)
				(fill
					(type background)
				)
			)
		)
		(symbol "HY2113_1_1"
			(pin output line
				(at 10.16 2.54 180)
				(length 2.54)
				(name "OD"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "1"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
			(pin passive line
				(at -10.16 0 0)
				(length 2.54)
				(name "CS"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "2"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
			(pin output line
				(at 10.16 -2.54 180)
				(length 2.54)
				(name "OC"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "3"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
			(pin passive line
				(at -7.62 -2.54 0)
				(length 0)
				(name "NC"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "4"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
			(pin power_in line
				(at 0 7.62 270)
				(length 2.54)
				(name "VDD"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "5"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
			(pin power_in line
				(at 0 -7.62 90)
				(length 2.54)
				(name "VSS"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "6"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
		)
	)''',
    "Supervisor:LN61C": '''(symbol "Supervisor:LN61C"
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(property "Reference" "U"
			(at -5.08 5.08 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(justify left)
			)
		)
		(property "Value" "LN61C"
			(at 5.08 5.08 0)
			(effects
				(font
					(size 1.27 1.27)
				)
			)
		)
		(property "Footprint" "Package_TO_SOT_SMD:SOT-23-3"
			(at 0 0 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Datasheet" ""
			(at 0 0 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Description" "Voltage Detector, Active-Low Open Drain Output, SOT-23-3"
			(at 0 0 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "ki_keywords" "voltage detector supervisor reset"
			(at 0 0 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(symbol "LN61C_0_1"
			(rectangle
				(start -5.08 3.81)
				(end 5.08 -3.81)
				(stroke
					(width 0.254)
					(type default)
				)
				(fill
					(type background)
				)
			)
		)
		(symbol "LN61C_1_1"
			(pin power_in line
				(at 0 7.62 270)
				(length 3.81)
				(name "VDD"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "1"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
			(pin power_in line
				(at 0 -7.62 90)
				(length 3.81)
				(name "GND"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "2"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
			(pin open_collector line
				(at 7.62 0 180)
				(length 2.54)
				(name "OUT"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
				(number "3"
					(effects
						(font
							(size 1.27 1.27)
						)
					)
				)
			)
		)
	)''',
}

def collect_lib_symbols(needed):
    """needed: list of (lib_prefix, sym_name)"""
    results = []
    seen = set()
    for lib_prefix, sym_name in needed:
        key = f"{lib_prefix}:{sym_name}"
        if key in seen:
            continue
        # Check custom symbols first
        if key in CUSTOM_SYMBOLS:
            results.append(CUSTOM_SYMBOLS[key])
            seen.add(key)
            continue
        lib_path = os.path.join(KICAD_SYM_DIR, f"{lib_prefix}.kicad_sym")
        raw = extract_symbol(lib_path, sym_name)
        if raw is None:
            continue
        base = get_extends_base(raw)
        if base:
            # Resolve extends: merge base graphics with derived properties
            resolved = resolve_extends(lib_path, sym_name, base)
            if resolved:
                results.append(qualify_symbol(resolved, sym_name, lib_prefix))
                seen.add(key)
            continue
        results.append(qualify_symbol(raw, sym_name, lib_prefix))
        seen.add(key)
    return results

# ============================================================
# Pin data (connection point positions relative to symbol origin)
# ============================================================
PIN_DATA = {
    "Connector:USB_C_Receptacle_USB2.0_16P": {
        "A4": (15.24, 15.24), "A9": (15.24, 15.24),
        "B4": (15.24, 15.24), "B9": (15.24, 15.24),
        "A5": (15.24, 10.16), "B5": (15.24, 7.62),
        "A7": (15.24, 2.54), "B7": (15.24, 0),
        "A6": (15.24, -2.54), "B6": (15.24, -5.08),
        "A8": (15.24, -12.7), "B8": (15.24, -15.24),
        "A1": (0, -22.86), "A12": (0, -22.86),
        "B1": (0, -22.86), "B12": (0, -22.86),
        "S1": (-7.62, -22.86),
    },
    "Power_Protection:USBLC6-2SC6": {
        "1": (-5.08, 0), "3": (-5.08, -2.54), "5": (0, 5.08),
        "2": (0, -7.62), "6": (5.08, 0), "4": (5.08, -2.54),
    },
    "Device:Fuse": {"1": (0, 3.81), "2": (0, -3.81)},
    "Device:R": {"1": (0, 3.81), "2": (0, -3.81)},
    "Device:C": {"1": (0, 3.81), "2": (0, -3.81)},
    "Device:L": {"1": (0, 3.81), "2": (0, -3.81)},
    "Device:LED": {"1": (-3.81, 0), "2": (3.81, 0)},
    "Device:D_Schottky": {"1": (-3.81, 0), "2": (3.81, 0)},
    "Device:Battery_Cell": {"1": (0, 5.08), "2": (0, -2.54)},
    "Device:Thermistor_NTC": {"1": (0, 3.81), "2": (0, -3.81)},
    "Battery_Management:BQ24072RGT": {
        "13": (0, 15.24), "10": (12.7, 10.16), "11": (12.7, 10.16),
        "2": (12.7, 2.54), "3": (12.7, 2.54),
        "1": (12.7, -2.54), "7": (12.7, -7.62), "9": (12.7, -10.16),
        "8": (0, -15.24), "17": (0, -15.24),
        "15": (-12.7, 10.16), "4": (-12.7, 5.08), "14": (-12.7, 2.54),
        "6": (-12.7, 0), "5": (-12.7, -2.54),
        "12": (-12.7, -7.62), "16": (-12.7, -10.16),
    },
    "Battery_Management:HY2113": {
        "1": (10.16, 2.54), "2": (-10.16, 0), "3": (10.16, -2.54),
        "4": (-7.62, -2.54), "5": (0, 7.62), "6": (0, -7.62),
    },
    "Supervisor:LN61C": {
        "1": (0, 7.62), "2": (0, -7.62), "3": (7.62, 0),
    },
    "Transistor_FET:Q_Dual_NMOS_S1G1D2S2G2D1": {
        "2": (-5.08, 0), "6": (2.54, 5.08), "1": (2.54, -5.08),
        "5": (-5.08, 0), "3": (2.54, 5.08), "4": (2.54, -5.08),
    },
    "Regulator_Switching:MT3608": {
        "5": (-7.62, 2.54), "4": (-7.62, -2.54), "2": (0, -7.62),
        "1": (7.62, 2.54), "3": (7.62, -2.54), "6": (5.08, 0),
    },
    "Regulator_Linear:AP2112K-3.3": {
        "1": (-7.62, 2.54), "3": (-7.62, 0), "2": (0, -7.62),
        "5": (7.62, 2.54), "4": (5.08, 0),
    },
    "Connector_Generic:Conn_01x05": {
        "1": (-5.08, 5.08), "2": (-5.08, 2.54), "3": (-5.08, 0),
        "4": (-5.08, -2.54), "5": (-5.08, -5.08),
    },
    "Connector_Generic:Conn_01x03": {
        "1": (-5.08, 2.54), "2": (-5.08, 0), "3": (-5.08, -2.54),
    },
    "power:GND": {"1": (0, 0)},
    "power:+5V": {"1": (0, 0)},
    "power:+3V3": {"1": (0, 0)},
    "power:PWR_FLAG": {"1": (0, 0)},
}

# Pin-to-unit mapping for multi-unit symbols
PIN_UNIT = {
    "Transistor_FET:Q_Dual_NMOS_S1G1D2S2G2D1": {
        "1": 1, "2": 1, "6": 1,
        "3": 2, "4": 2, "5": 2,
    }
}

# All pin numbers per lib_id (for symbol instance pin entries)
ALL_PINS = {
    "Connector:USB_C_Receptacle_USB2.0_16P": [
        "A1","A4","A5","A6","A7","A8","A9","A12",
        "B1","B4","B5","B6","B7","B8","B9","B12","S1"
    ],
    "Power_Protection:USBLC6-2SC6": ["1","2","3","4","5","6"],
    "Device:Fuse": ["1","2"],
    "Device:R": ["1","2"],
    "Device:C": ["1","2"],
    "Device:L": ["1","2"],
    "Device:LED": ["1","2"],
    "Device:D_Schottky": ["1","2"],
    "Device:Battery_Cell": ["1","2"],
    "Device:Thermistor_NTC": ["1","2"],
    "Battery_Management:BQ24072RGT": [str(i) for i in range(1,18)],
    "Battery_Management:HY2113": ["1","2","3","4","5","6"],
    "Supervisor:LN61C": ["1","2","3"],
    "Transistor_FET:Q_Dual_NMOS_S1G1D2S2G2D1": ["1","2","3","4","5","6"],
    "Regulator_Switching:MT3608": ["1","2","3","4","5","6"],
    "Regulator_Linear:AP2112K-3.3": ["1","2","3","4","5"],
    "Connector_Generic:Conn_01x05": ["1","2","3","4","5"],
    "Connector_Generic:Conn_01x03": ["1","2","3"],
    "power:GND": ["1"],
    "power:+5V": ["1"],
    "power:+3V3": ["1"],
    "power:PWR_FLAG": ["1"],
}

# Pins belonging to each unit (for multi-unit symbols)
UNIT_PINS = {
    "Transistor_FET:Q_Dual_NMOS_S1G1D2S2G2D1": {
        1: ["1","2","6"],
        2: ["3","4","5"],
    }
}

# ============================================================
# Component placements: (ref, lib_id, value, footprint, x, y, rot, unit)
# Positions designed for clean wire routing within sections.
# ============================================================
PLACEMENTS = [
    # --- USB INPUT (x: 25-105, y: 50-130) ---
    ("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB_C", "Connector_USB:USB_C_Receptacle_GCT_USB4085", 38, 80, 0, 1),
    ("F1", "Device:Fuse", "2A_PTC", "Fuse:Fuse_0805_2012Metric", 64.67, 64.76, 270, 1),
    ("C1", "Device:C", "10u", "Capacitor_SMD:C_0805_2012Metric", 80, 52, 0, 1),
    ("U1", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", 80, 82, 0, 1),
    ("R1", "Device:R", "5.1k", "Resistor_SMD:R_0402_1005Metric", 96, 90, 0, 1),
    ("R2", "Device:R", "5.1k", "Resistor_SMD:R_0402_1005Metric", 96, 100, 0, 1),
    # --- CHARGER (x: 120-220, y: 50-130) ---
    ("U2", "Battery_Management:BQ24072RGT", "BQ24072", "Package_DFN_QFN:VQFN-16-1EP_3.5x3.5mm_P0.5mm_EP2.1x2.1mm", 165, 100, 0, 1),
    ("C2", "Device:C", "4.7u", "Capacitor_SMD:C_0402_1005Metric", 155, 77, 0, 1),
    ("C3", "Device:C", "4.7u", "Capacitor_SMD:C_0402_1005Metric", 192, 86, 0, 1),
    ("C4", "Device:C", "4.7u", "Capacitor_SMD:C_0402_1005Metric", 192, 100, 0, 1),
    ("R3", "Device:R", "1k", "Resistor_SMD:R_0402_1005Metric", 140, 110.16, 90, 1),
    ("R4", "Device:R", "1.5k", "Resistor_SMD:R_0402_1005Metric", 140, 107.62, 90, 1),
    ("R5", "Device:R", "10k", "Resistor_SMD:R_0402_1005Metric", 140, 97.46, 90, 1),
    ("D1", "Device:LED", "CHG", "LED_SMD:LED_0603_1608Metric", 190, 110.16, 0, 1),
    ("D2", "Device:LED", "PGOOD", "LED_SMD:LED_0603_1608Metric", 190, 107.62, 0, 1),
    ("R6", "Device:R", "1k", "Resistor_SMD:R_0402_1005Metric", 205, 110.16, 90, 1),
    ("R7", "Device:R", "1k", "Resistor_SMD:R_0402_1005Metric", 205, 107.62, 90, 1),
    ("R8", "Device:R", "10k", "Resistor_SMD:R_0402_1005Metric", 192, 110, 0, 1),
    # --- BATTERY + PROTECTION (x: 240-370, y: 50-170) ---
    ("BT1", "Device:Battery_Cell", "18650", "Battery:BatteryHolder_Keystone_1042_1x18650", 260, 70, 0, 1),
    ("BT2", "Device:Battery_Cell", "18650", "Battery:BatteryHolder_Keystone_1042_1x18650", 280, 70, 0, 1),
    ("RT1", "Device:Thermistor_NTC", "10k_NTC", "Resistor_SMD:R_0402_1005Metric", 270, 100, 0, 1),
    ("U3", "Battery_Management:HY2113", "HY2113-KB5B", "Package_TO_SOT_SMD:SOT-23-6", 300, 130, 0, 1),
    ("U6", "Supervisor:LN61C", "LN61CN3302MR-G", "Package_TO_SOT_SMD:SOT-23-3", 300, 165, 0, 1),
    ("Q1", "Transistor_FET:Q_Dual_NMOS_S1G1D2S2G2D1", "FS8205A", "Package_TO_SOT_SMD:SOT-23-6", 340, 115, 0, 1),
    ("Q1", "Transistor_FET:Q_Dual_NMOS_S1G1D2S2G2D1", "FS8205A", "Package_TO_SOT_SMD:SOT-23-6", 340, 145, 0, 2),
    # --- BOOST 5V (x: 120-230, y: 190-280) ---
    ("U4", "Regulator_Switching:MT3608", "MT3608", "Package_TO_SOT_SMD:SOT-23-6", 175, 245, 0, 1),
    ("L1", "Device:L", "4.7u", "Inductor_SMD:L_0805_2012Metric", 175, 230, 270, 1),
    ("D3", "Device:D_Schottky", "SS14", "Diode_SMD:D_SMA", 200, 237.46, 180, 1),
    ("C5", "Device:C", "10u", "Capacitor_SMD:C_0805_2012Metric", 155, 250, 0, 1),
    ("C6", "Device:C", "22u", "Capacitor_SMD:C_0805_2012Metric", 220, 250, 0, 1),
    ("R9", "Device:R", "75k", "Resistor_SMD:R_0402_1005Metric", 210, 250, 0, 1),
    ("R10", "Device:R", "10k", "Resistor_SMD:R_0402_1005Metric", 210, 262, 0, 1),
    ("R11", "Device:R", "100k", "Resistor_SMD:R_0402_1005Metric", 155, 260, 0, 1),
    # --- LDO 3.3V + OUTPUT (x: 240-390, y: 190-280) ---
    ("U5", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", 290, 240, 0, 1),
    ("C7", "Device:C", "1u", "Capacitor_SMD:C_0402_1005Metric", 275, 258, 0, 1),
    ("C8", "Device:C", "1u", "Capacitor_SMD:C_0402_1005Metric", 310, 258, 0, 1),
    ("J2", "Connector_Generic:Conn_01x05", "Output", "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical", 365, 240, 0, 1),
    ("J3", "Connector_Generic:Conn_01x03", "Debug", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical", 365, 275, 0, 1),
]

# ============================================================
# GND connections: (ref, pin_num) - will get GND power symbols
# ============================================================
GND_PINS = [
    ("J1","A1"), ("J1","S1"), ("U1","2"), ("R1","2"), ("R2","2"), ("C1","2"),
    ("U2","8"), ("C2","2"), ("C3","2"), ("C4","2"),
    ("R3","2"), ("R4","2"), ("R5","2"), ("RT1","2"),
    ("U3","2"), ("U6","2"), ("Q1","1"),
    ("U4","2"), ("C5","2"), ("C6","2"), ("R10","2"),
    ("U5","2"), ("C7","2"), ("C8","2"), ("J2","3"),
]

# No-connect pins
NC_PINS = [
    ("J1","A6"), ("J1","B6"), ("J1","A7"), ("J1","B7"),
    ("J1","A8"), ("J1","B8"),
    ("U2","15"),
    ("U2","4"),  # CE - tie high via pull-up or leave NC
    ("U3","4"),
    ("U4","6"),
    ("U5","4"),
]

# ============================================================
# Wire connections: explicit pin-to-pin wires within sections
# Each: (ref1, pin1, ref2, pin2)
# Code will route L-shaped wires between the pin positions.
# ============================================================
WIRE_PAIRS = [
    # --- USB INPUT ---
    ("J1", "A4", "F1", "1"),       # VBUS_RAW: USB VBUS → fuse input
    ("J1", "A5", "U1", "1"),       # CC1: USB CC1 → ESD I/O1 in
    ("U1", "6", "R1", "1"),        # CC1: ESD I/O1 out → pulldown top
    ("J1", "B5", "U1", "3"),       # CC2: USB CC2 → ESD I/O2 in
    ("U1", "4", "R2", "1"),        # CC2: ESD I/O2 out → pulldown top
    # --- CHARGER config resistors (left side of U2) ---
    ("R3", "1", "U2", "16"),       # ISET: resistor → charger ISET pin
    ("R4", "1", "U2", "12"),       # ILIM: resistor → charger ILIM pin
    ("R5", "1", "U2", "14"),       # TMR: resistor → charger TMR pin
    # --- CHARGER LED circuits (right side of U2) ---
    ("U2", "9", "D1", "1"),        # CHG status → LED cathode
    ("D1", "2", "R6", "2"),        # LED anode → resistor
    ("U2", "7", "D2", "1"),        # PGOOD → LED cathode
    ("D2", "2", "R7", "2"),        # LED anode → resistor
    # --- CHARGER caps ---
    ("U2", "13", "C2", "1"),       # IN pin → input cap
    ("U2", "10", "C3", "1"),       # SYS → sys cap
    ("U2", "2", "C4", "1"),        # BAT → bat cap
    # --- BATTERY ---
    ("BT1", "1", "BT2", "1"),      # Battery + terminals together
    ("BT1", "2", "BT2", "2"),      # Battery - terminals together
    # --- PROTECTION ---
    ("U3", "1", "Q1", "2"),        # DO gate signal
    ("U3", "3", "Q1", "5"),        # CO gate signal
    # --- BOOST converter ---
    ("U4", "5", "L1", "1"),        # VIN → inductor pin1 (VSYS_BOOST bus)
    ("L1", "2", "U4", "1"),        # Inductor pin2 → SW pin (SW bus)
    ("U4", "3", "R9", "2"),        # FB pin → divider midpoint
    ("R9", "2", "R10", "1"),       # FB divider: top R bottom → bottom R top
    # --- LDO ---
    ("U5", "5", "C8", "1"),        # 3.3V output → output cap
    ("U5", "1", "C7", "1"),        # LDO input → input cap
]

# ============================================================
# Multi-segment wire routes for complex connections
# Each: list of (x, y) waypoints — wires drawn between consecutive pairs
# ============================================================
def build_complex_wires():
    """Build wire segments and junctions for nets that need multi-point routing.
    Returns (segments, junctions) where segments are (x1,y1,x2,y2) and junctions are (x,y)."""
    segments = []
    junctions = []

    def bus_with_stubs(bus_y, points):
        """Create a horizontal bus at bus_y connecting multiple points.
        points: list of (x, y) pin positions. Generates bus segments between
        consecutive x-sorted points, plus vertical stubs to off-bus pins.
        Adds junctions at interior T-connections."""
        sorted_pts = sorted(points, key=lambda p: p[0])
        # Draw bus segments between consecutive x positions
        for i in range(len(sorted_pts) - 1):
            x1 = sorted_pts[i][0]
            x2 = sorted_pts[i+1][0]
            if abs(x2 - x1) > 0.01:
                segments.append((x1, bus_y, x2, bus_y))
        # Draw vertical stubs and track which x positions have stubs
        stub_xs = set()
        for i, (px, py) in enumerate(sorted_pts):
            if abs(py - bus_y) > 0.01:
                segments.append((px, bus_y, px, py))
                stub_xs.add(i)
        # Add junctions at any point where 3+ wires meet:
        # - Interior bus points always need junctions if they have stubs
        # - Endpoint bus points need junctions if 2+ stubs share same x
        for i, (px, py) in enumerate(sorted_pts):
            if i in stub_xs and 0 < i < len(sorted_pts) - 1:
                junctions.append((px, bus_y))
        # Check endpoints: if multiple points share same x at an endpoint,
        # they create multiple stubs that need a junction
        for endpoint_i in [0, len(sorted_pts) - 1]:
            ex = sorted_pts[endpoint_i][0]
            stubs_at_endpoint = sum(1 for i, (px, py) in enumerate(sorted_pts)
                                    if abs(px - ex) < 0.01 and abs(py - bus_y) > 0.01)
            if stubs_at_endpoint >= 2:
                junctions.append((ex, bus_y))

    # VBUS bus in USB section: F1.2 → C1.1 → U1.5
    f1_2 = get_pin_pos("F1", "2")
    c1_1 = get_pin_pos("C1", "1")
    u1_5 = get_pin_pos("U1", "5")
    if f1_2 and c1_1 and u1_5:
        bus_with_stubs(f1_2[1], [f1_2, c1_1, u1_5])

    # SW node: L1.2 → U4.1 → D3.2
    l1_2 = get_pin_pos("L1", "2")
    u4_1 = get_pin_pos("U4", "1")
    d3_2 = get_pin_pos("D3", "2")
    if l1_2 and u4_1 and d3_2:
        sw_y = u4_1[1]
        bus_with_stubs(sw_y, [l1_2, u4_1, d3_2])

    # VSYS_BOOST bus: U4.5 → C5.1 → L1.1
    u4_5 = get_pin_pos("U4", "5")
    c5_1 = get_pin_pos("C5", "1")
    l1_1 = get_pin_pos("L1", "1")
    if u4_5 and c5_1 and l1_1:
        bus_with_stubs(u4_5[1], [u4_5, c5_1, l1_1])

    # 5V bus: D3.1 → R9.1 → C6.1
    d3_1 = get_pin_pos("D3", "1")
    c6_1 = get_pin_pos("C6", "1")
    r9_1 = get_pin_pos("R9", "1")
    if d3_1 and c6_1 and r9_1:
        bus_with_stubs(d3_1[1], [d3_1, r9_1, c6_1])

    # EN: U4.4 → R11.2
    u4_4 = get_pin_pos("U4", "4")
    r11_2 = get_pin_pos("R11", "2")
    if u4_4 and r11_2:
        segments.append((u4_4[0], u4_4[1], r11_2[0], u4_4[1]))
        segments.append((r11_2[0], u4_4[1], r11_2[0], r11_2[1]))

    # CELL_NEG extensions: BT2.2 → U3.6(VSS), U3.6→Q1.4
    # HY2113 VSS (pin 6) connects to cell negative for voltage monitoring
    bt2_2 = get_pin_pos("BT2", "2")
    u3_6 = get_pin_pos("U3", "6")
    q1_4 = get_pin_pos("Q1", "4")
    if bt2_2 and u3_6:
        segments.append((bt2_2[0], bt2_2[1], u3_6[0], bt2_2[1]))
        segments.append((u3_6[0], bt2_2[1], u3_6[0], u3_6[1]))
    if u3_6 and q1_4:
        segments.append((u3_6[0], u3_6[1], q1_4[0], u3_6[1]))
        segments.append((q1_4[0], u3_6[1], q1_4[0], q1_4[1]))

    # DRAIN_MID: Q1.6(unit1) → Q1.3(unit2)
    q1_6 = get_pin_pos("Q1", "6")
    q1_3 = get_pin_pos("Q1", "3")
    if q1_6 and q1_3:
        segments.append((q1_6[0], q1_6[1], q1_3[0], q1_3[1]))

    return segments, junctions

# ============================================================
# Net labels — placed at pins for cross-section connectivity
# and for complex nets where wiring everything isn't practical.
# (net_name, ref, pin) — label positioned at pin, angle auto-computed
# ============================================================
LABEL_PINS = [
    # VBUS: USB section ↔ Charger section
    ("VBUS", "F1", "2"),         # USB side (on wire, acts as bus label)
    ("VBUS", "C2", "1"),         # Charger side (charger input cap)
    # VSYS: scattered across charger, use labels everywhere
    ("VSYS", "U2", "10"),        # SYS output
    ("VSYS", "U2", "11"),        # SYS output (duplicate pad)
    ("VSYS", "U2", "5"),         # OUT1
    ("VSYS", "U2", "6"),         # OUT2
    ("VSYS", "C3", "1"),         # SYS cap (wired to U2.10, but label for clarity)
    ("VSYS", "R6", "1"),         # CHG LED current source
    ("VSYS", "R7", "1"),         # PGOOD LED current source
    ("VSYS", "R11", "1"),        # EN pulldown (Boost section)
    # VBAT: Charger ↔ Battery ↔ Output
    ("VBAT", "U2", "2"),         # Charger BAT output
    ("VBAT", "U2", "3"),         # Charger BAT output (dup)
    ("VBAT", "C4", "1"),         # BAT cap (wired to U2.2)
    ("VBAT", "R8", "1"),         # NTC bias resistor top
    ("VBAT", "U3", "5"),         # Protection IC VDD
    ("VBAT", "BT1", "1"),        # Battery + (wired to BT2.1)
    ("VBAT", "J2", "5"),         # Output header VBAT
    ("VBAT", "J3", "1"),         # Debug header VBAT
    # NTC_SENSE: Charger ↔ Battery ↔ Output
    ("NTC_SENSE", "U2", "1"),    # Charger TS pin
    ("NTC_SENSE", "R8", "2"),    # NTC bias midpoint
    ("NTC_SENSE", "RT1", "1"),   # NTC thermistor
    ("NTC_SENSE", "J3", "2"),    # Debug header NTC
    # CELL_NEG: within Battery section (labels + wires)
    ("CELL_NEG", "BT1", "2"),    # Battery - (wired to BT2.2)
    # VBAT label on voltage supervisor VDD
    ("VBAT", "U6", "1"),         # Voltage supervisor VDD (monitors battery)
    # EN label on voltage supervisor output
    ("EN", "U6", "3"),           # Voltage supervisor output → EN net
    # 5V: Boost ↔ LDO ↔ Output
    ("5V", "D3", "1"),           # Boost output (on 5V wire bus)
    ("5V", "U5", "1"),           # LDO input (wired to C7.1)
    ("5V", "C7", "1"),           # LDO input cap
    ("5V", "J2", "1"),           # Output header 5V
    # 3V3: LDO ↔ Output
    ("3V3", "U5", "5"),          # LDO output (wired to C8.1)
    ("3V3", "J2", "2"),          # Output header 3.3V
    # EN: Boost ↔ LDO ↔ Output
    ("EN", "U4", "4"),           # Boost EN pin (wired to R11.2)
    ("EN", "U5", "3"),           # LDO EN pin
    ("EN", "J2", "4"),           # Output header EN
    # CHG_N: Charger → Output
    ("CHG_N", "U2", "9"),        # Charger stat (wired to D1.1)
    ("CHG_N", "J3", "3"),        # Debug header
    # VSYS_BOOST: internal to Boost (bus label)
    ("VSYS_BOOST", "U4", "5"),
    ("VSYS_BOOST", "C5", "1"),
    ("VSYS_BOOST", "L1", "1"),
]

# ============================================================
# Position computation
# ============================================================
def pin_abs_correct(lib_id, pin_num, sx, sy, rot):
    pd = PIN_DATA.get(lib_id, {})
    if pin_num not in pd:
        return None
    px, py = pd[pin_num]
    # Symbol pin coords are Y-UP, schematic coords are Y-DOWN: negate py
    if rot == 0:
        return (round(sx + px, 2), round(sy - py, 2))
    elif rot == 90:
        return (round(sx + py, 2), round(sy + px, 2))
    elif rot == 180:
        return (round(sx - px, 2), round(sy + py, 2))
    elif rot == 270:
        return (round(sx - py, 2), round(sy - px, 2))
    return (round(sx + px, 2), round(sy - py, 2))

def find_placement(ref, pin_num):
    """Find the correct placement for a pin (handles multi-unit symbols)."""
    for p in PLACEMENTS:
        if p[0] != ref:
            continue
        lib_id = p[1]
        unit = p[7]
        unit_map = PIN_UNIT.get(lib_id, {})
        if unit_map:
            pin_unit = unit_map.get(pin_num, 1)
            if unit == pin_unit:
                return p
        else:
            return p
    return None

def get_pin_pos(ref, pin_num):
    """Get absolute position of a pin."""
    p = find_placement(ref, pin_num)
    if p is None:
        return None
    return pin_abs_correct(p[1], pin_num, p[4], p[5], p[6])

def label_angle(lib_id, pin_num, comp_rot):
    """Determine label angle based on effective pin direction."""
    pd = PIN_DATA.get(lib_id, {})
    if pin_num not in pd:
        return 0
    px, py = pd[pin_num]
    # Determine which side the pin is on after rotation (negate py for Y-UP→Y-DOWN)
    if comp_rot == 0:
        epx, epy = px, -py
    elif comp_rot == 90:
        epx, epy = py, px
    elif comp_rot == 180:
        epx, epy = -px, py
    elif comp_rot == 270:
        epx, epy = -py, -px
    else:
        epx, epy = px, -py
    # Label extends away from component center (in schematic Y-DOWN coords)
    if abs(epx) >= abs(epy):
        return 0 if epx > 0 else 180
    else:
        return 90 if epy > 0 else 270

def route_two_pins(p1, p2):
    """Generate L-shaped wire segments connecting two pin positions.
    Returns list of (x1, y1, x2, y2) wire segments."""
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = abs(x2 - x1), abs(y2 - y1)
    if dx < 0.01 and dy < 0.01:
        return []
    if dx < 0.01 or dy < 0.01:
        return [(x1, y1, x2, y2)]
    # L-shaped: horizontal first if pins are more horizontal, else vertical first
    if dx >= dy:
        return [(x1, y1, x2, y1), (x2, y1, x2, y2)]
    else:
        return [(x1, y1, x1, y2), (x1, y2, x2, y2)]

# ============================================================
# Schematic S-expression generation
# ============================================================
def fmt(v):
    """Format a number for KiCad output."""
    if isinstance(v, int):
        return str(v)
    if v == int(v):
        return str(int(v))
    return f"{v:.4f}".rstrip('0').rstrip('.')

def gen_symbol_instance(ref, lib_id, value, footprint, x, y, rot, unit):
    """Generate a symbol placement S-expression."""
    lines = []
    lines.append(f'\t(symbol')
    lines.append(f'\t\t(lib_id "{lib_id}")')
    lines.append(f'\t\t(at {fmt(x)} {fmt(y)} {rot})')
    lines.append(f'\t\t(unit {unit})')
    lines.append(f'\t\t(exclude_from_sim no)')
    lines.append(f'\t\t(in_bom yes)')
    lines.append(f'\t\t(on_board yes)')
    lines.append(f'\t\t(dnp no)')
    lines.append(f'\t\t(uuid "{uid()}")')
    ry = y - 5 if rot in (0, 180) else y
    rx = x if rot in (0, 180) else x - 5
    is_pwr = lib_id.startswith("power:")
    ref_prefix = "#PWR" if is_pwr else ref
    lines.append(f'\t\t(property "Reference" "{ref_prefix}"')
    lines.append(f'\t\t\t(at {fmt(rx)} {fmt(ry)} 0)')
    if is_pwr:
        lines.append(f'\t\t\t(effects (font (size 1.27 1.27)) (hide yes))')
    else:
        lines.append(f'\t\t\t(effects (font (size 1.27 1.27)))')
    lines.append(f'\t\t)')
    vy = y + 5 if rot in (0, 180) else y
    vx = x if rot in (0, 180) else x + 5
    lines.append(f'\t\t(property "Value" "{value}"')
    lines.append(f'\t\t\t(at {fmt(vx)} {fmt(vy)} 0)')
    lines.append(f'\t\t\t(effects (font (size 1.27 1.27)))')
    lines.append(f'\t\t)')
    lines.append(f'\t\t(property "Footprint" "{footprint}"')
    lines.append(f'\t\t\t(at {fmt(x)} {fmt(y)} 0)')
    lines.append(f'\t\t\t(effects (font (size 1.27 1.27)) (hide yes))')
    lines.append(f'\t\t)')
    lines.append(f'\t\t(property "Datasheet" ""')
    lines.append(f'\t\t\t(at {fmt(x)} {fmt(y)} 0)')
    lines.append(f'\t\t\t(effects (font (size 1.27 1.27)) (hide yes))')
    lines.append(f'\t\t)')
    lines.append(f'\t\t(property "Description" ""')
    lines.append(f'\t\t\t(at {fmt(x)} {fmt(y)} 0)')
    lines.append(f'\t\t\t(effects (font (size 1.27 1.27)) (hide yes))')
    lines.append(f'\t\t)')
    up = UNIT_PINS.get(lib_id, {})
    if up:
        pins = up.get(unit, [])
    else:
        pins = ALL_PINS.get(lib_id, [])
    for pn in pins:
        lines.append(f'\t\t(pin "{pn}" (uuid "{uid()}"))')
    lines.append(f'\t\t(instances')
    lines.append(f'\t\t\t(project "{PROJECT_NAME}"')
    lines.append(f'\t\t\t\t(path "/{ROOT_UUID}"')
    lines.append(f'\t\t\t\t\t(reference "{ref_prefix}")')
    lines.append(f'\t\t\t\t\t(unit {unit})')
    lines.append(f'\t\t\t\t)')
    lines.append(f'\t\t\t)')
    lines.append(f'\t\t)')
    lines.append(f'\t)')
    return '\n'.join(lines)

def gen_label(name, x, y, angle=0):
    return (
        f'\t(label "{name}"\n'
        f'\t\t(at {fmt(x)} {fmt(y)} {angle})\n'
        f'\t\t(effects\n'
        f'\t\t\t(font (size 1.27 1.27))\n'
        f'\t\t)\n'
        f'\t\t(uuid "{uid()}")\n'
        f'\t)'
    )

def gen_no_connect(x, y):
    return (
        f'\t(no_connect\n'
        f'\t\t(at {fmt(x)} {fmt(y)})\n'
        f'\t\t(uuid "{uid()}")\n'
        f'\t)'
    )

def gen_wire(x1, y1, x2, y2):
    return (
        f'\t(wire\n'
        f'\t\t(pts\n'
        f'\t\t\t(xy {fmt(x1)} {fmt(y1)}) (xy {fmt(x2)} {fmt(y2)})\n'
        f'\t\t)\n'
        f'\t\t(stroke\n'
        f'\t\t\t(width 0)\n'
        f'\t\t\t(type default)\n'
        f'\t\t)\n'
        f'\t\t(uuid "{uid()}")\n'
        f'\t)'
    )

def gen_junction(x, y):
    return (
        f'\t(junction\n'
        f'\t\t(at {fmt(x)} {fmt(y)})\n'
        f'\t\t(diameter 0)\n'
        f'\t\t(color 0 0 0 0)\n'
        f'\t\t(uuid "{uid()}")\n'
        f'\t)'
    )

def gen_text(text, x, y, size=2.54):
    return (
        f'\t(text "{text}"\n'
        f'\t\t(exclude_from_sim no)\n'
        f'\t\t(at {fmt(x)} {fmt(y)} 0)\n'
        f'\t\t(effects\n'
        f'\t\t\t(font (size {fmt(size)} {fmt(size)}))\n'
        f'\t\t\t(justify left bottom)\n'
        f'\t\t)\n'
        f'\t\t(uuid "{uid()}")\n'
        f'\t)'
    )

# ============================================================
# GND power symbol generation
# ============================================================
pwr_counter = [0]
def gen_gnd_symbol(x, y):
    pwr_counter[0] += 1
    ref = f"#PWR{pwr_counter[0]:03d}"
    return gen_symbol_instance(ref, "power:GND", "GND", "", x, y, 0, 1)

def gen_pwr_flag(x, y):
    pwr_counter[0] += 1
    ref = f"#FLG{pwr_counter[0]:03d}"
    return gen_symbol_instance(ref, "power:PWR_FLAG", "PWR_FLAG", "", x, y, 0, 1)

# ============================================================
# Main schematic generation
# ============================================================
def generate_schematic():
    # Collect needed library symbols
    needed_libs = set()
    for p in PLACEMENTS:
        lib_id = p[1]
        lib_parts = lib_id.split(":", 1)
        needed_libs.add((lib_parts[0], lib_parts[1]))
    needed_libs.add(("power", "GND"))
    needed_libs.add(("power", "PWR_FLAG"))

    lib_symbol_blocks = collect_lib_symbols(sorted(needed_libs))

    parts = []
    parts.append(f'(kicad_sch')
    parts.append(f'\t(version 20250114)')
    parts.append(f'\t(generator "eeschema")')
    parts.append(f'\t(generator_version "9.0")')
    parts.append(f'\t(uuid "{ROOT_UUID}")')
    parts.append(f'\t(paper "A3")')
    parts.append(f'')
    parts.append(f'\t(title_block')
    parts.append(f'\t\t(title "LLUPS - Lithium Li-ion Universal Power Supply")')
    parts.append(f'\t\t(rev "1.0")')
    parts.append(f'\t\t(comment 1 "Two 18650 cells (1S2P), USB-C charging, 5V/3.3V regulated output")')
    parts.append(f'\t)')
    parts.append(f'')

    # lib_symbols
    parts.append(f'\t(lib_symbols')
    for block in lib_symbol_blocks:
        for line in block.split('\n'):
            parts.append(f'\t{line}')
    parts.append(f'\t)')
    parts.append(f'')

    # Section labels
    parts.append(gen_text("USB INPUT", 25, 40))
    parts.append(gen_text("CHARGER (BQ24072)", 125, 40))
    parts.append(gen_text("BATTERY + PROTECTION", 240, 40))
    parts.append(gen_text("BOOST 5V (MT3608)", 125, 185))
    parts.append(gen_text("LDO 3.3V + OUTPUT", 250, 185))

    # Component instances
    for p in PLACEMENTS:
        ref, lib_id, value, fp, x, y, rot, unit = p
        parts.append(gen_symbol_instance(ref, lib_id, value, fp, x, y, rot, unit))

    # --- WIRES: pin-to-pin connections ---
    wire_count = 0
    for ref1, pin1, ref2, pin2 in WIRE_PAIRS:
        p1 = get_pin_pos(ref1, pin1)
        p2 = get_pin_pos(ref2, pin2)
        if p1 is None or p2 is None:
            print(f"WARNING: Can't route wire {ref1}.{pin1} → {ref2}.{pin2}", file=sys.stderr)
            continue
        for seg in route_two_pins(p1, p2):
            parts.append(gen_wire(*seg))
            wire_count += 1

    # --- WIRES: complex multi-point routes ---
    complex_segs, complex_junctions = build_complex_wires()
    for seg in complex_segs:
        x1, y1, x2, y2 = seg
        if abs(x1-x2) > 0.01 or abs(y1-y2) > 0.01:
            parts.append(gen_wire(x1, y1, x2, y2))
            wire_count += 1
    for jx, jy in complex_junctions:
        parts.append(gen_junction(jx, jy))

    # --- NET LABELS ---
    for net_name, ref, pin_num in LABEL_PINS:
        pos = get_pin_pos(ref, pin_num)
        if pos is None:
            print(f"WARNING: Can't find pin {pin_num} of {ref} for label {net_name}", file=sys.stderr)
            continue
        x, y = pos
        p = find_placement(ref, pin_num)
        ang = label_angle(p[1], pin_num, p[6]) if p else 0
        parts.append(gen_label(net_name, x, y, ang))

    # --- GND power symbols ---
    for ref, pin_num in GND_PINS:
        pos = get_pin_pos(ref, pin_num)
        if pos is None:
            print(f"WARNING: Can't find GND pin {pin_num} of {ref}", file=sys.stderr)
            continue
        x, y = pos
        parts.append(gen_gnd_symbol(x, y))

    # --- No-connect flags ---
    for ref, pin_num in NC_PINS:
        pos = get_pin_pos(ref, pin_num)
        if pos is None:
            continue
        parts.append(gen_no_connect(pos[0], pos[1]))

    # --- PWR_FLAG for ERC ---
    # PWR_FLAGs needed on nets with power input pins but no power output pins
    pwr_flag_pins = [
        ("J1", "A4"),    # VBUS raw (USB connector)
        ("J1", "A1"),    # GND
        ("U2", "13"),    # VBUS (charger IN)
        ("U4", "5"),     # VSYS_BOOST (boost VIN)
        ("U5", "1"),     # 5V (LDO VIN)
    ]
    for ref, pin in pwr_flag_pins:
        pos = get_pin_pos(ref, pin)
        if pos:
            parts.append(gen_pwr_flag(pos[0], pos[1]))

    # Sheet instances
    parts.append(f'')
    parts.append(f'\t(sheet_instances')
    parts.append(f'\t\t(path "/"')
    parts.append(f'\t\t\t(page "1")')
    parts.append(f'\t\t)')
    parts.append(f'\t)')
    parts.append(f'')
    parts.append(f'\t(embedded_fonts no)')
    parts.append(f')')

    print(f"Wires: {wire_count} segments", file=sys.stderr)
    return '\n'.join(parts)

# ============================================================
# Project file (.kicad_pro)
# ============================================================
def generate_project():
    proj = {
        "board": {
            "3dviewports": [],
            "design_settings": {
                "defaults": {
                    "apply_defaults_to_fp_fields": False,
                    "apply_defaults_to_fp_shapes": False,
                    "apply_defaults_to_fp_text": False,
                    "board_outline_line_width": 0.1,
                    "copper_line_width": 0.2,
                    "copper_text_italic": False,
                    "copper_text_size_h": 1.5,
                    "copper_text_size_v": 1.5,
                    "copper_text_thickness": 0.3,
                    "copper_text_upright": False,
                    "courtyard_line_width": 0.05,
                    "dimension_precision": 4,
                    "dimension_units": 3,
                    "fab_line_width": 0.1,
                    "fab_text_italic": False,
                    "fab_text_size_h": 1.0,
                    "fab_text_size_v": 1.0,
                    "fab_text_thickness": 0.15,
                    "fab_text_upright": False,
                    "other_line_width": 0.1,
                    "other_text_italic": False,
                    "other_text_size_h": 1.0,
                    "other_text_size_v": 1.0,
                    "other_text_thickness": 0.15,
                    "other_text_upright": False,
                    "pads": {
                        "drill": 0.762,
                        "height": 1.524,
                        "width": 1.524
                    },
                    "silk_line_width": 0.12,
                    "silk_text_italic": False,
                    "silk_text_size_h": 1.0,
                    "silk_text_size_v": 1.0,
                    "silk_text_thickness": 0.15,
                    "silk_text_upright": False,
                    "zones": {
                        "min_clearance": 0.5
                    }
                },
                "diff_pair_dimensions": [],
                "drc_exclusions": [],
                "rules": {
                    "min_clearance": 0.2,
                    "min_connection_width": 0.0,
                    "min_copper_edge_clearance": 0.0,
                    "min_hole_clearance": 0.25,
                    "min_hole_to_hole": 0.25,
                    "min_microvia_diameter": 0.2,
                    "min_microvia_drill": 0.1,
                    "min_resolved_spokes": 2,
                    "min_silk_clearance": 0.0,
                    "min_text_height": 0.8,
                    "min_text_thickness": 0.08,
                    "min_through_hole_diameter": 0.3,
                    "min_track_width": 0.2,
                    "min_via_annular_width": 0.1,
                    "min_via_diameter": 0.5,
                    "solder_mask_to_copper_clearance": 0.0,
                    "use_height_for_length_calcs": True
                },
                "teardrop_options": [
                    {"td_onpadsmd": True, "td_onroundshapesonly": False,
                     "td_ontrackend": False, "td_onviapad": True}
                ],
                "teardrop_parameters": [
                    {"td_allow_use_two_tracks": True, "td_curve_segcount": 0,
                     "td_height_ratio": 1.0, "td_length_ratio": 0.5,
                     "td_maxheight": 2.0, "td_maxlen": 1.0,
                     "td_on_pad_in_zone": False, "td_target_name": "td_round_shape",
                     "td_width_to_size_filter_ratio": 0.9},
                    {"td_allow_use_two_tracks": True, "td_curve_segcount": 0,
                     "td_height_ratio": 1.0, "td_length_ratio": 0.5,
                     "td_maxheight": 2.0, "td_maxlen": 1.0,
                     "td_on_pad_in_zone": False, "td_target_name": "td_rect_shape",
                     "td_width_to_size_filter_ratio": 0.9},
                    {"td_allow_use_two_tracks": True, "td_curve_segcount": 0,
                     "td_height_ratio": 1.0, "td_length_ratio": 0.5,
                     "td_maxheight": 2.0, "td_maxlen": 1.0,
                     "td_on_pad_in_zone": False, "td_target_name": "td_track_end",
                     "td_width_to_size_filter_ratio": 0.9}
                ],
                "track_widths": [],
                "tuning_pattern_settings": {
                    "diff_pair_defaults": {"corner_radius_percentage": 80, "corner_style": 1,
                                           "max_amplitude": 1.0, "min_amplitude": 0.2,
                                           "single_sided": False, "spacing": 0.6},
                    "single_track_defaults": {"corner_radius_percentage": 80, "corner_style": 1,
                                              "max_amplitude": 1.0, "min_amplitude": 0.2,
                                              "single_sided": False, "spacing": 0.6}
                },
                "via_dimensions": []
            },
            "ipc2581": {"dist": "", "distpn": "", "internal_id": "",
                        "mfg": "", "mpn": ""},
            "layer_pairs": [],
            "layer_presets": [],
            "viewports": []
        },
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{PROJECT_NAME}.kicad_pro", "version": 3},
        "net_settings": {
            "classes": [
                {
                    "bus_width": 12,
                    "clearance": 0.2,
                    "diff_pair_gap": 0.25,
                    "diff_pair_via_gap": 0.25,
                    "diff_pair_width": 0.2,
                    "line_style": 0,
                    "microvia_diameter": 0.3,
                    "microvia_drill": 0.1,
                    "name": "Default",
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "track_width": 0.2,
                    "via_diameter": 0.6,
                    "via_drill": 0.3,
                    "wire_width": 6
                },
                {
                    "bus_width": 12,
                    "clearance": 0.3,
                    "diff_pair_gap": 0.25,
                    "diff_pair_via_gap": 0.25,
                    "diff_pair_width": 0.2,
                    "line_style": 0,
                    "microvia_diameter": 0.3,
                    "microvia_drill": 0.1,
                    "name": "Power",
                    "nets": [],
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "track_width": 0.5,
                    "via_diameter": 0.8,
                    "via_drill": 0.4,
                    "wire_width": 6
                }
            ],
            "meta": {"version": 3},
            "net_colors": None,
            "netclass_assignments": None,
            "netclass_patterns": []
        },
        "pcbnew": {
            "last_paths": {"gencad": "", "idf": "", "netlist": "",
                           "plot": "", "pos_files": "", "specctra_dsn": "",
                           "step": "", "svg": "", "vrml": ""},
            "page_layout_descr_file": ""
        },
        "schematic": {
            "annotate_start_num": 0,
            "bom_export_filename": "",
            "connection_grid_size": 50.0,
            "drawing": {
                "dashed_lines_dash_length_ratio": 12.0,
                "dashed_lines_gap_length_ratio": 3.0,
                "default_line_thickness": 6.0,
                "default_text_size": 50.0,
                "field_names": [],
                "intersheets_ref_own_page": False,
                "intersheets_ref_prefix": "",
                "intersheets_ref_short": False,
                "intersheets_ref_show": False,
                "intersheets_ref_suffix": "",
                "junction_size_choice": 3,
                "label_size_ratio": 0.375,
                "operating_point_overlay_i_precision": 3,
                "operating_point_overlay_i_range": "~A",
                "operating_point_overlay_v_precision": 3,
                "operating_point_overlay_v_range": "~V",
                "overbar_offset_ratio": 1.23,
                "pin_symbol_size": 25.0,
                "text_offset_ratio": 0.15
            },
            "legacy_lib_dir": "",
            "legacy_lib_list": [],
            "meta": {"version": 1},
            "net_format_name": "",
            "page_layout_descr_file": "",
            "plot_directory": "",
            "spice_current_sheet_as_root": False,
            "spice_external_command": "spice \"%I\"",
            "spice_model_current_sheet_as_root": True,
            "spice_save_all_currents": False,
            "spice_save_all_dissipations": False,
            "spice_save_all_voltages": False,
            "subpart_first_id": 65,
            "subpart_id_separator": 0
        },
        "sheets": [
            [ROOT_UUID, "Root"]
        ],
        "text_variables": {}
    }
    return json.dumps(proj, indent=2)

# ============================================================
# PCB Layout Generation
# ============================================================
import math, xml.etree.ElementTree as ET

KICAD_FP_DIR = "/usr/share/kicad/footprints"

# Map schematic footprint IDs to actual library file paths
FP_FILE_MAP = {
    "Connector_USB:USB_C_Receptacle_GCT_USB4085":
        "Connector_USB.pretty/USB_C_Receptacle_GCT_USB4085.kicad_mod",
    "Fuse:Fuse_0805_2012Metric":
        "Fuse.pretty/Fuse_0805_2012Metric.kicad_mod",
    "Capacitor_SMD:C_0805_2012Metric":
        "Capacitor_SMD.pretty/C_0805_2012Metric.kicad_mod",
    "Capacitor_SMD:C_0402_1005Metric":
        "Capacitor_SMD.pretty/C_0402_1005Metric.kicad_mod",
    "Package_TO_SOT_SMD:SOT-23-6":
        "Package_TO_SOT_SMD.pretty/SOT-23-6.kicad_mod",
    "Package_TO_SOT_SMD:SOT-23-5":
        "Package_TO_SOT_SMD.pretty/SOT-23-5.kicad_mod",
    "Package_TO_SOT_SMD:SOT-23-3":
        "Package_TO_SOT_SMD.pretty/SOT-23-3.kicad_mod",
    "Resistor_SMD:R_0402_1005Metric":
        "Resistor_SMD.pretty/R_0402_1005Metric.kicad_mod",
    "LED_SMD:LED_0603_1608Metric":
        "LED_SMD.pretty/LED_0603_1608Metric.kicad_mod",
    "Diode_SMD:D_SMA":
        "Diode_SMD.pretty/D_SMA.kicad_mod",
    "Inductor_SMD:L_0805_2012Metric":
        "Inductor_SMD.pretty/L_0805_2012Metric.kicad_mod",
    "Battery:BatteryHolder_Keystone_1042_1x18650":
        "Battery.pretty/BatteryHolder_Keystone_1042_1x18650.kicad_mod",
    "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical":
        "Connector_PinHeader_2.54mm.pretty/PinHeader_1x05_P2.54mm_Vertical.kicad_mod",
    "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical":
        "Connector_PinHeader_2.54mm.pretty/PinHeader_1x03_P2.54mm_Vertical.kicad_mod",
    # BQ24072 uses TI RVA QFN with thermal vias
    "Package_DFN_QFN:VQFN-16-1EP_3.5x3.5mm_P0.5mm_EP2.1x2.1mm":
        "Package_DFN_QFN.pretty/Texas_RVA_VQFN-16-1EP_3.5x3.5mm_P0.5mm_EP2.14x2.14mm_ThermalVias.kicad_mod",
}

# Pad positions from footprint files: {fp_lib_id: {pad_num: [(x, y), ...]}}
# (Some pads like shield/EP have multiple instances)
FP_PAD_POS = {
    "Connector_USB:USB_C_Receptacle_GCT_USB4085": {
        "A1": (0,0), "A4": (0.85,0), "A5": (1.7,0), "A6": (2.55,0),
        "A7": (3.4,0), "A8": (4.25,0), "A9": (5.1,0), "A12": (5.95,0),
        "B1": (5.95,1.35), "B4": (5.1,1.35), "B5": (4.25,1.35),
        "B6": (3.4,1.35), "B7": (2.55,1.35), "B8": (1.7,1.35),
        "B9": (0.85,1.35), "B12": (0,1.35), "S1": (-1.35,0.98),
    },
    "Fuse:Fuse_0805_2012Metric": {"1": (-0.9375,0), "2": (0.9375,0)},
    "Resistor_SMD:R_0402_1005Metric": {"1": (-0.51,0), "2": (0.51,0)},
    "Capacitor_SMD:C_0402_1005Metric": {"1": (-0.48,0), "2": (0.48,0)},
    "Capacitor_SMD:C_0805_2012Metric": {"1": (-0.95,0), "2": (0.95,0)},
    "LED_SMD:LED_0603_1608Metric": {"1": (-0.7875,0), "2": (0.7875,0)},
    "Diode_SMD:D_SMA": {"1": (-2.0,0), "2": (2.0,0)},
    "Inductor_SMD:L_0805_2012Metric": {"1": (-0.9125,0), "2": (0.9125,0)},
    "Package_TO_SOT_SMD:SOT-23-6": {
        "1": (-1.137,-0.95), "2": (-1.137,0), "3": (-1.137,0.95),
        "4": (1.137,0.95), "5": (1.137,0), "6": (1.137,-0.95),
    },
    "Package_TO_SOT_SMD:SOT-23-5": {
        "1": (-1.137,-0.95), "2": (-1.137,0), "3": (-1.137,0.95),
        "4": (1.137,0.95), "5": (1.137,-0.95),
    },
    "Package_TO_SOT_SMD:SOT-23-3": {
        "1": (-1.1375,-0.95), "2": (-1.1375,0.95), "3": (1.1375,0),
    },
    "Package_DFN_QFN:VQFN-16-1EP_3.5x3.5mm_P0.5mm_EP2.1x2.1mm": {
        "1": (-1.698,-0.75), "2": (-1.698,-0.25), "3": (-1.698,0.25),
        "4": (-1.698,0.75), "5": (-0.75,1.698), "6": (-0.25,1.698),
        "7": (0.25,1.698), "8": (0.75,1.698), "9": (1.698,0.75),
        "10": (1.698,0.25), "11": (1.698,-0.25), "12": (1.698,-0.75),
        "13": (0.75,-1.698), "14": (0.25,-1.698), "15": (-0.25,-1.698),
        "16": (-0.75,-1.698), "17": (0,0),
    },
    "Battery:BatteryHolder_Keystone_1042_1x18650": {
        "1": (-39.69,0), "2": (39.69,0),
    },
    "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical": {
        "1": (0,0), "2": (0,2.54), "3": (0,5.08), "4": (0,7.62), "5": (0,10.16),
    },
    "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical": {
        "1": (0,0), "2": (0,2.54), "3": (0,5.08),
    },
}

# ============================================================
# PCB Component Placements
# Board: 90mm x 58mm, USB-C on left edge
# Electronics in top 15mm, battery holders below
# (ref, footprint_schematic_id, x_mm, y_mm, rotation_deg, layer)
# ============================================================
PCB_PLACEMENTS = [
    # --- USB INPUT (left edge) ---
    # USB-C: rot=90° so mating face points left (toward board edge)
    # At rot=90, pads span vertically. Place so shield aligns with edge.
    ("J1",  "Connector_USB:USB_C_Receptacle_GCT_USB4085",  3.5, 7.5,  90, "F.Cu"),
    ("F1",  "Fuse:Fuse_0805_2012Metric",                   11, 3.5,    0, "F.Cu"),
    ("C1",  "Capacitor_SMD:C_0805_2012Metric",             11, 6.5,    0, "F.Cu"),
    ("U1",  "Package_TO_SOT_SMD:SOT-23-6",                 11, 10,     0, "F.Cu"),
    ("R1",  "Resistor_SMD:R_0402_1005Metric",               7, 12,    90, "F.Cu"),
    ("R2",  "Resistor_SMD:R_0402_1005Metric",               9, 12,    90, "F.Cu"),

    # --- CHARGER (BQ24072) ---
    ("U2",  "Package_DFN_QFN:VQFN-16-1EP_3.5x3.5mm_P0.5mm_EP2.1x2.1mm",
                                                            26, 8,      0, "F.Cu"),
    ("C2",  "Capacitor_SMD:C_0402_1005Metric",             19, 4,      0, "F.Cu"),  # IN cap
    ("C3",  "Capacitor_SMD:C_0402_1005Metric",             32, 4,      0, "F.Cu"),  # SYS cap
    ("C4",  "Capacitor_SMD:C_0402_1005Metric",             32, 8,     90, "F.Cu"),  # BAT cap
    ("R3",  "Resistor_SMD:R_0402_1005Metric",              22, 13,     0, "F.Cu"),  # ISET
    ("R4",  "Resistor_SMD:R_0402_1005Metric",              26, 13,     0, "F.Cu"),  # ILIM (near pin12)
    ("R5",  "Resistor_SMD:R_0402_1005Metric",              24, 13,     0, "F.Cu"),  # TMR
    ("R8",  "Resistor_SMD:R_0402_1005Metric",              19, 8,     90, "F.Cu"),  # NTC bias
    ("D1",  "LED_SMD:LED_0603_1608Metric",                 34, 6,      0, "F.Cu"),  # CHG LED
    ("D2",  "LED_SMD:LED_0603_1608Metric",                 34, 10,     0, "F.Cu"),  # PGOOD LED
    ("R6",  "Resistor_SMD:R_0402_1005Metric",              37, 6,      0, "F.Cu"),  # CHG LED R
    ("R7",  "Resistor_SMD:R_0402_1005Metric",              37, 10,     0, "F.Cu"),  # PGOOD LED R

    # --- BATTERY + PROTECTION ---
    ("RT1", "Resistor_SMD:R_0402_1005Metric",              42, 10,     0, "F.Cu"),
    ("U3",  "Package_TO_SOT_SMD:SOT-23-6",                 48, 8,      0, "F.Cu"),
    ("U6",  "Package_TO_SOT_SMD:SOT-23-3",                 48, 14,     0, "F.Cu"),
    ("Q1",  "Package_TO_SOT_SMD:SOT-23-6",                 55, 8,      0, "F.Cu"),
    ("BT1", "Battery:BatteryHolder_Keystone_1042_1x18650",  45, 27,    0, "F.Cu"),
    ("BT2", "Battery:BatteryHolder_Keystone_1042_1x18650",  45, 48,    0, "F.Cu"),

    # --- BOOST CONVERTER (MT3608) ---
    ("L1",  "Inductor_SMD:L_0805_2012Metric",              60, 4,      0, "F.Cu"),
    ("U4",  "Package_TO_SOT_SMD:SOT-23-6",                 64, 8,      0, "F.Cu"),
    ("D3",  "Diode_SMD:D_SMA",                             70, 4,      0, "F.Cu"),
    ("C5",  "Capacitor_SMD:C_0805_2012Metric",             58, 12,     0, "F.Cu"),
    ("C6",  "Capacitor_SMD:C_0805_2012Metric",             76, 4,      0, "F.Cu"),
    ("R9",  "Resistor_SMD:R_0402_1005Metric",              68, 12,     0, "F.Cu"),
    ("R10", "Resistor_SMD:R_0402_1005Metric",              70, 12,     0, "F.Cu"),
    ("R11", "Resistor_SMD:R_0402_1005Metric",              62, 12,     0, "F.Cu"),

    # --- LDO + OUTPUT ---
    ("U5",  "Package_TO_SOT_SMD:SOT-23-5",                 80, 8,      0, "F.Cu"),
    ("C7",  "Capacitor_SMD:C_0402_1005Metric",             76, 12,     0, "F.Cu"),
    ("C8",  "Capacitor_SMD:C_0402_1005Metric",             84, 12,     0, "F.Cu"),
    ("J2",  "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
                                                            88, 2,      0, "F.Cu"),
    ("J3",  "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
                                                            88, 14,     0, "F.Cu"),
]

# Board dimensions
BOARD_W = 90
BOARD_H = 58
BOARD_CORNER_R = 1.5  # corner radius

# ============================================================
# PCB helper functions
# ============================================================
def pcb_pad_abs(comp_x, comp_y, comp_rot_deg, pad_x, pad_y):
    """Get absolute pad position on PCB given component and pad positions."""
    rad = math.radians(comp_rot_deg)
    ax = comp_x + pad_x * math.cos(rad) - pad_y * math.sin(rad)
    ay = comp_y + pad_x * math.sin(rad) + pad_y * math.cos(rad)
    return (round(ax, 4), round(ay, 4))

def get_pcb_pad_positions():
    """Build dict of (ref, pad_num) -> (abs_x, abs_y) for all PCB components."""
    positions = {}
    for ref, fp_id, cx, cy, rot, layer in PCB_PLACEMENTS:
        pads = FP_PAD_POS.get(fp_id, {})
        for pnum, (px, py) in pads.items():
            positions[(ref, pnum)] = pcb_pad_abs(cx, cy, rot, px, py)
    return positions

def read_fp_mod(fp_id):
    """Read a .kicad_mod file content."""
    rel = FP_FILE_MAP.get(fp_id)
    if not rel:
        print(f"WARNING: No footprint file mapping for {fp_id}", file=sys.stderr)
        return None
    path = os.path.join(KICAD_FP_DIR, rel)
    with open(path) as f:
        return f.read()

def find_balanced_end(text, start):
    """Find the matching closing paren for an opening paren at start."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1

def embed_footprint(fp_id, ref, value, cx, cy, rot, layer, pad_net_map, net_codes):
    """Read a .kicad_mod file and produce a PCB footprint instance with nets."""
    raw = read_fp_mod(fp_id)
    if raw is None:
        return ""

    # Extract content between outer parens (skip first line, remove trailing ))
    first_nl = raw.index('\n')
    inner = raw[first_nl:]
    # Remove trailing ) that closes the footprint
    inner = inner.rstrip()
    if inner.endswith(')'):
        inner = inner[:-1]

    # Build header
    rot_str = f" {rot}" if rot else ""
    header = f'\t(footprint "{fp_id}"\n'
    header += f'\t\t(layer "{layer}")\n'
    header += f'\t\t(uuid "{uid()}")\n'
    header += f'\t\t(at {cx} {cy}{rot_str})\n'

    # Insert net info into pads
    # Find each (pad "N" ...) block and add (net CODE "name") before closing )
    result = inner
    processed = ""
    pos = 0
    while True:
        pad_start = result.find('(pad "', pos)
        if pad_start < 0:
            processed += result[pos:]
            break
        processed += result[pos:pad_start]
        pad_end = find_balanced_end(result, pad_start)

        pad_block = result[pad_start:pad_end+1]
        # Extract pad number
        m = re.match(r'\(pad "([^"]+)"', pad_block)
        if m:
            pnum = m.group(1)
            net_name = pad_net_map.get((ref, pnum), "")
            net_code = net_codes.get(net_name, 0)
            # Insert net and uuid before closing )
            net_insert = f'\n\t\t\t(net {net_code} "{net_name}")' if net_name else ""
            uuid_insert = f'\n\t\t\t(uuid "{uid()}")'
            pad_block = pad_block[:-1] + net_insert + uuid_insert + '\n\t\t)'
        processed += pad_block
        pos = pad_end + 1

    # Update Reference property
    ref_pat = r'\(property "Reference" "[^"]*"'
    processed = re.sub(ref_pat, f'(property "Reference" "{ref}"', processed, count=1)

    # Update Value property
    val_pat = r'\(property "Value" "[^"]*"'
    processed = re.sub(val_pat, f'(property "Value" "{value}"', processed, count=1)

    return header + processed + '\n\t)'

def pcb_track(x1, y1, x2, y2, width, layer, net_code):
    """Generate a PCB track segment."""
    return (
        f'\t(segment\n'
        f'\t\t(start {x1} {y1})\n'
        f'\t\t(end {x2} {y2})\n'
        f'\t\t(width {width})\n'
        f'\t\t(layer "{layer}")\n'
        f'\t\t(net {net_code})\n'
        f'\t\t(uuid "{uid()}")\n'
        f'\t)'
    )

def pcb_via(x, y, net_code, size=0.6, drill=0.3):
    """Generate a PCB via."""
    return (
        f'\t(via\n'
        f'\t\t(at {x} {y})\n'
        f'\t\t(size {size})\n'
        f'\t\t(drill {drill})\n'
        f'\t\t(layers "F.Cu" "B.Cu")\n'
        f'\t\t(net {net_code})\n'
        f'\t\t(uuid "{uid()}")\n'
        f'\t)'
    )

def pcb_route_L(x1, y1, x2, y2, width, layer, net_code, h_first=True):
    """Route an L-shaped trace between two points. Returns list of track strings."""
    tracks = []
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    if dx < 0.01 and dy < 0.01:
        return tracks
    if dx < 0.01 or dy < 0.01:
        tracks.append(pcb_track(x1, y1, x2, y2, width, layer, net_code))
        return tracks
    if h_first:
        tracks.append(pcb_track(x1, y1, x2, y1, width, layer, net_code))
        tracks.append(pcb_track(x2, y1, x2, y2, width, layer, net_code))
    else:
        tracks.append(pcb_track(x1, y1, x1, y2, width, layer, net_code))
        tracks.append(pcb_track(x1, y2, x2, y2, width, layer, net_code))
    return tracks

def pcb_mounting_hole(x, y, diameter=2.2, pad_dia=4.0):
    """Generate a mounting hole footprint."""
    return (
        f'\t(footprint "MountingHole:MountingHole_{diameter:.1f}mm"\n'
        f'\t\t(layer "F.Cu")\n'
        f'\t\t(uuid "{uid()}")\n'
        f'\t\t(at {x} {y})\n'
        f'\t\t(property "Reference" "H{x:.0f}"\n'
        f'\t\t\t(at 0 -2.5)\n'
        f'\t\t\t(layer "F.SilkS")\n'
        f'\t\t\t(uuid "{uid()}")\n'
        f'\t\t\t(effects (font (size 1 1) (thickness 0.15)))\n'
        f'\t\t)\n'
        f'\t\t(property "Value" "MountingHole"\n'
        f'\t\t\t(at 0 2.5)\n'
        f'\t\t\t(layer "F.Fab")\n'
        f'\t\t\t(uuid "{uid()}")\n'
        f'\t\t\t(effects (font (size 1 1) (thickness 0.15)))\n'
        f'\t\t)\n'
        f'\t\t(pad "" thru_hole circle\n'
        f'\t\t\t(at 0 0)\n'
        f'\t\t\t(size {pad_dia} {pad_dia})\n'
        f'\t\t\t(drill {diameter})\n'
        f'\t\t\t(layers "*.Cu" "*.Mask")\n'
        f'\t\t\t(uuid "{uid()}")\n'
        f'\t\t)\n'
        f'\t\t(fp_circle\n'
        f'\t\t\t(center 0 0)\n'
        f'\t\t\t(end {pad_dia/2 + 0.25} 0)\n'
        f'\t\t\t(stroke (width 0.05) (type solid))\n'
        f'\t\t\t(layer "F.CrtYd")\n'
        f'\t\t\t(uuid "{uid()}")\n'
        f'\t\t)\n'
        f'\t)'
    )

# ============================================================
# Trace routing — hand-planned, one net at a time
# Order: power nets on F.Cu, signals on F.Cu, B.Cu only for short hops
# GND handled entirely by zones (F.Cu + B.Cu) + stitching vias
#
# B.Cu corridor map (east-west runs):
#   y=0.5: 5V → J2.1 (x=75-88)
#   y=1:   VSYS east run (x=31.5-61.5)
#   y=1.5: VBUS east run (x=10-18.5)
#   y=4.5: 3V3 → J2.2 (x=83.5-88)
#   y=7.05: 5V → C7.1 (x=75.5-78)
#   y=7.52: VBAT C4→U2 (x=22-32)
#   y=9:   CELL_NEG U3→Q1 (x=46.9-56.1)
#   y=9.62: EN hop (x=81-83)
#   y=13-15: TMR via (x=24.5)
#   y=16:  VBAT east run (x=49-86)
#   y=18:  NTC_SENSE → J3.2 (x=41.5-88)
#   y=20:  CELL_NEG west run (x=56-84.7)
#   y=21:  CHG_N → J3.3 (x=33-88)
# ============================================================
def generate_pcb_traces(pad_positions, pad_net_map, net_codes):
    tracks = []
    vias = []

    def nc(name):
        return net_codes.get(name, 0)

    def T(x1, y1, x2, y2, w, layer, net):
        if abs(x1-x2) < 0.001 and abs(y1-y2) < 0.001:
            return
        tracks.append(pcb_track(x1, y1, x2, y2, w, layer, net))

    def V(x, y, net, sz=0.6, dr=0.3):
        vias.append(pcb_via(x, y, net, sz, dr))

    PW  = 0.5    # power trace width
    PW2 = 0.8    # heavy power trace width
    SW  = 0.25   # signal trace width

    # ── GND stitching vias — battery area only (far from all signals) ──
    nc_gnd = nc("GND")
    for gx in [10, 30, 50, 70, 80]:
        for gy in [24, 35, 45, 55]:
            V(gx, gy, nc_gnd)

    # ══════════════════════════════════════════════════════════
    #  POWER NETS — wide traces, routed first
    # ══════════════════════════════════════════════════════════

    # ── Net-(F1-Pad2): J1 VBUS pads → F1.2(11.94,3.5) ──
    # Pads: A4(3.5,8.35), B9(2.15,8.35), A9(3.5,12.6), B4(2.15,12.6)
    # J1 shield S1 at (2.52,6.15) has large PTH pads — keep traces away!
    nf = nc("Net-(F1-Pad2)")
    # A4+B9 merge at y=8.35, go right then UP to y=2, then right to F1.2
    # This avoids crossing F1.1(10.06,3.5)=VBUS by approaching from above
    T(2.15, 8.35, 3.5, 8.35, PW, "F.Cu", nf)
    T(3.5, 8.35, 6.5, 8.35, PW, "F.Cu", nf)
    T(6.5, 8.35, 6.5, 2, PW, "F.Cu", nf)
    T(6.5, 2, 11.94, 2, PW, "F.Cu", nf)
    T(11.94, 2, 11.94, 3.5, PW, "F.Cu", nf)
    # A9+B4 at y=12.6: via to B.Cu, run up to join at x=6.5
    T(2.15, 12.6, 3.5, 12.6, PW, "F.Cu", nf)
    T(3.5, 12.6, 6.5, 12.6, PW, "F.Cu", nf)
    V(6.5, 12.6, nf)
    T(6.5, 12.6, 6.5, 8.35, PW, "B.Cu", nf)
    V(6.5, 8.35, nf)

    # ── /VBUS: F1.1(10.06,3.5) → C1.1(10.05,6.5), U1.5(12.14,10), ──
    # ──        C2.1(18.52,4), U2.13(26.75,6.3)                      ──
    nv = nc("/VBUS")
    # F1.1 → C1.1: straight down (C1.1 at 10.05 ≈ F1.1 at 10.06)
    T(10.06, 3.5, 10.06, 6.5, PW, "F.Cu", nv)
    # C1.1 → U1.5: via to B.Cu to avoid C1.2(11.95,6.5)=GND,
    # route at y=6.5 on B.Cu past C1.2 (SMD, no B.Cu pad), emerge at x=14
    V(10.06, 6.5, nv)
    T(10.06, 6.5, 14, 6.5, PW, "B.Cu", nv)
    V(14, 6.5, nv)
    T(14, 6.5, 14, 10, PW, "F.Cu", nv)
    T(14, 10, 12.14, 10, PW, "F.Cu", nv)
    # F1.1 → C2.1: go up to y=1.5, right on B.Cu
    T(10.06, 3.5, 10.06, 1.5, PW, "F.Cu", nv)
    V(10.06, 1.5, nv)
    T(10.06, 1.5, 18.52, 1.5, PW, "B.Cu", nv)
    V(18.52, 1.5, nv)
    T(18.52, 1.5, 18.52, 4, PW, "F.Cu", nv)
    # C2.1 → U2.13(26.75,6.3): at y=5.5
    T(18.52, 4, 18.52, 5.5, PW, "F.Cu", nv)
    T(18.52, 5.5, 26.75, 5.5, PW, "F.Cu", nv)
    T(26.75, 5.5, 26.75, 6.3, PW, "F.Cu", nv)

    # ── /VBAT: U2.2(24.3,7.75), U2.3(24.3,8.25), C4.1(32,7.52),    ──
    # ──   R8.1(19,7.49), BT1.1(5.31,27), BT2.1(5.31,48),            ──
    # ──   U3.5(49.14,8), J2.5(88,12.16), J3.1(88,14)                ──
    nb = nc("/VBAT")
    # U2.2+U2.3 vertical stub
    T(24.3, 7.75, 24.3, 8.25, PW, "F.Cu", nb)
    # R8.1(19,7.49) → U2.2: up to y=6.8, right to x=23.5, down to 7.75
    T(19, 7.49, 19, 6.8, PW, "F.Cu", nb)
    T(19, 6.8, 23.5, 6.8, PW, "F.Cu", nb)
    T(23.5, 6.8, 23.5, 7.75, PW, "F.Cu", nb)
    T(23.5, 7.75, 24.3, 7.75, PW, "F.Cu", nb)
    # C4.1(32,7.52): via to B.Cu, run west, via up LEFT of U2 to avoid U2.1
    V(32, 7.52, nb)
    T(32, 7.52, 22, 7.52, PW, "B.Cu", nb)
    V(22, 7.52, nb)
    T(22, 7.52, 23.5, 7.52, PW, "F.Cu", nb)
    # VBAT south to batteries: at x=17
    T(19, 6.8, 17, 6.8, PW, "F.Cu", nb)
    T(17, 6.8, 17, 16, PW2, "F.Cu", nb)
    T(17, 16, 5.31, 16, PW2, "F.Cu", nb)
    T(5.31, 16, 5.31, 27, PW2, "F.Cu", nb)
    T(5.31, 27, 5.31, 48, PW2, "F.Cu", nb)
    # VBAT east to U3.5(49.14,8)
    T(17, 16, 49.14, 16, PW2, "F.Cu", nb)
    T(49.14, 16, 49.14, 8, PW2, "F.Cu", nb)
    # VBAT to J2.5(88,12.16) and J3.1(88,14): east on B.Cu at y=16
    V(49.14, 16, nb)
    T(49.14, 16, 86, 16, PW, "B.Cu", nb)
    V(86, 16, nb)
    T(86, 16, 86, 12.16, PW, "F.Cu", nb)
    T(86, 12.16, 88, 12.16, PW, "F.Cu", nb)
    T(86, 12.16, 86, 14, PW, "F.Cu", nb)
    T(86, 14, 88, 14, PW, "F.Cu", nb)

    # ── /CELL_NEG: BT1.2(84.69,27), BT2.2(84.69,48),   ──
    # ──   Q1.4(56.14,8.95), U3.2(46.86,8)               ──
    ncn = nc("/CELL_NEG")
    T(84.69, 27, 84.69, 48, PW2, "F.Cu", ncn)
    T(84.69, 27, 84.69, 20, PW, "F.Cu", ncn)
    # West on B.Cu at y=20
    V(84.69, 20, ncn)
    T(84.69, 20, 56.14, 20, PW, "B.Cu", ncn)
    V(56.14, 20, ncn)
    T(56.14, 20, 56.14, 8.95, PW, "F.Cu", ncn)
    # U3.2(46.86,8) → Q1.4(56.14,8.95): B.Cu hop to avoid F.Cu congestion
    V(46.86, 8, ncn)
    T(46.86, 8, 46.86, 9, PW, "B.Cu", ncn)
    T(46.86, 9, 56.14, 9, PW, "B.Cu", ncn)
    V(56.14, 9, ncn)
    T(56.14, 9, 56.14, 8.95, PW, "F.Cu", ncn)

    # ── /VSYS: U2.10(27.7,8.25), U2.11(27.7,7.75), U2.5(25.25,9.7),  ──
    # ──   U2.6(25.75,9.7), C3.1(31.52,4), R6.2(37.51,6),              ──
    # ──   R7.2(37.51,10), R11.1(61.49,12)                              ──
    ns = nc("/VSYS")
    # Join U2 right pins 10+11
    T(27.7, 7.75, 27.7, 8.25, PW, "F.Cu", ns)
    # Join U2 bottom pins 5+6
    T(25.25, 9.7, 25.75, 9.7, PW, "F.Cu", ns)
    # Connect right to bottom
    T(27.7, 8.25, 27.7, 10.5, PW, "F.Cu", ns)
    T(27.7, 10.5, 25.75, 10.5, PW, "F.Cu", ns)
    T(25.75, 10.5, 25.75, 9.7, PW, "F.Cu", ns)
    # U2.11 → C3.1(31.52,4): right then up, avoiding CHG_N at x=30.5
    T(27.7, 7.75, 29.5, 7.75, PW, "F.Cu", ns)
    T(29.5, 7.75, 29.5, 4, PW, "F.Cu", ns)
    T(29.5, 4, 31.52, 4, PW, "F.Cu", ns)
    # C3.1 → LEDs: at y=3 east, then south to R6/R7
    T(31.52, 4, 31.52, 3, PW, "F.Cu", ns)
    T(31.52, 3, 39, 3, PW, "F.Cu", ns)
    T(39, 3, 39, 6, PW, "F.Cu", ns)
    T(39, 6, 37.51, 6, SW, "F.Cu", ns)
    T(39, 6, 39, 10, PW, "F.Cu", ns)
    T(39, 10, 37.51, 10, SW, "F.Cu", ns)
    # VSYS → R11.1(61.49,12): B.Cu at y=1
    V(31.52, 3, ns)
    T(31.52, 3, 31.52, 1, PW, "B.Cu", ns)
    T(31.52, 1, 61.49, 1, PW, "B.Cu", ns)
    T(61.49, 1, 61.49, 12, PW, "B.Cu", ns)
    V(61.49, 12, ns)

    # ── /VSYS_BOOST: C5.1(57.05,12), L1.2(60.91,4), U4.5(65.14,8) ──
    nvb = nc("/VSYS_BOOST")
    # U4.5 → L1.2
    T(65.14, 8, 61.5, 8, PW, "F.Cu", nvb)
    T(61.5, 8, 61.5, 4, PW, "F.Cu", nvb)
    T(61.5, 4, 60.91, 4, PW, "F.Cu", nvb)
    # C5.1 → junction: route up at x=57.05, right at y=9.5, join at x=60
    T(57.05, 12, 57.05, 9.5, PW, "F.Cu", nvb)
    T(57.05, 9.5, 60, 9.5, PW, "F.Cu", nvb)
    T(60, 9.5, 60, 8, PW, "F.Cu", nvb)

    # ── Net-(D3-A) SW node: L1.1(59.09,4), U4.1(62.86,7.05), D3.2(72,4) ──
    nsw = nc("Net-(D3-A)")
    # L1.1 → U4.1: down then right
    T(59.09, 4, 59.09, 7.05, PW, "F.Cu", nsw)
    T(59.09, 7.05, 62.86, 7.05, PW, "F.Cu", nsw)
    # L1.1 → D3.2(72,4): go up to y=2 on F.Cu (above VSYS_BOOST at y=4-8),
    # then right past D3 body, down to D3.2 from above-right
    T(59.09, 4, 59.09, 2, PW, "F.Cu", nsw)
    T(59.09, 2, 73, 2, PW, "F.Cu", nsw)
    T(73, 2, 73, 4, PW, "F.Cu", nsw)
    T(73, 4, 72, 4, PW, "F.Cu", nsw)

    # ── /5V: D3.1(68,4), C6.1(75.05,4), U5.1(78.86,7.05),  ──
    # ──   C7.1(75.52,12), R9.1(67.49,12), J2.1(88,2)        ──
    n5 = nc("/5V")
    # D3.1(68,4) → C6.1(75.05,4): B.Cu hop under D3 body
    V(68, 4, n5)
    T(68, 4, 75.05, 4, PW, "B.Cu", n5)
    V(75.05, 4, n5)
    # C6.1(75.05,4) → U5.1(78.86,7.05): F.Cu right then down
    T(75.05, 4, 78.86, 4, PW, "F.Cu", n5)
    T(78.86, 4, 78.86, 7.05, PW, "F.Cu", n5)
    # R9.1(67.49,12): from D3.1, short F.Cu left then B.Cu down
    T(68, 4, 67.49, 4, PW, "F.Cu", n5)
    V(67.49, 4, n5)
    T(67.49, 4, 67.49, 12, PW, "B.Cu", n5)
    V(67.49, 12, n5)
    # C7.1(75.52,12): from U5.1, B.Cu hop left and down
    T(78.86, 7.05, 78, 7.05, PW, "F.Cu", n5)
    V(78, 7.05, n5)
    T(78, 7.05, 75.52, 7.05, PW, "B.Cu", n5)
    T(75.52, 7.05, 75.52, 12, PW, "B.Cu", n5)
    V(75.52, 12, n5)
    # J2.1(88,2): from C6.1 north then east on B.Cu
    T(75.05, 4, 75.05, 0.5, PW, "F.Cu", n5)
    V(75.05, 0.5, n5)
    T(75.05, 0.5, 88, 0.5, PW, "B.Cu", n5)
    V(88, 0.5, n5)
    T(88, 0.5, 88, 2, PW, "F.Cu", n5)

    # ── /3V3: U5.5(81.14,7.05), C8.1(83.52,12), J2.2(88,4.54) ──
    n3 = nc("/3V3")
    # U5.5 → C8.1: right to x=83.52, down to y=12
    T(81.14, 7.05, 83.52, 7.05, PW, "F.Cu", n3)
    T(83.52, 7.05, 83.52, 12, PW, "F.Cu", n3)
    # U5.5 → J2.2: via to B.Cu at x=83.52, east at y=4.5
    V(83.52, 7.05, n3)
    T(83.52, 7.05, 83.52, 4.5, PW, "B.Cu", n3)
    T(83.52, 4.5, 88, 4.5, PW, "B.Cu", n3)
    V(88, 4.5, n3)
    T(88, 4.5, 88, 4.54, PW, "F.Cu", n3)

    # ══════════════════════════════════════════════════════════
    #  SIGNAL NETS — narrow traces, routed after power
    # ══════════════════════════════════════════════════════════

    # ── /EN: R11.2(62.51,12), U4.4(65.14,8.95), U5.3(78.86,8.95), J2.4(88,9.62) ──
    ne = nc("/EN")
    T(62.51, 12, 64, 12, SW, "F.Cu", ne)
    T(64, 12, 64, 8.95, SW, "F.Cu", ne)
    T(64, 8.95, 65.14, 8.95, SW, "F.Cu", ne)
    # U4.4 → U5.3: at y=10.5 (avoids 5V B.Cu via at 67.49 and FB at y=11)
    T(65.14, 8.95, 65.14, 10.5, SW, "F.Cu", ne)
    T(65.14, 10.5, 77, 10.5, SW, "F.Cu", ne)
    T(77, 10.5, 77, 8.95, SW, "F.Cu", ne)
    T(77, 8.95, 78.86, 8.95, SW, "F.Cu", ne)
    # U5.3 → J2.4: hop over 3V3 vertical at x=83.52 on B.Cu
    T(78.86, 8.95, 78.86, 9.62, SW, "F.Cu", ne)
    T(78.86, 9.62, 82.5, 9.62, SW, "F.Cu", ne)
    V(82.5, 9.62, ne)
    T(82.5, 9.62, 84.5, 9.62, SW, "B.Cu", ne)
    V(84.5, 9.62, ne)
    T(84.5, 9.62, 88, 9.62, SW, "F.Cu", ne)

    # ── /CHG_N: U2.9(27.7,8.75), D1.1(33.21,6), J3.3(88,19.08) ──
    nch = nc("/CHG_N")
    # Route right at y=8.75 past VSYS at x=29.5, up at x=30.5 to D1
    T(27.7, 8.75, 30.5, 8.75, SW, "F.Cu", nch)
    T(30.5, 8.75, 30.5, 5.5, SW, "F.Cu", nch)
    T(30.5, 5.5, 33.21, 5.5, SW, "F.Cu", nch)
    T(33.21, 5.5, 33.21, 6, SW, "F.Cu", nch)
    # D1.1 → J3.3: south on F.Cu to y=14.5, B.Cu east at y=21
    T(33.21, 6, 33.21, 14.5, SW, "F.Cu", nch)
    V(33.21, 14.5, nch)
    T(33.21, 14.5, 33.21, 21, SW, "B.Cu", nch)
    T(33.21, 21, 88, 21, SW, "B.Cu", nch)
    V(88, 21, nch)
    T(88, 21, 88, 19.08, SW, "F.Cu", nch)

    # ── /NTC_SENSE: U2.1(24.3,7.25), R8.2(19,8.51), RT1.1(41.49,10), J3.2(88,16.54) ──
    nnt = nc("/NTC_SENSE")
    # U2.1 → R8.2: left to x=21, down to y=8.51, left
    T(24.3, 7.25, 21, 7.25, SW, "F.Cu", nnt)
    T(21, 7.25, 21, 8.51, SW, "F.Cu", nnt)
    T(21, 8.51, 19, 8.51, SW, "F.Cu", nnt)
    # R8.2 → RT1.1: down at x=16 to y=14, east
    T(19, 8.51, 16, 8.51, SW, "F.Cu", nnt)
    T(16, 8.51, 16, 14, SW, "F.Cu", nnt)
    T(16, 14, 41.49, 14, SW, "F.Cu", nnt)
    T(41.49, 14, 41.49, 10, SW, "F.Cu", nnt)
    # RT1.1 → J3.2: via, B.Cu at y=18
    V(41.49, 14, nnt)
    T(41.49, 14, 41.49, 18, SW, "B.Cu", nnt)
    T(41.49, 18, 88, 18, SW, "B.Cu", nnt)
    V(88, 18, nnt)
    T(88, 18, 88, 16.54, SW, "F.Cu", nnt)

    # ── Net-(D1-A): D1.2(34.79,6) → R6.1(36.49,6) ──
    T(34.79, 6, 36.49, 6, SW, "F.Cu", nc("Net-(D1-A)"))

    # ── Net-(D2-A): D2.2(34.79,10) → R7.1(36.49,10) ──
    T(34.79, 10, 36.49, 10, SW, "F.Cu", nc("Net-(D2-A)"))

    # ── Net-(D2-K): D2.1(33.21,10) → U2.7(26.25,9.7) ──
    nd2k = nc("Net-(D2-K)")
    T(33.21, 10, 31.5, 10, SW, "F.Cu", nd2k)
    T(31.5, 10, 31.5, 9.7, SW, "F.Cu", nd2k)
    T(31.5, 9.7, 26.25, 9.7, SW, "F.Cu", nd2k)

    # ── Net-(J1-CC1): J1.A5(3.5,9.2) → U1.1(9.86,9.05) ──
    # Route right from J1, avoiding S1 shield area at (2.52,6.15)
    ncc1 = nc("Net-(J1-CC1)")
    T(3.5, 9.2, 5.5, 9.2, SW, "F.Cu", ncc1)
    T(5.5, 9.2, 5.5, 9.05, SW, "F.Cu", ncc1)
    T(5.5, 9.05, 9.86, 9.05, SW, "F.Cu", ncc1)

    # ── Net-(J1-CC2): J1.B5(2.15,11.75) → U1.3(9.86,10.95) ──
    ncc2 = nc("Net-(J1-CC2)")
    T(2.15, 11.75, 4.5, 11.75, SW, "F.Cu", ncc2)
    T(4.5, 11.75, 4.5, 10.95, SW, "F.Cu", ncc2)
    T(4.5, 10.95, 9.86, 10.95, SW, "F.Cu", ncc2)

    # ── Net-(R1-Pad1): R1.1(7,11.49) → U1.6(12.14,9.05) ──
    # B.Cu to avoid CC1/CC2, far from S1
    nr1 = nc("Net-(R1-Pad1)")
    V(7, 11.49, nr1)
    T(7, 11.49, 7, 9.05, SW, "B.Cu", nr1)
    T(7, 9.05, 12.14, 9.05, SW, "B.Cu", nr1)
    V(12.14, 9.05, nr1)

    # ── Net-(R2-Pad1): R2.1(9,11.49) → U1.4(12.14,10.95) ──
    # B.Cu to avoid crossing CC2 at y=10.95
    nr2 = nc("Net-(R2-Pad1)")
    V(9, 11.49, nr2)
    T(9, 11.49, 12.14, 11.49, SW, "B.Cu", nr2)
    T(12.14, 11.49, 12.14, 10.95, SW, "B.Cu", nr2)
    V(12.14, 10.95, nr2)

    # ── Net-(U2-ISET): R3.2(22.51,13) → U2.16(25.25,6.3) ──
    ni = nc("Net-(U2-ISET)")
    T(22.51, 13, 22.51, 11, SW, "F.Cu", ni)
    T(22.51, 11, 23.5, 11, SW, "F.Cu", ni)
    T(23.5, 11, 23.5, 6, SW, "F.Cu", ni)
    T(23.5, 6, 25.25, 6, SW, "F.Cu", ni)
    T(25.25, 6, 25.25, 6.3, SW, "F.Cu", ni)

    # ── Net-(U2-TMR): R5.2(24.51,13) → U2.14(26.25,6.3) ──
    # Route: via to B.Cu, south past NTC(y=14), via to F.Cu, left to x=20.5,
    # up to y=4.5, right to x=25.5, via to B.Cu, down to pin
    nt = nc("Net-(U2-TMR)")
    V(24.51, 13, nt)
    T(24.51, 13, 24.51, 15, SW, "B.Cu", nt)
    V(24.51, 15, nt)
    T(24.51, 15, 20.5, 15, SW, "F.Cu", nt)
    T(20.5, 15, 20.5, 4.5, SW, "F.Cu", nt)
    T(20.5, 4.5, 25.5, 4.5, SW, "F.Cu", nt)
    V(25.5, 4.5, nt)
    T(25.5, 4.5, 26.25, 4.5, SW, "B.Cu", nt)
    T(26.25, 4.5, 26.25, 6.3, SW, "B.Cu", nt)
    V(26.25, 6.3, nt)

    # ── Net-(U2-ILIM): R4.2(26.51,13) → U2.12(27.7,7.25) ──
    nil = nc("Net-(U2-ILIM)")
    T(26.51, 13, 29, 13, SW, "F.Cu", nil)
    T(29, 13, 29, 7.25, SW, "F.Cu", nil)
    T(29, 7.25, 27.7, 7.25, SW, "F.Cu", nil)

    # ── Net-(Q1A-D): Q1.3(53.86,8.95) → Q1.6(56.14,7.05) ──
    # Route north of Q1 at x=51 (far from Q1.1 GND pad at 53.86,7.05)
    nqd = nc("Net-(Q1A-D)")
    T(53.86, 8.95, 51, 8.95, PW, "F.Cu", nqd)
    T(51, 8.95, 51, 5.5, PW, "F.Cu", nqd)
    T(51, 5.5, 56.14, 5.5, PW, "F.Cu", nqd)
    T(56.14, 5.5, 56.14, 7.05, PW, "F.Cu", nqd)

    # ── Net-(Q1A-G): Q1.2(53.86,8) → U3.1(46.86,7.05) ──
    nqag = nc("Net-(Q1A-G)")
    T(53.86, 8, 52.5, 8, SW, "F.Cu", nqag)
    T(52.5, 8, 52.5, 6.5, SW, "F.Cu", nqag)
    T(52.5, 6.5, 46.86, 6.5, SW, "F.Cu", nqag)
    T(46.86, 6.5, 46.86, 7.05, SW, "F.Cu", nqag)

    # ── Net-(Q1B-G): Q1.5(56.14,8) → U3.3(46.86,8.95) ──
    # South route avoids VSYS_BOOST at x=57,y=9.5
    nqbg = nc("Net-(Q1B-G)")
    T(56.14, 8, 58, 8, SW, "F.Cu", nqbg)
    T(58, 8, 58, 11.5, SW, "F.Cu", nqbg)
    T(58, 11.5, 44, 11.5, SW, "F.Cu", nqbg)
    T(44, 11.5, 44, 8.95, SW, "F.Cu", nqbg)
    T(44, 8.95, 46.86, 8.95, SW, "F.Cu", nqbg)

    # ── Net-(U4-FB): U4.3(62.86,8.95), R9.2(68.51,12), R10.1(69.49,12) ──
    nfb = nc("Net-(U4-FB)")
    T(68.51, 12, 69.49, 12, SW, "F.Cu", nfb)
    # U4.3 → R9.2: down to y=11, right past EN at x=64
    T(62.86, 8.95, 62.86, 11, SW, "F.Cu", nfb)
    T(62.86, 11, 68.51, 11, SW, "F.Cu", nfb)
    T(68.51, 11, 68.51, 12, SW, "F.Cu", nfb)

    return tracks, vias

# ============================================================
# Generate complete PCB
# ============================================================
def generate_pcb():
    # Parse netlist for pad-net mapping
    netlist_path = os.path.join(PROJECT_DIR, f"{PROJECT_NAME}.kicad_sch")
    # Export netlist
    import subprocess
    nl_path = "/tmp/llups_pcb_netlist.xml"
    subprocess.run(["kicad-cli", "sch", "export", "netlist",
                     "--output", nl_path, "--format", "kicadxml", netlist_path],
                    capture_output=True)

    # Parse netlist XML
    pad_net_map = {}
    net_codes = {"": 0}
    try:
        tree = ET.parse(nl_path)
        root = tree.getroot()
        for net in root.find('nets').findall('net'):
            code = int(net.get('code', '0'))
            name = net.get('name', '')
            net_codes[name] = code
            for node in net.findall('node'):
                pad_net_map[(node.get('ref',''), node.get('pin',''))] = name
    except Exception as e:
        print(f"WARNING: Could not parse netlist: {e}", file=sys.stderr)

    # Get value map from schematic placements
    value_map = {}
    for p in PLACEMENTS:
        value_map[p[0]] = p[2]  # ref -> value

    # Build net definitions string
    net_defs = '\t(net 0 "")\n'
    for name, code in sorted(net_codes.items(), key=lambda x: x[1]):
        if code > 0:
            net_defs += f'\t(net {code} "{name}")\n'

    # Embed footprints
    fp_blocks = []
    for ref, fp_id, cx, cy, rot, layer in PCB_PLACEMENTS:
        value = value_map.get(ref, ref)
        block = embed_footprint(fp_id, ref, value, cx, cy, rot, layer, pad_net_map, net_codes)
        if block:
            fp_blocks.append(block)
        else:
            print(f"WARNING: Could not embed footprint for {ref} ({fp_id})", file=sys.stderr)

    # Generate traces
    pad_positions = get_pcb_pad_positions()
    tracks, vias = generate_pcb_traces(pad_positions, pad_net_map, net_codes)

    # Mounting holes — corners away from USB and routing
    mh_blocks = [
        pcb_mounting_hole(3.5, 55),
        pcb_mounting_hole(86.5, 55),
    ]

    # Board outline (simple rectangle — clean and reliable)
    outline = []
    W, H = BOARD_W, BOARD_H
    outline.append(f'\t(gr_rect (start 0 0) (end {W} {H}) (stroke (width 0.1) (type solid)) (fill none) (layer "Edge.Cuts") (uuid "{uid()}"))')

    # Ground zone on back copper (full board)
    nc_gnd = net_codes.get("GND", 0)
    ground_zone = f"""\t(zone
\t\t(net {nc_gnd})
\t\t(net_name "GND")
\t\t(layer "B.Cu")
\t\t(uuid "{uid()}")
\t\t(hatch edge 0.5)
\t\t(connect_pads
\t\t\t(clearance 0.25)
\t\t)
\t\t(min_thickness 0.2)
\t\t(filled_areas_thickness no)
\t\t(fill
\t\t\t(thermal_gap 0.3)
\t\t\t(thermal_bridge_width 0.3)
\t\t)
\t\t(polygon
\t\t\t(pts
\t\t\t\t(xy 0 0) (xy {W} 0) (xy {W} {H}) (xy 0 {H})
\t\t\t)
\t\t)
\t)"""

    # Ground zone on front copper (fills around components)
    ground_zone_front = f"""\t(zone
\t\t(net {nc_gnd})
\t\t(net_name "GND")
\t\t(layer "F.Cu")
\t\t(uuid "{uid()}")
\t\t(hatch edge 0.5)
\t\t(priority 1)
\t\t(connect_pads
\t\t\t(clearance 0.25)
\t\t)
\t\t(min_thickness 0.2)
\t\t(filled_areas_thickness no)
\t\t(fill
\t\t\t(thermal_gap 0.3)
\t\t\t(thermal_bridge_width 0.3)
\t\t)
\t\t(polygon
\t\t\t(pts
\t\t\t\t(xy 0 0) (xy {W} 0) (xy {W} {H}) (xy 0 {H})
\t\t\t)
\t\t)
\t)"""

    # Assemble PCB
    pcb = f"""(kicad_pcb
\t(version 20241229)
\t(generator "pcbnew")
\t(generator_version "9.0")
\t(general
\t\t(thickness 1.6)
\t\t(legacy_teardrops no)
\t)
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(31 "B.Cu" signal)
\t\t(32 "B.Adhes" user "B.Adhesive")
\t\t(33 "F.Adhes" user "F.Adhesive")
\t\t(34 "B.Paste" user)
\t\t(35 "F.Paste" user)
\t\t(36 "B.SilkS" user "B.Silkscreen")
\t\t(37 "F.SilkS" user "F.Silkscreen")
\t\t(38 "B.Mask" user)
\t\t(39 "F.Mask" user)
\t\t(40 "Dwgs.User" user "User.Drawings")
\t\t(41 "Cmts.User" user "User.Comments")
\t\t(42 "Eco1.User" user "User.Eco1")
\t\t(43 "Eco2.User" user "User.Eco2")
\t\t(44 "Edge.Cuts" user)
\t\t(45 "Margin" user)
\t\t(46 "B.CrtYd" user "B.Courtyard")
\t\t(47 "F.CrtYd" user "F.Courtyard")
\t\t(48 "B.Fab" user)
\t\t(49 "F.Fab" user)
\t\t(50 "User.1" user)
\t\t(51 "User.2" user)
\t)
\t(setup
\t\t(pad_to_mask_clearance 0)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(pcbplotparams
\t\t\t(layerselection 0x00010fc_ffffffff)
\t\t\t(plot_on_all_layers_selection 0x0000000_00000000)
\t\t\t(disableapertmacros no)
\t\t\t(usegerberextensions no)
\t\t\t(usegerberattributes yes)
\t\t\t(usegerberadvancedattributes yes)
\t\t\t(creategerberjobfile yes)
\t\t\t(dashed_line_dash_ratio 12.000000)
\t\t\t(dashed_line_gap_ratio 3.000000)
\t\t\t(svgprecision 4)
\t\t\t(plotframeref no)
\t\t\t(viasonmask no)
\t\t\t(mode 1)
\t\t\t(useauxorigin no)
\t\t\t(hpglpennumber 1)
\t\t\t(hpglpenspeed 20)
\t\t\t(hpglpendiameter 15.000000)
\t\t\t(pdf_front_fp_property_popups yes)
\t\t\t(pdf_back_fp_property_popups yes)
\t\t\t(dxfpolygonmode yes)
\t\t\t(dxfimperialunits yes)
\t\t\t(dxfusepcbnewfont yes)
\t\t\t(psnegative no)
\t\t\t(psa4output no)
\t\t\t(plotreference yes)
\t\t\t(plotvalue yes)
\t\t\t(plotfptext yes)
\t\t\t(plotinvisibletext no)
\t\t\t(sketchpadsonfab no)
\t\t\t(subtractmaskfromsilk no)
\t\t\t(outputformat 1)
\t\t\t(mirror no)
\t\t\t(drillshape 1)
\t\t\t(scaleselection 1)
\t\t\t(outputdirectory "")
\t\t)
\t)

{net_defs}
"""
    # Add footprints
    for block in fp_blocks:
        pcb += block + '\n'

    # Add mounting holes
    for mh in mh_blocks:
        pcb += mh + '\n'

    # Add tracks
    for track in tracks:
        pcb += track + '\n'

    # Add vias
    for via in vias:
        pcb += via + '\n'

    # Add board outline
    for line in outline:
        pcb += line + '\n'

    # Add ground zones
    pcb += ground_zone + '\n'
    pcb += ground_zone_front + '\n'

    pcb += ')\n'

    print(f"PCB: {len(fp_blocks)} footprints, {len(tracks)} traces, {len(vias)} vias", file=sys.stderr)
    return pcb

# ============================================================
# Main
# ============================================================
def main():
    os.makedirs(PROJECT_DIR, exist_ok=True)

    # Generate project file
    proj_path = os.path.join(PROJECT_DIR, f"{PROJECT_NAME}.kicad_pro")
    with open(proj_path, 'w') as f:
        f.write(generate_project())
    print(f"Created {proj_path}")

    # Generate schematic
    sch_path = os.path.join(PROJECT_DIR, f"{PROJECT_NAME}.kicad_sch")
    with open(sch_path, 'w') as f:
        f.write(generate_schematic())
    print(f"Created {sch_path}")

    # Generate PCB
    pcb_path = os.path.join(PROJECT_DIR, f"{PROJECT_NAME}.kicad_pcb")
    with open(pcb_path, 'w') as f:
        f.write(generate_pcb())
    print(f"Created {pcb_path}")

    print(f"\nProject generated in {PROJECT_DIR}")
    print(f"Components: {len([p for p in PLACEMENTS if not p[1].startswith('power:')])} placed")
    print(f"Wire pairs: {len(WIRE_PAIRS)} direct + complex routes")
    print(f"Net labels: {len(LABEL_PINS)} cross-section labels")
    print(f"\nOpen {proj_path} in KiCad to review.")

if __name__ == "__main__":
    main()
