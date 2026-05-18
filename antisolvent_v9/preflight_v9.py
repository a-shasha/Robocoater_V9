#!/usr/bin/env python3
"""
Self_Driving_V9 preflight validation (read-only hardware safety checks).

Safety constraints:
- Does not start spinner.
- Does not dispense pumps.
- Does not move servo.
- Does not turn LEDs on.
- Only checks resource reachability/readiness.
"""

from __future__ import annotations

import ast
import json
import os
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL
    details: str


BASE_DIR = Path(__file__).resolve().parent
RUN_CAMPAIGN_FILE = BASE_DIR / "run_campaign.py"
DUAL_COMMANDS_FILE = BASE_DIR / "Dual_Send_Commands.py"
DUAL_OCEAN_FILE = BASE_DIR / "Dual_Send_OceanFlame.py"
DUAL_CAMERA_FILE = BASE_DIR / "Dual_Send_Camera.py"
FILM_CLASSIFIER_FILE = BASE_DIR / "Analysis_2" / "Film_Classification_2.py"


def _load_constants(py_path: Path) -> dict[str, Any]:
    constants: dict[str, Any] = {}
    source = py_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_path))

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            try:
                constants[target.id] = ast.literal_eval(node.value)
            except Exception:
                continue
    return constants


def _extract_camera_index(camera_file: Path) -> int:
    source = camera_file.read_text(encoding="utf-8")
    match = re.search(r"cv2\.VideoCapture\(\s*(\d+)\s*\)", source)
    if match:
        return int(match.group(1))
    return 0


def _extract_spectrometer_serial(ocean_file: Path) -> str | None:
    source = ocean_file.read_text(encoding="utf-8")
    match = re.search(
        r"Spectrometer\.from_serial_number\(\s*['\"]([^'\"]+)['\"]\s*\)",
        source,
    )
    return match.group(1) if match else None


def _nearest_existing_parent(path: Path) -> Path | None:
    cur = path
    while True:
        if cur.exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def _looks_writable(path: Path) -> bool:
    parent = _nearest_existing_parent(path)
    if parent is None:
        return False
    return os.access(parent, os.W_OK)


def _check_com_port_exists(port_name: str, all_ports: set[str], label: str) -> CheckResult:
    if not port_name:
        return CheckResult(label, "FAIL", "No COM port configured.")
    found = port_name.upper() in all_ports
    if found:
        return CheckResult(label, "PASS", f"{port_name} found in system COM port list.")
    return CheckResult(label, "FAIL", f"{port_name} not found in system COM port list.")


def _check_spectrometer(expected_serial: str | None) -> CheckResult:
    try:
        from seabreeze.spectrometers import list_devices
    except Exception as exc:
        return CheckResult("Ocean Flame detected", "FAIL", f"seabreeze import failed: {exc}")

    try:
        devices = list(list_devices())
    except Exception as exc:
        return CheckResult("Ocean Flame detected", "FAIL", f"Device enumeration failed: {exc}")

    if not devices:
        return CheckResult("Ocean Flame detected", "FAIL", "No spectrometer devices detected.")

    serials: list[str] = []
    for dev in devices:
        serial = None
        for attr in ("serial_number", "serial"):
            val = getattr(dev, attr, None)
            if val:
                serial = str(val)
                break
        if serial is None:
            serial = str(dev)
        serials.append(serial)

    if expected_serial and expected_serial in serials:
        return CheckResult(
            "Ocean Flame detected",
            "PASS",
            f"Detected expected serial {expected_serial}. All detected: {serials}",
        )

    if expected_serial:
        return CheckResult(
            "Ocean Flame detected",
            "WARN",
            f"Spectrometer detected, but expected serial {expected_serial} not found. Detected: {serials}",
        )

    return CheckResult("Ocean Flame detected", "PASS", f"Detected spectrometer(s): {serials}")


def _check_camera(index: int) -> CheckResult:
    try:
        import cv2
    except Exception as exc:
        return CheckResult("Camera frame capture", "FAIL", f"OpenCV import failed: {exc}")

    cam = cv2.VideoCapture(index)
    try:
        if not cam.isOpened():
            return CheckResult("Camera frame capture", "FAIL", f"Could not open camera index {index}.")
        ok, frame = cam.read()
        if not ok or frame is None:
            return CheckResult("Camera frame capture", "FAIL", f"Opened camera {index}, but frame read failed.")
        shape = tuple(int(x) for x in frame.shape)
        return CheckResult("Camera frame capture", "PASS", f"Camera {index} opened and returned frame shape {shape}.")
    finally:
        cam.release()


def _check_model_file(model_folder: Any, model_file: Any) -> CheckResult:
    if not isinstance(model_folder, str) or not isinstance(model_file, str):
        return CheckResult("RF model file exists", "FAIL", "Model path constants not found in Film_Classification_2.py")

    configured = Path(model_folder) / model_file
    local_fallback = (FILM_CLASSIFIER_FILE.parent / model_file).resolve()

    if configured.exists():
        return CheckResult("RF model file exists", "PASS", f"Configured model path exists: {configured}")

    if local_fallback.exists():
        return CheckResult(
            "RF model file exists",
            "FAIL",
            f"Configured model path missing: {configured}. Local copy exists at {local_fallback}, but runtime uses configured path.",
        )

    return CheckResult(
        "RF model file exists",
        "FAIL",
        f"Configured model path missing: {configured}. Local fallback also missing: {local_fallback}",
    )


def _check_campaign_folder(folder_raw: Any) -> tuple[CheckResult, Path | None]:
    if not isinstance(folder_raw, str) or not folder_raw.strip():
        return CheckResult("Campaign output folder", "FAIL", "file_folder is missing/invalid in run_campaign.py"), None

    folder = Path(folder_raw)
    if folder.exists():
        if folder.is_dir():
            return CheckResult("Campaign output folder", "PASS", f"Folder exists: {folder}"), folder
        return CheckResult("Campaign output folder", "FAIL", f"Path exists but is not a directory: {folder}"), None

    if _looks_writable(folder):
        return CheckResult(
            "Campaign output folder",
            "WARN",
            f"Folder does not exist but parent is writable; can be created safely: {folder}",
        ), folder

    return CheckResult(
        "Campaign output folder",
        "FAIL",
        f"Folder does not exist and parent is not writable: {folder}",
    ), folder


def _check_campaign_json(campaign_folder: Path | None) -> tuple[CheckResult, int | None]:
    if campaign_folder is None:
        return CheckResult("Campaign_Experiments.json", "FAIL", "Campaign folder unavailable."), None

    campaign_path = campaign_folder / "Campaign_Experiments.json"
    if campaign_path.exists():
        try:
            with campaign_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return CheckResult(
                    "Campaign_Experiments.json",
                    "PASS",
                    f"Readable dict with {len(data)} entries: {campaign_path}",
                ), len(data)
            if _looks_writable(campaign_path):
                return CheckResult(
                    "Campaign_Experiments.json",
                    "WARN",
                    f"Readable but not a dict ({type(data).__name__}); can be safely reinitialized to {{}}.",
                ), None
            return CheckResult(
                "Campaign_Experiments.json",
                "FAIL",
                f"Readable but not a dict ({type(data).__name__}) and location is not writable.",
            ), None
        except Exception as exc:
            if _looks_writable(campaign_path):
                return CheckResult(
                    "Campaign_Experiments.json",
                    "WARN",
                    f"Unreadable ({exc}); can be safely reinitialized to {{}} with a backup.",
                ), None
            return CheckResult("Campaign_Experiments.json", "FAIL", f"Unreadable and not writable: {exc}"), None

    if _looks_writable(campaign_path):
        return CheckResult(
            "Campaign_Experiments.json",
            "WARN",
            f"Missing file; can be safely initialized as empty dict at {campaign_path}",
        ), 0

    return CheckResult(
        "Campaign_Experiments.json",
        "FAIL",
        f"Missing file and cannot initialize due write permissions: {campaign_path}",
    ), None


def _is_lhs_stage(completed_runs: int | None, lhs_count: int | None, budget: int | None) -> bool:
    if completed_runs is None:
        completed_runs = 0
    if lhs_count is None:
        lhs_count = 0
    if budget is None:
        budget = lhs_count
    learning = min(lhs_count, budget)
    return completed_runs < learning


def _check_holmes_reachability(base_url_raw: Any, in_lhs_stage: bool) -> CheckResult:
    if not isinstance(base_url_raw, str) or not base_url_raw.strip():
        return CheckResult("HOLMES endpoint reachability", "FAIL", "BASE_URL missing/invalid in run_campaign.py")

    parsed = urlparse(base_url_raw)
    host = parsed.hostname
    port = parsed.port
    if host is None:
        return CheckResult("HOLMES endpoint reachability", "FAIL", f"Could not parse host from BASE_URL={base_url_raw}")
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    try:
        with socket.create_connection((host, port), timeout=2.5):
            pass
        return CheckResult(
            "HOLMES endpoint reachability",
            "PASS",
            f"TCP reachable at {host}:{port} ({base_url_raw})",
        )
    except Exception as exc:
        if in_lhs_stage:
            return CheckResult(
                "HOLMES endpoint reachability",
                "WARN",
                f"Unreachable ({exc}). Current stage appears to be LHS, so this is warning-only.",
            )
        return CheckResult(
            "HOLMES endpoint reachability",
            "FAIL",
            f"Unreachable ({exc}). Current stage appears adaptive/BO, so HOLMES is required.",
        )


def _print_table(results: list[CheckResult]) -> None:
    title = "Self_Driving_V9 Preflight Validation"
    print("\n" + title)
    print("=" * len(title))
    print(f"{'Check':<36} {'Status':<6} Details")
    print("-" * 120)
    for r in results:
        print(f"{r.name:<36} {r.status:<6} {r.details}")
    print("-" * 120)
    pass_count = sum(1 for r in results if r.status == "PASS")
    warn_count = sum(1 for r in results if r.status == "WARN")
    fail_count = sum(1 for r in results if r.status == "FAIL")
    print(f"Summary: PASS={pass_count} WARN={warn_count} FAIL={fail_count}")


def main() -> int:
    run_cfg = _load_constants(RUN_CAMPAIGN_FILE)
    commands_cfg = _load_constants(DUAL_COMMANDS_FILE)
    film_cfg = _load_constants(FILM_CLASSIFIER_FILE)

    results: list[CheckResult] = []

    # COM port presence checks (no port opening, read-only enumeration).
    try:
        from serial.tools import list_ports

        all_ports = {str(p.device).upper() for p in list_ports.comports()}
        if not all_ports:
            results.append(CheckResult("Serial ports enumerated", "WARN", "No COM ports found in system list."))
        else:
            results.append(CheckResult("Serial ports enumerated", "PASS", f"Detected ports: {sorted(all_ports)}"))

        arduino_port = str(commands_cfg.get("arduinoPort", "")).strip()
        pump_port = str(commands_cfg.get("syringePort", "")).strip()
        led_port = str(commands_cfg.get("ledPort", "")).strip()

        results.append(_check_com_port_exists(arduino_port, all_ports, "Arduino COM port"))
        results.append(_check_com_port_exists(pump_port, all_ports, "Pump COM port"))
        results.append(_check_com_port_exists(led_port, all_ports, "Reflection LED COM port"))
    except Exception as exc:
        msg = f"pyserial COM enumeration failed: {exc}"
        results.append(CheckResult("Serial ports enumerated", "FAIL", msg))
        results.append(CheckResult("Arduino COM port", "FAIL", msg))
        results.append(CheckResult("Pump COM port", "FAIL", msg))
        results.append(CheckResult("Reflection LED COM port", "FAIL", msg))

    # Spectrometer detection.
    expected_serial = _extract_spectrometer_serial(DUAL_OCEAN_FILE)
    results.append(_check_spectrometer(expected_serial))

    # Camera open + one frame.
    camera_index = _extract_camera_index(DUAL_CAMERA_FILE)
    results.append(_check_camera(camera_index))

    # Model file existence.
    model_folder = film_cfg.get("ml_model_folder")
    model_file = film_cfg.get("my_model_file")
    results.append(_check_model_file(model_folder, model_file))

    # Campaign folder and campaign json checks.
    campaign_folder_result, campaign_folder = _check_campaign_folder(run_cfg.get("file_folder"))
    results.append(campaign_folder_result)

    campaign_json_result, completed_runs = _check_campaign_json(campaign_folder)
    results.append(campaign_json_result)

    # HOLMES check with stage-aware severity.
    lhs_times = run_cfg.get("LHS_DRIP_TIMES")
    lhs_count = len(lhs_times) if isinstance(lhs_times, list) else None
    budget_raw = run_cfg.get("experiment_budget")
    budget = int(budget_raw) if isinstance(budget_raw, (int, float)) else None
    in_lhs_stage = _is_lhs_stage(completed_runs, lhs_count, budget)
    stage_label = "LHS" if in_lhs_stage else "Adaptive/BO"
    results.append(CheckResult("Campaign stage inference", "PASS", f"Inferred stage: {stage_label}"))

    results.append(_check_holmes_reachability(run_cfg.get("BASE_URL"), in_lhs_stage))

    _print_table(results)

    has_fail = any(r.status == "FAIL" for r in results)
    return 1 if has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
