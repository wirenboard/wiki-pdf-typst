#!/usr/bin/env python3
"""Batch generate PDFs for all Wiren Board device pages."""

import subprocess
import sys
import time

DEVICES = [
    # Controllers
    "Wiren_Board_8.5",
    "Wiren_Board_7.4",
    # Interface converters
    "WB-MGE_v.3_Modbus_Ethernet_Gateway",
    "WB-MIO-E_v.2_Modbus_Interface_Converter",
    # Power meters
    "WB-MAP12E_Multi-channel_Modbus_Power_Meter",
    "WB-MAP3E_Modbus_Power_Meter",
    "WB-MAP3ET_Modbus_Power_Meter_With_Transformers",
    "WB-MAP3EV_Modbus_Three_Phase_Voltmeter",
    "WB-MAP3H_Power_Meter",
    # Current transformers
    "ZMCT205D",
    "ZMCT102w",
    "ZMCT134",
    "KCT-6",
    "ZMDCT21",
    "ZEMCTK05-14",
    # Relay modules
    "WB-MR6C_v.3_Modbus_Relay_Modules",
    "WB-MRPS6_Modbus_Relay_Modules",
    "WB-MR14_Modbus_14_Channel_Relay_Module",
    "WB-MRM2-mini_Modbus_Relay_Modules",
    # Sensors
    "WB-MS_v.2_Modbus_Sensor",
    "WB-MSW_v.4_Modbus_Sensor",
    "WB-MSW2_Modbus_Sensor",
    "WB-MAI6_Modbus_Analog_Inputs",
    "WB-M1W2_v.3_1-Wire_to_Modbus_Temperature_Measurement_Module",
    # Dimmers
    "WB-MDM3_230V_Modbus_Dimmer",
    "WB-LED_v.1_Modbus_LED_Dimmer",
    "WB-MRGBW-D_Modbus_LED_Dimmer",
    # IO modules
    "WBIO-DI-WD-14_Discrete_Inputs",
    "WBIO-DO-R10A-8_Relay_Module",
    # Misc
    "WB-MCM8_Modbus_Count_Inputs",
    "WB-MIR_v3_-_Modbus_IR_Remote_Control",
    "WB-MWAC_v.2_Modbus_Water_Consumption_Metering_and_Leak_Monitoring",
    "WB-UPS_v.3_Backup_power_supply",
    "WB-BUSHUB_v1_-_Wire_Connector_Board",
    # Extension modules
    "WBE2-I-OPENTHERM_OpenTherm_Extension_Module",
    "WBMZ6-BATTERY_Backup_Power_Module",
    # Refrigeration
    "WB-REF-U_Carel_and_Eliwell_Modbus_Module",
]

BASE = "https://wiki.wirenboard.com"
success = []
failed = []

for i, page in enumerate(DEVICES):
    print(f"\n[{i+1}/{len(DEVICES)}] {page}", flush=True)
    t0 = time.time()
    result = subprocess.run(
        [sys.executable, "wiki2pdf.py", f"{BASE}/wiki/{page}"],
        capture_output=True, text=True, timeout=120,
    )
    elapsed = time.time() - t0
    if result.returncode == 0:
        print(f"  OK ({elapsed:.1f}s)", flush=True)
        success.append(page)
    else:
        err = result.stderr.strip().split("\n")[-3:]
        print(f"  FAILED ({elapsed:.1f}s): {err[-1]}", flush=True)
        failed.append((page, err[-1]))

print(f"\n=== Results: {len(success)} OK, {len(failed)} failed ===")
for page, err in failed:
    print(f"  FAIL: {page}: {err}")
