print('Dual Send Commands')

import os
import csv
import serial
import pyfirmata
import time
import pandas as pd
import sys
import contextlib
import io
import threading
import importlib.util
import re
from datetime import datetime
from statistics import mean

sys.path.append("Gas-Quenching/NOYITO-USB-Relay-Module-GUI")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SPINNER_CANDIDATE_DIRS = [
    os.path.normpath(os.path.join(_THIS_DIR, "..", "odrive-code")),
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "odrive-code")),
]

_SPINNER_CONTROL_CANDIDATES = []
for _spinner_dir in _SPINNER_CANDIDATE_DIRS:
    _SPINNER_CONTROL_CANDIDATES.append(os.path.join(_spinner_dir, "odrive-spinner.py"))
    _SPINNER_CONTROL_CANDIDATES.append(os.path.join(_spinner_dir, "odrive_control.py"))


def _load_odrive_controller_class():
    def _build_spinner_module_adapter(spinner_module):
        class SpinnerModuleAdapter:
            def __init__(self):
                self.odrv0 = None

            def connect(self):
                return {"status": "ready"}

            def initialize(self, test_sequence=False):
                if self.odrv0 is None:
                    init_fn = getattr(spinner_module, "initialize_spinner")
                    try:
                        self.odrv0 = init_fn(run_test_sequence=test_sequence)
                    except TypeError:
                        self.odrv0 = init_fn()
                return {"status": "initialized", "test_sequence": test_sequence}

            def set_velocity(self, velocity, vel_ramp_rate=16.67, vel_limit=90):
                if self.odrv0 is None:
                    raise RuntimeError("Spinner adapter is not initialized.")

                axis = self.odrv0.axis0
                axis.controller.config.vel_ramp_rate = vel_ramp_rate
                axis.controller.config.control_mode = spinner_module.ControlMode.VELOCITY_CONTROL
                axis.controller.config.input_mode = spinner_module.InputMode.VEL_RAMP
                axis.controller.config.vel_limit = vel_limit
                axis.controller.input_vel = velocity

                return {
                    "status": "success",
                    "mode": "velocity",
                    "target_velocity": velocity,
                }

            def set_position(self, position, vel_limit=10):
                if self.odrv0 is None:
                    raise RuntimeError("Spinner adapter is not initialized.")

                axis = self.odrv0.axis0
                axis.controller.config.control_mode = spinner_module.ControlMode.POSITION_CONTROL
                axis.controller.config.input_mode = spinner_module.InputMode.PASSTHROUGH
                if hasattr(axis.controller.config, "absolute_setpoints"):
                    axis.controller.config.absolute_setpoints = True
                if hasattr(axis.controller.config, "circular_setpoints"):
                    axis.controller.config.circular_setpoints = True
                axis.controller.config.vel_limit = vel_limit

                if hasattr(axis, "pos_vel_mapper") and hasattr(axis.pos_vel_mapper, "config"):
                    try:
                        axis.pos_vel_mapper.config.offset_valid = True
                    except Exception:
                        pass

                try:
                    if axis.current_state != spinner_module.AxisState.CLOSED_LOOP_CONTROL:
                        axis.requested_state = spinner_module.AxisState.CLOSED_LOOP_CONTROL
                        time.sleep(0.1)
                except Exception:
                    pass

                axis.controller.input_pos = position

                return {
                    "status": "success",
                    "mode": "position",
                    "target_position": position,
                }

        return SpinnerModuleAdapter

    last_error = None

    for module_path in _SPINNER_CONTROL_CANDIDATES:
        if not os.path.isfile(module_path):
            continue
        try:
            module_name = f"_lab_odrive_control_{abs(hash(module_path))}"
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not build a module spec for {module_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            controller_class = getattr(module, "ODriveController", None)
            if controller_class is None and hasattr(module, "initialize_spinner"):
                controller_class = _build_spinner_module_adapter(module)
            if controller_class is None:
                raise AttributeError(
                    f"{module_path} does not define ODriveController or initialize_spinner."
                )
            return controller_class, module_path, None
        except Exception as exc:
            last_error = RuntimeError(f"{module_path}: {exc}")

    if last_error is None:
        last_error = RuntimeError(
            "odrive_control.py was not found. "
            f"Checked: {_SPINNER_CONTROL_CANDIDATES}"
        )
    return None, None, last_error


ODriveController, _odrive_control_module_path, _odrive_control_import_error = _load_odrive_controller_class()
_spinner_controller = None
_spinner_target_rpm = 0.0
_spinner_command_lock = threading.RLock()
_pump_command_lock = threading.RLock()
_event_log_lock = threading.RLock()

# Operation event logging context (updated per sample by orchestration code).
_event_log_context = {
    "campaign_folder": "",
    "sample_id": "",
    "file_name": "",
    "sample_start_monotonic": None,
    "requested_drip_time_s": "",
    "requested_rate_ml_min": "",
    "requested_volume_ul": "",
}


# from usbrelay import USBRelay


def _safe_float_str(value):
    if value is None:
        return ""
    try:
        return f"{float(value):.6f}"
    except Exception:
        return str(value)


def _infer_sample_id(file_name):
    if file_name is None:
        return ""
    try:
        match = re.search(r"(\d+)", str(file_name))
    except Exception:
        return ""
    if match is None:
        return ""
    try:
        return str(int(match.group(1)))
    except Exception:
        return match.group(1)


def _pump_role_name(sn):
    try:
        pump_index = int(sn)
    except Exception:
        return f"pump_{sn}"

    if pump_index == 0:
        return "perovskite"
    if pump_index == 1:
        return "antisolvent"
    if pump_index == 2:
        return "wash"
    return f"pump_{pump_index}"


def configure_operation_event_logger(
    campaign_folder,
    file_name,
    sample_id=None,
    sample_start_monotonic=None,
    requested_drip_time_s=None,
    requested_rate_ml_min=None,
    requested_volume_ul=None,
):
    """Configure per-sample event logging context.

    Safe to call repeatedly; failures are warning-only and never raise.
    """
    global _event_log_context
    try:
        inferred_sample_id = _infer_sample_id(file_name)
        _event_log_context = {
            "campaign_folder": str(campaign_folder or ""),
            "sample_id": str(sample_id) if sample_id not in (None, "") else inferred_sample_id,
            "file_name": str(file_name or ""),
            "sample_start_monotonic": sample_start_monotonic,
            "requested_drip_time_s": requested_drip_time_s if requested_drip_time_s is not None else "",
            "requested_rate_ml_min": requested_rate_ml_min if requested_rate_ml_min is not None else "",
            "requested_volume_ul": requested_volume_ul if requested_volume_ul is not None else "",
        }
    except Exception as exc:
        print(f"WARNING: Failed to configure operation event logger context: {exc}")


def log_operation_event(
    event_name,
    details="",
    sample_id=None,
    file_name=None,
    requested_drip_time_s=None,
    requested_rate_ml_min=None,
    requested_volume_ul=None,
):
    """Append one operation event row to Operation_Event_Log.csv.

    Logging failures are warning-only and never raise.
    """
    try:
        campaign_folder = _event_log_context.get("campaign_folder", "")
        if not campaign_folder:
            print(f"WARNING: Operation event logger has no campaign folder; skipped event '{event_name}'.")
            return

        now = datetime.now().astimezone()
        monotonic_s = time.monotonic()
        sample_start_monotonic = _event_log_context.get("sample_start_monotonic", None)
        elapsed_s = ""
        if sample_start_monotonic is not None:
            try:
                elapsed_s = monotonic_s - float(sample_start_monotonic)
            except Exception:
                elapsed_s = ""

        resolved_file_name = str(file_name) if file_name not in (None, "") else str(_event_log_context.get("file_name", ""))
        resolved_sample_id = (
            str(sample_id)
            if sample_id not in (None, "")
            else str(_event_log_context.get("sample_id", "") or _infer_sample_id(resolved_file_name))
        )
        resolved_drip_time = (
            requested_drip_time_s
            if requested_drip_time_s is not None
            else _event_log_context.get("requested_drip_time_s", "")
        )
        resolved_rate = (
            requested_rate_ml_min
            if requested_rate_ml_min is not None
            else _event_log_context.get("requested_rate_ml_min", "")
        )
        resolved_volume = (
            requested_volume_ul
            if requested_volume_ul is not None
            else _event_log_context.get("requested_volume_ul", "")
        )

        log_path = os.path.join(campaign_folder, "Operation_Event_Log.csv")
        os.makedirs(campaign_folder, exist_ok=True)
        write_header = (not os.path.exists(log_path)) or os.path.getsize(log_path) == 0

        row = {
            "sample_id": resolved_sample_id,
            "file_name": resolved_file_name,
            "event_name": str(event_name),
            "wall_time_iso_with_ms": now.isoformat(timespec="milliseconds"),
            "wall_time_local_mmddyyyy_hhmmss_ms": now.strftime("%m/%d/%Y %H:%M:%S.") + f"{now.microsecond // 1000:03d}",
            "monotonic_s": _safe_float_str(monotonic_s),
            "elapsed_from_sample_start_s": _safe_float_str(elapsed_s) if elapsed_s != "" else "",
            "requested_drip_time_s": _safe_float_str(resolved_drip_time) if resolved_drip_time != "" else "",
            "requested_rate_ml_min": _safe_float_str(resolved_rate) if resolved_rate != "" else "",
            "requested_volume_ul": _safe_float_str(resolved_volume) if resolved_volume != "" else "",
            "details": str(details),
        }

        fieldnames = [
            "sample_id",
            "file_name",
            "event_name",
            "wall_time_iso_with_ms",
            "wall_time_local_mmddyyyy_hhmmss_ms",
            "monotonic_s",
            "elapsed_from_sample_start_s",
            "requested_drip_time_s",
            "requested_rate_ml_min",
            "requested_volume_ul",
            "details",
        ]

        with _event_log_lock:
            with open(log_path, "a", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
                csv_file.flush()

    except Exception as exc:
        print(f"WARNING: Failed to append operation event '{event_name}': {exc}")


### List of Fucntions ###


## Syringe Pump ##
# setSyringePump(sn, diameter, rate, rateUnits)
# changeFlowRate(sn, rate, rateUnits)
# dispense(sn, volume, timeStart, delay)
# prime(sn, volume)


## Arduino ##
# setSpinner(speed, timeStart)
# rampSpinner(speed, rampTime, timeStart)
# stopSpinner(timeStart)
# rot_Over_Spinner()
# def rot_Over_Hotplate():
# plON()
# plOFF()
# nitrogenON()
# nitrogenOFF()


## Broadband LED ##
# turnON_rflc_led():
# turnOff_rflc_led():


## end serial communciation ##
# close_Ser()


## Data lists to be saved and reste ##
# sequenceName
# sequenceTime
# init_List()


## Gas Quenching ##


# function so the list can be reset every run
def init_List():
    global sequenceName, sequenceTime
    sequenceName = []
    sequenceTime = []


### Syringe Pump Fucntions ###


# function to send commands to syringe pumps
# syringes numbered 0, 1, 2, 3 > pump 1, pump 2, pump 3, pump 4
def sendCMD(cmd):
    send = '{command}\r'.format(command=cmd)  # \r is carriage return
    with _pump_command_lock:
        pumpSer.write(send.encode())  # encodes in hex and sends command to specified pump
        response = pumpSer.readline()  # pump always transmits data back
    return response
    # print(self.response.decode())


def send_n_recieve(cmd):
    send = '{command}\r'.format(command=cmd)  # \r is carriage return
    with _pump_command_lock:
        pumpSer.write(send.encode())  # encodes in hex and sends command to specified pump
        response = pumpSer.readline().decode(errors='ignore')  # pump always transmits data back
    # print(response)
    return response


_VALID_PUMP_STATUS_CODES = {ord('I'), ord('W'), ord('S'), ord('P'), ord('T'), ord('U'), ord('X')}

# Pump wait safety timeout in seconds.
# Can be overridden on the lab PC via env var PUMP_WAIT_TIMEOUT_S.
_DEFAULT_PUMP_WAIT_TIMEOUT_S = 120.0
try:
    pumpWaitTimeoutS = float(os.environ.get("PUMP_WAIT_TIMEOUT_S", _DEFAULT_PUMP_WAIT_TIMEOUT_S))
except (TypeError, ValueError):
    pumpWaitTimeoutS = _DEFAULT_PUMP_WAIT_TIMEOUT_S


class PumpTimeoutError(TimeoutError):
    """Raised when a pump does not report stopped status within the configured timeout."""

    def __init__(
        self,
        pump_number,
        command,
        elapsed_s,
        timeout_s,
        stop_command=None,
        stop_status='',
        stop_details='',
    ):
        self.pump_number = int(pump_number)
        self.command = str(command)
        self.elapsed_s = float(elapsed_s)
        self.timeout_s = float(timeout_s)
        self.stop_command = stop_command
        self.stop_status = stop_status
        self.stop_details = stop_details

        msg = (
            f"Pump timeout: pump={self.pump_number}, command='{self.command}', "
            f"elapsed={self.elapsed_s:.2f}s, timeout={self.timeout_s:.2f}s"
        )
        if self.stop_command is not None:
            msg += f", stop_command='{self.stop_command}', stop_status='{self.stop_status}'"
        if self.stop_details:
            msg += f", stop_details={self.stop_details}"
        super().__init__(msg)


def _parse_pump_dis_response(output):
    """Parse a New Era `DIS` response line.

    Expected canonical payload shape (example): `00SI25.04W0.000UL`
    where:
      - `00` is address
      - `I` is status (infusing)
      - `25.04` is infused volume
      - `0.000` is withdrawn volume
      - `UL` is units (UL or ML)
    """
    raw_text = _decode_pump_output_brief(output)
    if output is None:
        clean_text = ""
    elif isinstance(output, (bytes, bytearray)):
        clean_text = bytes(output).decode(errors='ignore')
    else:
        clean_text = str(output)

    # Remove transport/control characters while keeping ASCII payload.
    clean_text = "".join(ch for ch in clean_text if ch.isprintable())

    match = re.search(
        r"(?P<address>\d{2})S(?P<status>[A-Za-z\?])"
        r"(?P<infused>[+-]?\d+(?:\.\d+)?)W(?P<withdrawn>[+-]?\d+(?:\.\d+)?)"
        r"(?P<units>UL|ML)",
        clean_text,
    )

    parsed = {
        "raw_text": raw_text,
        "address": "",
        "status": "",
        "infused_volume": None,
        "withdrawn_volume": None,
        "units": "",
        "infused_volume_ul": None,
        "withdrawn_volume_ul": None,
    }
    if match is None:
        return parsed

    parsed["address"] = match.group("address")
    parsed["status"] = match.group("status").upper()
    parsed["units"] = match.group("units").upper()

    try:
        infused_value = float(match.group("infused"))
    except Exception:
        infused_value = None
    try:
        withdrawn_value = float(match.group("withdrawn"))
    except Exception:
        withdrawn_value = None

    parsed["infused_volume"] = infused_value
    parsed["withdrawn_volume"] = withdrawn_value

    unit_scale = 1.0 if parsed["units"] == "UL" else 1000.0 if parsed["units"] == "ML" else None
    if unit_scale is not None and infused_value is not None:
        parsed["infused_volume_ul"] = infused_value * unit_scale
    if unit_scale is not None and withdrawn_value is not None:
        parsed["withdrawn_volume_ul"] = withdrawn_value * unit_scale

    return parsed


def _extract_pump_status(output):
    """Extract pump status from raw serial response bytes without UTF-8 decode failures."""
    parsed = _parse_pump_dis_response(output)
    status = parsed.get("status", "")
    if len(status) == 1 and ord(status) in _VALID_PUMP_STATUS_CODES:
        return status
    return ''


def _decode_pump_output_brief(output):
    if output is None:
        return "None"
    if isinstance(output, (bytes, bytearray)):
        try:
            text = output.decode(errors='ignore').strip()
            if text:
                return text
        except Exception:
            pass
        return repr(bytes(output))
    return str(output).strip()


def _send_pump_command_locked(cmd_no_cr):
    """Send one raw pump command and return one raw response line.

    Caller must hold _pump_command_lock.
    """
    send = f"{cmd_no_cr}\r"
    pumpSer.write(send.encode())
    return pumpSer.readline()


def _normalize_pump_direction(direction):
    if direction is None:
        return ""
    norm = str(direction).strip().upper()
    if norm in ("I", "INF", "INFUSE"):
        return "INF"
    if norm in ("W", "WDR", "WITHDRAW"):
        return "WDR"
    return ""


def _compute_volume_tolerance_ul(expected_volume_ul, explicit_tolerance_ul=None):
    if explicit_tolerance_ul is not None:
        try:
            value = abs(float(explicit_tolerance_ul))
            if value > 0:
                return value
        except Exception:
            pass

    try:
        expected = abs(float(expected_volume_ul))
    except Exception:
        return 0.5
    return max(0.5, expected * 0.01)


def _select_measured_volume_ul(parsed, expected_direction):
    status = str(parsed.get("status", "") or "").upper()
    direction = _normalize_pump_direction(expected_direction)
    if direction == "":
        direction = "INF" if status == "I" else "WDR"

    if direction == "INF":
        return parsed.get("infused_volume_ul", None), "infused_volume_ul", direction
    return parsed.get("withdrawn_volume_ul", None), "withdrawn_volume_ul", direction


def _is_volume_reached(
    parsed,
    expected_volume_ul,
    expected_direction,
    volume_tolerance_ul=None,
    baseline_measured_ul=None,
):
    try:
        expected_ul = float(expected_volume_ul)
    except Exception:
        return False, None, None, None, None
    if expected_ul < 0:
        return False, None, None, None, None

    tolerance_ul = _compute_volume_tolerance_ul(expected_ul, explicit_tolerance_ul=volume_tolerance_ul)
    status = str(parsed.get("status", "") or "").upper()
    if status not in ("I", "W"):
        return False, tolerance_ul, None, None, None

    measured_ul, measured_field, resolved_direction = _select_measured_volume_ul(
        parsed,
        expected_direction=expected_direction,
    )

    try:
        measured_ul_float = float(measured_ul)
    except Exception:
        return False, tolerance_ul, None, measured_field, None

    if baseline_measured_ul is None:
        baseline_measured_ul = measured_ul_float
    delta_ul = measured_ul_float - float(baseline_measured_ul)
    absolute_reached = (measured_ul_float + tolerance_ul) >= expected_ul
    delta_reached = (delta_ul + tolerance_ul) >= expected_ul
    return (
        absolute_reached or delta_reached,
        tolerance_ul,
        measured_ul_float,
        measured_field,
        {
            "resolved_direction": resolved_direction,
            "baseline_measured_ul": baseline_measured_ul,
            "delta_ul": delta_ul,
            "absolute_reached": absolute_reached,
            "delta_reached": delta_reached,
        },
    )


def _build_pump_wait_completion_info(
    parsed,
    completion_reason,
    expected_volume_ul=None,
    expected_direction=None,
    volume_tolerance_ul=None,
):
    return {
        "completion_reason": str(completion_reason),
        "raw_final_response": parsed.get("raw_text", ""),
        "address": parsed.get("address", ""),
        "parsed_status": parsed.get("status", ""),
        "parsed_infused_volume": parsed.get("infused_volume", None),
        "parsed_withdrawn_volume": parsed.get("withdrawn_volume", None),
        "parsed_units": parsed.get("units", ""),
        "parsed_infused_volume_ul": parsed.get("infused_volume_ul", None),
        "parsed_withdrawn_volume_ul": parsed.get("withdrawn_volume_ul", None),
        "expected_volume_ul": expected_volume_ul,
        "expected_direction": _normalize_pump_direction(expected_direction),
        "volume_tolerance_ul": _compute_volume_tolerance_ul(
            expected_volume_ul, explicit_tolerance_ul=volume_tolerance_ul
        ) if expected_volume_ul is not None else "",
    }


def _pump_wait_completion_details(completion_info):
    if not completion_info:
        return "completion_reason=unknown"

    def _q(value):
        if value is None:
            return ""
        return str(value).replace("'", '"')

    return (
        f"completion_reason={_q(completion_info.get('completion_reason', ''))}, "
        f"raw_final_response='{_q(completion_info.get('raw_final_response', ''))}', "
        f"parsed_status={_q(completion_info.get('parsed_status', ''))}, "
        f"parsed_infused_volume={_q(completion_info.get('parsed_infused_volume', ''))}, "
        f"parsed_withdrawn_volume={_q(completion_info.get('parsed_withdrawn_volume', ''))}, "
        f"parsed_infused_volume_ul={_q(completion_info.get('parsed_infused_volume_ul', ''))}, "
        f"parsed_withdrawn_volume_ul={_q(completion_info.get('parsed_withdrawn_volume_ul', ''))}, "
        f"parsed_units={_q(completion_info.get('parsed_units', ''))}, "
        f"expected_direction={_q(completion_info.get('expected_direction', ''))}, "
        f"expected_volume_ul={_q(completion_info.get('expected_volume_ul', ''))}, "
        f"baseline_measured_ul={_q(completion_info.get('baseline_measured_ul', ''))}, "
        f"delta_measured_ul={_q(completion_info.get('delta_measured_ul', ''))}, "
        f"absolute_reached={_q(completion_info.get('absolute_reached', ''))}, "
        f"delta_reached={_q(completion_info.get('delta_reached', ''))}"
    )


def _attempt_pump_abort_locked(sn):
    """Attempt safest available stop command and report status/details.

    Caller must hold _pump_command_lock.
    """
    stop_cmd = f"{sn}STP"
    details = []
    stop_status = ''

    try:
        stop_output = _send_pump_command_locked(stop_cmd)
        details.append(f"stop_response='{_decode_pump_output_brief(stop_output)}'")
        stop_status = _extract_pump_status(stop_output)
    except Exception as exc:
        details.append(f"stop_response_error='{exc}'")
        return stop_cmd, stop_status, "; ".join(details)

    # Verify current status after stop attempt.
    try:
        verify_output = _send_pump_command_locked(f"{sn}DIS")
        verify_status = _extract_pump_status(verify_output)
        if verify_status:
            stop_status = verify_status
        details.append(f"verify_response='{_decode_pump_output_brief(verify_output)}'")
    except Exception as exc:
        details.append(f"verify_response_error='{exc}'")

    return stop_cmd, stop_status, "; ".join(details)


def _wait_until_pump_stops_locked(
    sn,
    timeout_s=None,
    expected_volume_ul=None,
    expected_direction=None,
    volume_tolerance_ul=None,
):
    """Poll pump status until it reports stopped.

    Caller must hold _pump_command_lock.
    """
    if timeout_s is None:
        timeout_s = pumpWaitTimeoutS
    try:
        timeout_s = float(timeout_s)
    except (TypeError, ValueError):
        timeout_s = _DEFAULT_PUMP_WAIT_TIMEOUT_S
    if timeout_s <= 0:
        timeout_s = _DEFAULT_PUMP_WAIT_TIMEOUT_S

    poll_cmd = '{number}DIS'.format(number=sn)
    start = time.monotonic()
    baseline_measured_ul = None
    baseline_measured_field = ""
    last_parsed = {
        "raw_text": "",
        "address": "",
        "status": "",
        "infused_volume": None,
        "withdrawn_volume": None,
        "units": "",
        "infused_volume_ul": None,
        "withdrawn_volume_ul": None,
    }

    while True:
        output = _send_pump_command_locked(poll_cmd)
        parsed = _parse_pump_dis_response(output)
        last_parsed = parsed
        status = parsed.get("status", "")

        # Capture the first measured value for this command to avoid relying on
        # absolute counters that may persist across commands on some pump firmware.
        if status in ("I", "W"):
            measured_now_ul, measured_field_now, _ = _select_measured_volume_ul(
                parsed,
                expected_direction=expected_direction,
            )
            if baseline_measured_ul is None and measured_now_ul is not None:
                try:
                    baseline_measured_ul = float(measured_now_ul)
                    baseline_measured_field = measured_field_now
                except Exception:
                    pass

        if status == 'S':
            completion_info = _build_pump_wait_completion_info(
                parsed,
                completion_reason="status_S",
                expected_volume_ul=expected_volume_ul,
                expected_direction=expected_direction,
                volume_tolerance_ul=volume_tolerance_ul,
            )
            completion_info["baseline_measured_field"] = baseline_measured_field
            completion_info["baseline_measured_ul"] = baseline_measured_ul
            return completion_info

        # New Era pumps can intermittently remain in I/W status even when the target
        # dispense/withdraw volume is already reached. Treat that as completion to avoid
        # false timeout failures while still requiring the commanded volume threshold.
        volume_reached, tolerance_ul, measured_ul, measured_field, volume_meta = _is_volume_reached(
            parsed,
            expected_volume_ul=expected_volume_ul,
            expected_direction=expected_direction,
            volume_tolerance_ul=volume_tolerance_ul,
            baseline_measured_ul=baseline_measured_ul,
        )
        if volume_reached:
            completion_info = _build_pump_wait_completion_info(
                parsed,
                completion_reason="volume_reached",
                expected_volume_ul=expected_volume_ul,
                expected_direction=expected_direction,
                volume_tolerance_ul=tolerance_ul,
            )
            completion_info["volume_check_field"] = measured_field or ""
            completion_info["volume_check_value_ul"] = measured_ul if measured_ul is not None else ""
            if volume_meta:
                completion_info["volume_check_direction"] = volume_meta.get("resolved_direction", "")
                completion_info["baseline_measured_ul"] = volume_meta.get("baseline_measured_ul", "")
                completion_info["delta_measured_ul"] = volume_meta.get("delta_ul", "")
                completion_info["absolute_reached"] = volume_meta.get("absolute_reached", "")
                completion_info["delta_reached"] = volume_meta.get("delta_reached", "")
            return completion_info

        elapsed_s = time.monotonic() - start
        if elapsed_s >= timeout_s:
            print(
                f"ERROR: Pump {sn} timed out while polling '{poll_cmd}' "
                f"(elapsed {elapsed_s:.2f}s, timeout {timeout_s:.2f}s). Attempting stop..."
            )
            stop_cmd, stop_status, stop_details = _attempt_pump_abort_locked(sn)
            log_operation_event(
                event_name=f"{_pump_role_name(sn)}_pump_timeout",
                details=(
                    f"pump_number={sn}, poll_command='{poll_cmd}', elapsed_s={elapsed_s:.3f}, "
                    f"timeout_s={timeout_s:.3f}, stop_command='{stop_cmd}', "
                    f"stop_status='{stop_status}', stop_details={stop_details}, "
                    f"raw_final_response='{last_parsed.get('raw_text', '')}', "
                    f"parsed_status={last_parsed.get('status', '')}, "
                    f"parsed_infused_volume={last_parsed.get('infused_volume', '')}, "
                    f"parsed_withdrawn_volume={last_parsed.get('withdrawn_volume', '')}, "
                    f"parsed_units={last_parsed.get('units', '')}, "
                    f"expected_volume_ul={expected_volume_ul}"
                ),
            )
            print(
                f"ERROR: Pump {sn} timeout stop attempt complete. "
                f"stop_command='{stop_cmd}', stop_status='{stop_status}', details: {stop_details}, "
                f"raw_final_response='{last_parsed.get('raw_text', '')}', "
                f"parsed_status={last_parsed.get('status', '')}, "
                f"parsed_infused_volume={last_parsed.get('infused_volume', '')}, "
                f"parsed_withdrawn_volume={last_parsed.get('withdrawn_volume', '')}, "
                f"parsed_units={last_parsed.get('units', '')}"
            )
            raise PumpTimeoutError(
                pump_number=sn,
                command=poll_cmd,
                elapsed_s=elapsed_s,
                timeout_s=timeout_s,
                stop_command=stop_cmd,
                stop_status=stop_status,
                stop_details=stop_details,
            )


# functions to set syringe diameter, flow rate & units, and volume units (to UL by defualt)
def setSyringePump(sn, diameter, rate, rateUnits):
    # set syringe diameter 0.1 to 50.0 mm
    # <14.0mm volume units uL
    # >=14.01 to 50.0mm volume units mL
    diameterF = checkPumpFloat(diameter)
    dia = '{number}DIA{float}'.format(number=sn, float=diameterF)
    sendCMD(dia)

    # sets Volume Units, override what is determined by diameter
    # units: UL or ML
    volUnits = '{number} VOL UL'.format(number=sn)  # sets volume to UL for all
    sendCMD(volUnits)

    # set pump flow rate and its unites
    # units UM (uL/min) MM (mL/min) UH (uL/hr) MH (mL/hr)
    rateF = checkPumpFloat(rate)
    rate = '{number} RAT {float} {unit}'.format(number=sn, float=rateF, unit=rateUnits)
    sendCMD(rate)


def changeFlowRate(sn, rate, rateUnits):
    # sets the new flow rate and units
    rateF = checkPumpFloat(rate)
    rateCMD = '{number} RAT {float} {unit}'.format(number=sn, float=rateF, unit=rateUnits)
    sendCMD(rateCMD)
    log_operation_event(
        event_name=f"{_pump_role_name(sn)}_pump_rate_set",
        details=f"pump_number={sn}, rate={rateF}, rate_units={rateUnits}",
    )

    # updates the pump rate variable to the newest value for the input log
    global p1Rate, p2Rate, p3Rate, p4Rate  # global to allow us to change the global variable value
    if sn == 0:
        p1Rate = rate
    elif sn == 1:
        p2Rate = rate
    elif sn == 2:
        p3Rate = rate
    elif sn == 3:
        p4Rate = rate

    # code to check the new rate
    # checkRate = '{number} RAT\r'.format(number=sn)
    # pumpSer.write(checkRate.encode())
    # print(pumpSer.readline().decode())


def getFlowRate(sn):
    cmd = '{number} RAT'.format(number=sn)
    output = send_n_recieve(cmd)
    pumpRate = output[-8:-1]
    units = output[-3:-1]

    # print(pumpRate)
    if units == 'MH':
        rate = str(float(output[4:-3]) * 1000)
    if units == 'UH':
        rate = output[4:-3]
    return pumpRate


def getDiameter(sn):
    cmd = '{number} DIA'.format(number=sn)
    output = send_n_recieve(cmd)
    return output[4:-1]


# set pump to infuse(dispense), moves servo arm over substrate, then starts and moves servo out of way when pumping is done
def dispense(sn, volume, timeStart, delay):
    # moves pump servo arm over substrate based on which pump is selected
    pumpArm.write(angle[sn])

    sequenceName.append('Servo move')  # record time of servo moving
    sequenceTime.append(time.time() - timeStart)

    with _pump_command_lock:
        # set direction to infuse to dispense
        directionINF = '{number} DIR INF'.format(number=sn)
        sendCMD(directionINF)

        # check to make sure its <1000ul. if not, divides by 1000 and sets units to ml, then checks number meets floats rules
        # then set the amount to dispense
        volC = checkVolUnit(sn, volume)
        volF = checkPumpFloat(volC)
        vol = '{number} VOL {float}'.format(number=sn, float=volF)
        sendCMD(vol)

        # run => start pumping; can repeat run command to perform the same task. rate, vol, diameter ect are static
        run = '{number} RUN'.format(number=sn)
        sendCMD(run)

    log_operation_event(
        event_name=f"{_pump_role_name(sn)}_dispense_command_sent",
        details=f"pump_number={sn}, run_command='{run}', requested_volume_ul={volume}, retract_delay_s={delay}",
    )

    sequenceName.append('Start pump')  # record time of syringe pump starting
    sequenceTime.append(time.time() - timeStart)

    # loops until pumping is stopped, then retracts arm
    # real time query of volume dispensed infused (I) or withdrawn (W) and volume units
    # status can be I, W, S, P, T, U, X
    log_operation_event(
        event_name=f"{_pump_role_name(sn)}_dispense_wait_start",
        details=f"pump_number={sn}, requested_volume_ul={volume}, expected_direction=INF",
    )
    with _pump_command_lock:
        wait_completion = _wait_until_pump_stops_locked(
            sn,
            expected_volume_ul=volume,
            expected_direction="INF",
        )
    log_operation_event(
        event_name=f"{_pump_role_name(sn)}_dispense_wait_end",
        details=(
            f"pump_number={sn}, requested_volume_ul={volume}, expected_direction=INF, "
            f"{_pump_wait_completion_details(wait_completion)}"
        ),
    )

    sequenceName.append('Pump done')  # record time of syringe pump stopping
    sequenceTime.append(time.time() - timeStart)

    # exits loop when pumping completed
    # moves pump servo arm back to default position out of the way 2 sec after
    time.sleep(delay)
    pumpArm.write(over_retract)
    sequenceName.append('Servo retract')
    sequenceTime.append(time.time() - timeStart)  # record time syringe servo arm retracts
    time.sleep(1.5)
    pumpArm.write(retract)
    sequenceName.append('Servo retract')
    sequenceTime.append(time.time() - timeStart)  # record time syringe servo arm retracts


# set pump to infuse(dispense),
# does not move servo arm!
def dispense_Only(sn, volume):
    pump_role = _pump_role_name(sn)
    if pump_role == "antisolvent":
        command_event = "antisolvent_prep_command_sent"
        wait_start_event = "antisolvent_prep_wait_start"
        wait_end_event = "antisolvent_prep_wait_end"
    elif pump_role == "perovskite":
        command_event = "perovskite_prep_command_sent"
        wait_start_event = "perovskite_prep_wait_start"
        wait_end_event = "perovskite_prep_wait_end"
    else:
        command_event = f"{pump_role}_dispense_command_sent"
        wait_start_event = f"{pump_role}_dispense_wait_start"
        wait_end_event = f"{pump_role}_dispense_wait_end"

    with _pump_command_lock:
        # set direction to infuse to dispense
        directionINF = '{number} DIR INF'.format(number=sn)
        sendCMD(directionINF)

        # check to make sure its <1000ul. if not, divides by 1000 and sets units to ml, then checks number meets floats rules
        # then set the amount to dispense
        volC = checkVolUnit(sn, volume)
        volF = checkPumpFloat(volC)
        vol = '{number} VOL {float}'.format(number=sn, float=volF)
        sendCMD(vol)

        # run => start pumping; can repeat run command to perform the same task. rate, vol, diameter ect are static
        run = '{number} RUN'.format(number=sn)
        log_operation_event(
            event_name=command_event,
            details=f"pump_number={sn}, run_command='{run}', requested_volume_ul={volume}",
        )
        sendCMD(run)

        # loops until pumping is stopped, then retracts arm
        # real time query of volume dispensed infused (I) or withdrawn (W) and volume units
        # status can be I, W, S, P, T, U, X
        log_operation_event(
            event_name=wait_start_event,
            details=f"pump_number={sn}, requested_volume_ul={volume}, expected_direction=INF",
        )
        wait_completion = _wait_until_pump_stops_locked(
            sn,
            expected_volume_ul=volume,
            expected_direction="INF",
        )
        log_operation_event(
            event_name=wait_end_event,
            details=(
                f"pump_number={sn}, requested_volume_ul={volume}, expected_direction=INF, "
                f"{_pump_wait_completion_details(wait_completion)}"
            ),
        )


# set pump to withdraw (no servo movement)
def withdraw_Only(sn, volume):
    pump_role = _pump_role_name(sn)
    if pump_role == "perovskite":
        command_event = "perovskite_withdraw_command_sent"
        wait_start_event = "perovskite_withdraw_wait_start"
        wait_end_event = "perovskite_withdraw_wait_end"
    else:
        command_event = f"{pump_role}_withdraw_command_sent"
        wait_start_event = f"{pump_role}_withdraw_wait_start"
        wait_end_event = f"{pump_role}_withdraw_wait_end"

    with _pump_command_lock:
        # set direction to withdraw
        directionWDR = '{number} DIR WDR'.format(number=sn)
        sendCMD(directionWDR)

        volC = checkVolUnit(sn, volume)
        volF = checkPumpFloat(volC)
        vol = '{number} VOL {float}'.format(number=sn, float=volF)
        sendCMD(vol)

        run = '{number} RUN'.format(number=sn)
        log_operation_event(
            event_name=command_event,
            details=f"pump_number={sn}, run_command='{run}', requested_volume_ul={volume}",
        )
        sendCMD(run)

        log_operation_event(
            event_name=wait_start_event,
            details=f"pump_number={sn}, requested_volume_ul={volume}, expected_direction=WDR",
        )
        wait_completion = _wait_until_pump_stops_locked(
            sn,
            expected_volume_ul=volume,
            expected_direction="WDR",
        )
        log_operation_event(
            event_name=wait_end_event,
            details=(
                f"pump_number={sn}, requested_volume_ul={volume}, expected_direction=WDR, "
                f"{_pump_wait_completion_details(wait_completion)}"
            ),
        )


# set pump to infuse(dispense), moves servo arm over substrate, then starts and moves servo out of way when pumping is done
def dispense_n_withdraw(sn, volume, timeStart, delay):
    withdraw_Vol = 90

    # moves pump servo arm over substrate based on which pump is selected
    pumpArm.write(angle[sn])

    sequenceName.append('Servo move')  # record time of servo moving
    sequenceTime.append(time.time() - timeStart)

    with _pump_command_lock:
        # set direction to infuse to dispense
        directionINF = '{number} DIR INF'.format(number=sn)
        sendCMD(directionINF)

        # check to make sure its <1000ul. if not, divides by 1000 and sets units to ml, then checks number meets floats rules
        # then set the amount to dispense
        volC = checkVolUnit(sn, (volume))  # + withdraw_Vol))
        volF = checkPumpFloat(volC)
        vol = '{number} VOL {float}'.format(number=sn, float=volF)
        sendCMD(vol)

        # run => start pumping; can repeat run command to perform the same task. rate, vol, diameter ect are static
        run = '{number} RUN'.format(number=sn)
        sendCMD(run)

    sequenceName.append('Start pump')  # record time of syringe pump starting
    sequenceTime.append(time.time() - timeStart)

    # loops until pumping is stopped, then retracts arm
    # real time query of volume dispensed infused (I) or withdrawn (W) and volume units
    # status can be I, W, S, P, T, U, X
    with _pump_command_lock:
        _wait_until_pump_stops_locked(
            sn,
            expected_volume_ul=volume,
            expected_direction="INF",
        )

    sequenceName.append('Pump done')  # record time of syringe pump stopping
    sequenceTime.append(time.time() - timeStart)

    # exits loop when pumping completed
    # moves pump servo arm back to default position out of the way 2 sec after
    time.sleep(delay)
    pumpArm.write(109)
    sequenceName.append('Servo retract')
    sequenceTime.append(time.time() - timeStart)  # record time syringe servo arm retracts
    time.sleep(2)
    pumpArm.write(retract)

    with _pump_command_lock:
        # set direction to withdraw
        directionWDR = '{number} DIR WDR'.format(number=sn)
        sendCMD(directionWDR)

        # check to make sure its <1000ul, if not divides by 1000 and sets units to ml, then check float rules
        # then set the amount to dispense
        volC_WRD = checkVolUnit(sn, withdraw_Vol)  # +100ul is to offset the infuse at the end
        volF_WRD = checkPumpFloat(volC_WRD)
        vol_WRD = '{number} VOL {float}'.format(number=sn, float=volF_WRD)
        sendCMD(vol_WRD)

        # run => start pumping
        run = '{number} RUN'.format(number=sn)
        sendCMD(run)

        _wait_until_pump_stops_locked(
            sn,
            expected_volume_ul=withdraw_Vol,
            expected_direction="WDR",
        )


# set pump to withdraw material out of vial and then proceeds to dispsenes to aliavate air gap
def prime(sn, volume):
    with _pump_command_lock:
        # set direction to withdraw
        directionWDR = '{number} DIR WDR'.format(number=sn)
        sendCMD(directionWDR)

        # check to make sure its <1000ul, if not divides by 1000 and sets units to ml, then check float rules
        # then set the amount to dispense
        volC = checkVolUnit(sn, (volume + 100))  # +100ul is to offset the infuse at the end
        volF = checkPumpFloat(volC)
        vol = '{number} VOL {float}'.format(number=sn, float=volF)
        sendCMD(vol)

        # run => start pumping
        run = '{number} RUN'.format(number=sn)
        sendCMD(run)

        # loops until pumping is stopped, so not to jump ahead on code
        # real time query of volume dispensed infused (I) or withdrawn (W) and volume units
        # status can be I, W, S, P, T, U, X
        _wait_until_pump_stops_locked(
            sn,
            expected_volume_ul=(volume + 100),
            expected_direction="WDR",
        )

        # dispense 100 ul to reduce air gap in syringe
        directionINF = '{number} DIR INF'.format(number=sn)
        sendCMD(directionINF)
        volC = checkVolUnit(sn, 100)
        volF = checkPumpFloat(volC)
        vol = '{number} VOL {float}'.format(number=sn, float=volF)
        sendCMD(vol)
        run = '{number} RUN'.format(number=sn)
        sendCMD(run)


# check to make sure its <1000ul, if not divides by 1000 and sets units to ml
# can't be outside of class due to using self.sendCMD()
def checkVolUnit(sn, volume):
    if volume >= 1000:
        vol = volume / 1000
        volUnitML = '{number} VOL ML'.format(number=sn)  # sets volume to ML
        sendCMD(volUnitML)
        return vol
    else:
        volUnitUL = '{number} VOL UL'.format(number=sn)  # sets volume to UL
        sendCMD(volUnitUL)
        return volume


# float value can be up to 4 digits plus 1 decimal.
# max of 3 digits right of the decimal
def checkPumpFloat(vl):
    val = float(vl)

    if val < 0.001:  # min allowed value
        val = 0.001
        pumpFloat = '{0:1.3f}'.format(val)
    elif val >= 1000:  # max allowed value
        val = 999.9
        pumpFloat = '{0:3.1f}'.format(val)
    elif val >= 100:
        pumpFloat = '{0:3.1f}'.format(val)
    elif val >= 10:
        pumpFloat = '{0:2.2f}'.format(val)
    else:
        pumpFloat = '{0:1.3f}'.format(val)

    return pumpFloat


## Arduino ##
def rpm_to_degrees(speed):
    degrees = round(speed * 0.00935 + 39.069)  # Syringe pump spinner small spinner

    # Setting the degrees too low will get the motor controller stuck off.
    if degrees <= 15:
        degrees = 25

    # degrees = round(speed * 0.006127887447 + 57.35932918)      # opentron # servo takes integers only
    return degrees


def _rpm_to_turns_per_second(speed_rpm):
    return float(speed_rpm) / 60.0


def _rpm_rate_to_turns_per_second_sq(rate_rpm_per_s):
    return float(rate_rpm_per_s) / 60.0


def _run_spinner_controller_call(method, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return method(*args, **kwargs)


def _ensure_spinner_controller():
    global _spinner_controller

    if not useODriveSpinner:
        return None

    with _spinner_command_lock:
        if _spinner_controller is not None:
            return _spinner_controller

        if ODriveController is None:
            raise RuntimeError(
                "ODrive spinner backend is enabled, but no usable ODrive backend could be imported. "
                f"Import status: {_odrive_control_import_error}. "
                f"Checked: {_SPINNER_CONTROL_CANDIDATES}"
            )

        controller = ODriveController()
        try:
            if _odrive_control_module_path:
                print(f"ODrive spinner backend: {_odrive_control_module_path}")
            print("Initializing ODrive spinner...")
            _run_spinner_controller_call(controller.connect)
            _run_spinner_controller_call(controller.initialize, test_sequence=False)
            print("ODrive spinner ready.")
        except Exception as exc:
            raise RuntimeError(
                "Failed to initialize the ODrive spinner backend. "
                f"Initialization status: {exc}"
            ) from exc

        _spinner_controller = controller
        return _spinner_controller


def _spinner_velocity_limit_turns_per_second(target_rpm):
    target_turns_per_second = abs(_rpm_to_turns_per_second(target_rpm))
    margin_turns_per_second = _rpm_to_turns_per_second(spinnerVelocityLimitMarginRPM)
    minimum_limit_turns_per_second = _rpm_to_turns_per_second(spinnerMinimumVelocityLimitRPM)
    return max(minimum_limit_turns_per_second, target_turns_per_second + margin_turns_per_second)


def _command_spinner_rpm(target_rpm, ramp_rpm_per_s):
    global _spinner_target_rpm

    controller = _ensure_spinner_controller()
    target_turns_per_second = _rpm_to_turns_per_second(target_rpm)
    ramp_turns_per_second_sq = max(
        _rpm_rate_to_turns_per_second_sq(spinnerMinimumRampRPMPerS),
        _rpm_rate_to_turns_per_second_sq(ramp_rpm_per_s),
    )
    velocity_limit = _spinner_velocity_limit_turns_per_second(target_rpm)

    with _spinner_command_lock:
        _run_spinner_controller_call(
            controller.set_velocity,
            target_turns_per_second,
            vel_ramp_rate=ramp_turns_per_second_sq,
            vel_limit=velocity_limit,
        )
        _spinner_target_rpm = float(target_rpm)


def _normalize_spinner_turns(turns):
    turns_float = float(turns)
    turns_norm = turns_float % 1.0
    if turns_norm < 0:
        turns_norm += 1.0
    return turns_norm


def _command_spinner_position_turns(target_turns, vel_limit_turns_per_s=10.0):
    controller = _ensure_spinner_controller()
    set_position_fn = getattr(controller, "set_position", None)
    if not callable(set_position_fn):
        raise RuntimeError("Active ODrive spinner backend does not support position commands.")

    target_turns_norm = _normalize_spinner_turns(target_turns)
    velocity_limit = max(0.1, float(vel_limit_turns_per_s))

    with _spinner_command_lock:
        _run_spinner_controller_call(
            set_position_fn,
            target_turns_norm,
            vel_limit=velocity_limit,
        )


def _command_spinner_position_degrees(target_degrees, vel_limit_turns_per_s=10.0):
    target_turns = _normalize_spinner_turns(float(target_degrees) / 360.0)
    _command_spinner_position_turns(target_turns, vel_limit_turns_per_s=vel_limit_turns_per_s)


# if spinner is already spinning, then can just change the speed without ramp
def setSpinner(speed, timeStart):
    target_rpm = max(0.0, float(speed))

    if useODriveSpinner:
        _command_spinner_rpm(target_rpm, spinnerDefaultAccelRPMPerS)
        sequenceName.append('Set Spinner to ' + str(target_rpm) + ' rpm')
        sequenceTime.append(time.time() - timeStart)
        return

    degrees = rpm_to_degrees(target_rpm)

    if target_rpm < 1600:
        sequenceName.append('Start Spinner at 35 degrees')  # can go as low as 31 but shakes some    #2000 rpm
        sequenceTime.append(time.time() - timeStart)  # record time spinner starts

        spinner.write(35)  # shakes at but doesnt start spinning
        time.sleep(3)

    spinner.write(degrees)

    sequenceName.append('Set Spinner to ' + str(speed) + '(' + str(degrees) + ' degree)')
    sequenceTime.append(time.time() - timeStart)  # record time spinner set to specified speed


# function that ramps the spinner speed from its current RPM to the target RPM
def rampSpinner(speed, rampTime, timeStart):
    target_rpm = max(0.0, float(speed))
    ramp_time_s = max(0.0, float(rampTime))

    sequenceName.append('Start spinner fucntion')  # record time spinning starts
    sequenceTime.append(time.time() - timeStart)

    if useODriveSpinner:
        current_rpm = max(0.0, float(_spinner_target_rpm))
        if ramp_time_s <= 0:
            ramp_rpm_per_s = spinnerDefaultAccelRPMPerS
        else:
            ramp_rpm_per_s = abs(target_rpm - current_rpm) / ramp_time_s
        _command_spinner_rpm(target_rpm, ramp_rpm_per_s)
        if ramp_time_s > 0:
            time.sleep(ramp_time_s)
    else:
        iterations = max(1, int(target_rpm / 10))
        ramp_rate = ramp_time_s / iterations if iterations > 0 else 0

        for x in range(iterations + 1):  # range only works with integers
            degrees = rpm_to_degrees(x)
            spinner.write(degrees)
            if ramp_rate > 0:
                time.sleep(ramp_rate)

    sequenceName.append('End spinner function')  # record time spinner speed is set
    sequenceTime.append(time.time() - timeStart)


# stops spinner
def stopSpinner(timeStart):
    sequenceName.append('Stop Spinner')  # record time of stopping spinner
    sequenceTime.append(time.time() - timeStart)

    if useODriveSpinner:
        if _spinner_controller is not None:
            current_rpm = max(0.0, float(_spinner_target_rpm))
            stop_ramp_rpm_per_s = spinnerDefaultDecelRPMPerS
            if current_rpm > 0:
                stop_ramp_rpm_per_s = max(
                    spinnerDefaultDecelRPMPerS,
                    current_rpm / max(0.1, spinnerTargetStopTimeS),
                )
                _command_spinner_rpm(0.0, stop_ramp_rpm_per_s)
            if spinnerStopAtFixedAngle:
                settle_time_s = spinnerStopPositionSettleMarginS
                if current_rpm > 0 and stop_ramp_rpm_per_s > 0:
                    settle_time_s += current_rpm / stop_ramp_rpm_per_s
                settle_time_s = min(spinnerStopPositionMaxWaitS, max(0.0, settle_time_s))
                if settle_time_s > 0:
                    time.sleep(settle_time_s)
                try:
                    _command_spinner_position_degrees(
                        spinnerStopAngleDeg,
                        vel_limit_turns_per_s=spinnerStopPositionVelLimitTurnsPerS,
                    )
                except Exception as exc:
                    print(
                        "WARNING: ODrive fixed-angle stop command failed: "
                        f"target_angle_deg={spinnerStopAngleDeg}, error={exc}"
                    )
        sequenceName.append('End stop Spinner')
        sequenceTime.append(time.time() - timeStart)
        return

    spinner.write(25)  # anything below 74 degrees is off
    # takes about 5 seconds to fully slow down spinning
    # self.magnet.write(1)    # turn on magnet over the spinner

    sequenceName.append('End stop Spinner')  # record time spinner stops
    sequenceTime.append(time.time() - timeStart)


# function to rotates uv-vis servo to position over spinner and hotplate
rotTime = 0.001


def rot_Over_Spinner():
    spinnerPos = 167
    currentPos = lightArm.read()

    if currentPos is not spinnerPos:
        for i in range(spinnerPos - currentPos + 1):  # goes 0 to 166 +1
            lightArm.write(currentPos + i)
            time.sleep(rotTime)


def rot_Over_Hotplate():
    hotplatePos = 0
    currentPos = lightArm.read()

    if currentPos is not hotplatePos:
        for i in range(currentPos - hotplatePos + 1):  # goes 0 to 166 +1
            lightArm.write(currentPos - i)
            time.sleep(rotTime)


# controls transistor relay for TTL logic of Thorlab's led cube for PL
def plON():
    plLED.write(1)


def plOFF():
    plLED.write(0)


# controls transistor relay to supply power to open the normally closed solenoid valve
def nitrogenON(self):
    self.nValve.write(1)


def nitrogenOFF(self):
    self.nValve.write(0)


def set_power(power):  # expects a power from 0 to 100
    percent = power / 100  # wants a percent
    irLamp.write(percent)
    print(percent)


def measureTemp():
    cArray = []
    for i in range(20):
        vOut = kTemp.read() * 5.16
        celcius = (vOut - 1.25) / 0.005
        cArray.append(celcius)
        time.sleep(.05)
    temp = round(mean(cArray), 2)

    print(temp)


def measureTemp_loop():
    while True:
        measureTemp()


### Broadband LED ###


def write_led(code):
    code = str(code) + '\n'
    ledSer.write(code.encode('UTF-8'))  # encode in unicode 8 bit

    # 'p10 sets the power to 10% \n\
    # m2 sets strobe mode \n\
    # f5 sets frequency to 5 Hz etc. \n\
    # see the other cmds in the manual'


def turnON_rflc_led():
    ledPower = 'p20'
    write_led(ledPower)  # set led to 35% power


def turnOff_rflc_led():
    write_led('p0')


## Close serial ports ##
def close_Ser():  # close port and exit the py
    ledSer.close()
    # pumSer.close()


# Nitrogen Gas Quenching


def doQuench(sn, timeStart, duration):
    relay = USBRelay(usbRelayPort)
    relay.connect()

    sequenceName.append('Servo move over substrate for gas quenching')  # record time of servo moving
    sequenceTime.append(time.time() - timeStart)

    # moves the servo arm over substrate based on which pump is selected
    pumpArm.write(angle[sn])

    # Wait one second for the arm to stop moving
    time.sleep(1)

    # Turn on gas solenoid
    print("Gas Quenching Valve Opened")
    relay.relay_on(1)

    sequenceName.append('Gas Valve Opened')
    sequenceTime.append(time.time() - timeStart)

    # Wait to turn off gas
    time.sleep(duration)

    # Turn off gas solenoid
    print("Gas Quenching Valve Closed")
    relay.relay_off(1)

    sequenceName.append('Gas Valve Closed')
    sequenceTime.append(time.time() - timeStart)

    # Return pump arm to home position
    retract = 90
    pumpArm.write(retract)

    sequenceName.append('Servo moved home')  # record time of servo moving
    sequenceTime.append(time.time() - timeStart)

    relay.disconnect()


### Initialization ###


# initiates serial communication with arduino, syringe pump, and broandband LED


arduinoPort = 'COM3'  # 'ttyAMC0' # Arduino Uno
syringePort = 'COM7'  # 'ttyUSB0' # Prolific USB-to-serial Comm Port
ledPort = 'COM4'  # 'ttyUSB1' # USB SERIAL PORT
useODriveSpinner = True  # Route spinner control through the ODrive backend while keeping recipe units in RPM.
spinnerDefaultAccelRPMPerS = 1500.0  # Default direct speed-change ramp for baseline and steady-state commands.
spinnerDefaultDecelRPMPerS = 1500.0  # Default stop ramp when no recipe-specific ramp time is provided.
spinnerMinimumRampRPMPerS = 60.0  # Prevent zero-ramp commands from confusing the ODrive velocity ramp controller.
spinnerMinimumVelocityLimitRPM = 7600.0  # Must exceed the highest legacy recipe speed, including wash at 7000 RPM.
spinnerVelocityLimitMarginRPM = 600.0  # Small control headroom above the requested speed.
spinnerTargetStopTimeS = 5.0  # Match the legacy expectation that the spinner needs about five seconds to stop.
spinnerStopAtFixedAngle = True  # After ramping down to zero, command position control to a fixed angular setpoint.
spinnerStopAngleDeg = 0.0  # Fixed post-spin parking angle in degrees; 0 and 360 are equivalent.
spinnerStopPositionVelLimitTurnsPerS = 2.0  # Position-mode velocity limit while parking to fixed angle.
spinnerStopPositionSettleMarginS = 0.25  # Extra wait after estimated deceleration before issuing park command.
spinnerStopPositionMaxWaitS = 6.0  # Cap on stop-to-park settle wait.
usbRelayPort = "COM5"  # CH340

# arduinoPort =  'ttyACM0' # 'COM11'  # Arduino Uno
# syringePort = 'ttyUSB0' #'COM24'  # Prolific USB-to-serial Comm Port
# ledPort = 'ttyUSB1' #'COM3'


## sets serial connection with the syringe pumps ##


# requires 19200 baudrate and 8N1 format with 0.5 sec timeout for SAFE mode
pumpSer = serial.Serial(syringePort, 19200, timeout=0.5)

# sets up syringe pumps
# rateUnits UM (uL/min) MM (mL/min) UH (uL/hr) MH (mL/hr); MM preferred
p1Rate = 4.2
p1Unit = 'MM'
p2Rate = 4.2
p2Unit = 'MM'
p3Rate = 14.2
p3Unit = 'MM'
p4Rate = 4.2
p4Unit = 'MM'

# def setSyringePump(pump number, syringe diameter, flow rate, rate Units):
# 1 mL Syringes: 4.69; min .0000012,  max 0.881 MM
# 5 mL Syringes: 12.45; min .307,  max 6.209
# 20 mL Syringes: 20.05; min 0.7968, max 16.1
# setSyringePump(0, 20.05, p1Rate, p1Unit)  # syringe pump no. 1
setSyringePump(0, 12.45, 4.2, 'MM')
# setSyringePump(1, 4.69, 4.2, p2Unit)  # syringe pump no. 2


setSyringePump(1, 20.05, p2Rate, p2Unit)  # syringe pump no. 2
setSyringePump(2, 12.45, p3Rate, p3Unit)  # syringe pump no. 3
setSyringePump(3, 12.45, p4Rate, p4Unit)  # syringe pump no. 4

## set up serial connection with arduino uno and establish pin connections ##
arduinoB = pyfirmata.Arduino(arduinoPort)  # arduino uno #if MEGA then use ArduinoMega(arduinoPort)
it = pyfirmata.util.Iterator(arduinoB)
it.start()

# set up pin
# a: analog,  d: digital
# i: input, o: output, s: servo, p: pwm
# servo 0-180
# pwm 0-255 or a float value 0 to 1.0
spinner = None
if not useODriveSpinner:
    spinner = arduinoB.get_pin('d:9:s')
pumpArm = arduinoB.get_pin('d:10:s')
# lightArm = arduinoB.get_pin('d:6:s')
plLED = arduinoB.get_pin('d:7:o')
irLamp = arduinoB.get_pin('d:6:p')
# nValve = arduinoB.get_pin('d:8:o')
# self.magnet = self.arduinoB.get_pin('d:4:o')
kTemp = arduinoB.get_pin('a:0:i')

# angle = [85, 92, 99, 106]  # [84, 91, 98, 105]        # for syringes 0,1,2,3
# angle = [77, 84, 90, 97] #[82, 89, 96, ]  # old [91, 104, 97, 104] # for 45 degree arm


## 45 degree
# angle = [86, 91, 102, 102]


## top down
# angle =  [73, 68, 63, 58] # Normal
# angle =  [73, 58, 68, 63] # QD
# angle =  [72, 73, 57, 63] # OPV
# angle =  [73, 67, 57, 63] # Perovskite washing = 3rd pump but 4th spot


# !!!!!!!! Angle of 80 does not block light for gas quenching nozzle.
# Angle of 78 is close to center
angle = [63, 73, 58, 63, 80]  # Gas Quench Tube & Perovskite washing = 3rd pump but 4th spot

# angle =  [73, 85, 57, 63] # for angled perovskite arm


retract = 90
over_retract = 95

pumpArm.write(retract)  # 65 top, 130 bottom
# lightArm.write(167)         # 167 is over center of spinner
if not useODriveSpinner and spinner is not None:
    spinner.write(25)  # initialize spinner; hear it chime 3 times
plLED.write(0)  # ensures PL led is off to start
irLamp.write(0)

## set up serial communication with broadband LED for reflection measurements ##
error = False
try:
    ledSer = serial.Serial(port=ledPort, baudrate=115200, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                           timeout=0.1, write_timeout=0.1, stopbits=serial.STOPBITS_ONE)  # 8N1 format

    while ledSer.inWaiting() == 0:  # wait for the lightsource to wake up and return some data (this may take some s)
        time.sleep(0.1)
except:  # in case of an error, do this:
    print('LED Serial Port Would Not Open')
    error = True
if error:
    close_Ser()
else:
    time.sleep(0.1)  # add some time to retrieve
    size = ledSer.inWaiting()
    response = ledSer.read(size)  # get entire response
    # print(response.decode('ASCII')) #print in readible form

turnOff_rflc_led()  # is on full brightness by default

# create list to store real times in which everything occurs
sequenceName = []
sequenceTime = []
