#!/usr/bin/env python3
"""Read-only New Era pump status probe for Self_Driving_V9.

This script only sends `DIS` queries and parses returned status lines.
It does NOT run the pump, move servos, or touch spinner/LED hardware.
"""

import argparse
import os
import re
import time
from pathlib import Path
from datetime import datetime

import serial


def _parse_dis_response(raw_bytes):
    if raw_bytes is None:
        text = ""
    elif isinstance(raw_bytes, (bytes, bytearray)):
        text = bytes(raw_bytes).decode(errors="ignore")
    else:
        text = str(raw_bytes)

    clean = "".join(ch for ch in text if ch.isprintable())
    match = re.search(
        r"(?P<address>\d{2})S(?P<status>[A-Za-z\?])"
        r"(?P<infused>[+-]?\d+(?:\.\d+)?)W(?P<withdrawn>[+-]?\d+(?:\.\d+)?)"
        r"(?P<units>UL|ML)",
        clean,
    )
    if match is None:
        return {
            "raw_text": clean.strip(),
            "address": "",
            "status": "",
            "infused_volume": "",
            "withdrawn_volume": "",
            "units": "",
            "infused_volume_ul": "",
            "withdrawn_volume_ul": "",
        }

    units = match.group("units").upper()
    infused = float(match.group("infused"))
    withdrawn = float(match.group("withdrawn"))
    scale = 1.0 if units == "UL" else 1000.0

    return {
        "raw_text": clean.strip(),
        "address": match.group("address"),
        "status": match.group("status").upper(),
        "infused_volume": infused,
        "withdrawn_volume": withdrawn,
        "units": units,
        "infused_volume_ul": infused * scale,
        "withdrawn_volume_ul": withdrawn * scale,
    }


def _infer_port_from_dual_send_commands():
    this_dir = Path(__file__).resolve().parent
    cfg_path = this_dir / "Dual_Send_Commands.py"
    if not cfg_path.exists():
        return None

    try:
        text = cfg_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    match = re.search(r"^\s*syringePort\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def _resolve_port(cli_port):
    if cli_port:
        return cli_port

    env_port = os.environ.get("PUMP_COM_PORT", "").strip()
    if env_port:
        return env_port

    file_port = _infer_port_from_dual_send_commands()
    if file_port:
        return file_port

    return "COM7"


def main():
    parser = argparse.ArgumentParser(description="Read-only pump status probe (`DIS` polling only).")
    parser.add_argument("--port", default="", help="Pump serial port (e.g., COM7).")
    parser.add_argument("--pump", type=int, default=0, help="Pump address number (default: 0).")
    parser.add_argument("--duration-s", type=float, default=10.0, help="Polling duration in seconds.")
    parser.add_argument("--interval-s", type=float, default=0.2, help="Polling interval in seconds.")
    args = parser.parse_args()

    port = _resolve_port(args.port)
    command = f"{int(args.pump)}DIS\r"

    print("=== pump_status_probe_v9 ===")
    print(f"port={port}, pump={int(args.pump)}, duration_s={args.duration_s}, interval_s={args.interval_s}")
    print("This probe is read-only: sends DIS queries only.")
    print(
        "Columns: wall_time_iso, elapsed_s, raw_response, address, status, infused_volume, "
        "withdrawn_volume, units, infused_volume_ul, withdrawn_volume_ul"
    )

    try:
        with serial.Serial(port=port, baudrate=19200, timeout=0.5) as ser:
            try:
                ser.reset_input_buffer()
            except Exception:
                pass

            start = time.monotonic()
            end_at = start + max(0.1, float(args.duration_s))
            while time.monotonic() < end_at:
                wall_time = datetime.now().astimezone().isoformat(timespec="milliseconds")
                ser.write(command.encode("ascii"))
                raw = ser.readline()
                parsed = _parse_dis_response(raw)
                elapsed_s = time.monotonic() - start
                print(
                    f"{wall_time}, {elapsed_s:.3f}, {parsed['raw_text']}, {parsed['address']}, "
                    f"{parsed['status']}, {parsed['infused_volume']}, {parsed['withdrawn_volume']}, "
                    f"{parsed['units']}, {parsed['infused_volume_ul']}, {parsed['withdrawn_volume_ul']}"
                )
                time.sleep(max(0.01, float(args.interval_s)))
    except Exception as exc:
        print(f"ERROR: probe failed: {exc}")
        raise


if __name__ == "__main__":
    main()
