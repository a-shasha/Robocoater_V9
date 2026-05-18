print('Dual Send Commands')

import os
import ctypes
import serial
import serial.tools.list_ports
import pyfirmata
import time
import pandas as pd
import sys
import subprocess
import zipfile
import json
import base64
import io
import contextlib
import threading
import importlib.util
from statistics import mean

if os.name == 'nt':
    import ctypes.wintypes as wintypes
else:
    wintypes = None


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_RELAY_CANDIDATE_DIRS = [
    os.path.normpath(
        os.path.join(
            _THIS_DIR,
            "..",
            "Gas-Quenching",
            "NOYITO-USB-Relay-Module-GUI",
        )
    ),
    os.path.normpath(
        os.path.join(
            _THIS_DIR,
            "..",
            "..",
            "..",
            "Gas-Quenching",
            "NOYITO-USB-Relay-Module-GUI",
        )
    ),
    os.path.normpath(
        os.path.join(
            _THIS_DIR,
            "..",
            "..",
            "..",
            "..",
            "Gas-Quenching",
            "NOYITO-USB-Relay-Module-GUI",
        )
    ),
]

for _relay_dir in _RELAY_CANDIDATE_DIRS:
    if os.path.isdir(_relay_dir) and _relay_dir not in sys.path:
        # Prefer the first valid relay package so we do not accidentally import a stale copy.
        sys.path.insert(0, _relay_dir)
        break

_SPINNER_CANDIDATE_DIRS = [
    os.path.normpath(os.path.join(_THIS_DIR, "..", "odrive-code")),
    os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "odrive-code")),
]

_SPINNER_CONTROL_CANDIDATES = []
for _spinner_dir in _SPINNER_CANDIDATE_DIRS:
    _SPINNER_CONTROL_CANDIDATES.append(os.path.join(_spinner_dir, "odrive-spinner.py"))
    _SPINNER_CONTROL_CANDIDATES.append(os.path.join(_spinner_dir, "odrive_control.py"))

try:
    from usbrelay import USBRelay
except Exception:
    USBRelay = None

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


# Relay timing constants taken from the NOYITO usbrelay.py implementation.
RELAY_CONNECT_SETTLE_S = 2.0
GAS_QUENCH_SERVO_SETTLE_S = 1.0
GAS_QUENCH_PRETRIGGER_S = RELAY_CONNECT_SETTLE_S + GAS_QUENCH_SERVO_SETTLE_S

_RELAY_VENDOR_DLL_RELATIVE_PATH = os.path.join(
    "NOYITO-Provided-Documentation-Software-Drivers",
    "USB Relay External Use Development Library",
    "usb_relay_dll",
    "usb_relay_device.dll",
)
_RELAY_VENDOR_ZIP_RELATIVE_PATH = os.path.join(
    "NOYITO-Provided-Documentation-Software-Drivers",
    "USB Relay External Use Development Library.zip",
)
_RELAY_VENDOR_COMMAND_RELATIVE_PATH = os.path.join(
    "NOYITO-Provided-Documentation-Software-Drivers",
    "USB Relay External Use Development Library",
    "TestApp",
    "CommandApp_USBRelay.exe",
)
_RELAY_VENDOR_BUNDLE_DIR_RELATIVE_PATH = os.path.join(
    "NOYITO-Provided-Documentation-Software-Drivers",
    "USB Relay External Use Development Library",
)
_RELAY_VENDOR_DLL_CANDIDATES = [
    os.path.join(_relay_dir, _RELAY_VENDOR_DLL_RELATIVE_PATH)
    for _relay_dir in _RELAY_CANDIDATE_DIRS
]
_RELAY_VENDOR_ZIP_CANDIDATES = [
    os.path.join(_relay_dir, _RELAY_VENDOR_ZIP_RELATIVE_PATH)
    for _relay_dir in _RELAY_CANDIDATE_DIRS
]
_RELAY_VENDOR_COMMAND_CANDIDATES = [
    os.path.join(_relay_dir, _RELAY_VENDOR_COMMAND_RELATIVE_PATH)
    for _relay_dir in _RELAY_CANDIDATE_DIRS
]
_RELAY_VENDOR_BUNDLE_DIR_CANDIDATES = [
    os.path.join(_relay_dir, _RELAY_VENDOR_BUNDLE_DIR_RELATIVE_PATH)
    for _relay_dir in _RELAY_CANDIDATE_DIRS
]


class _USBRelayDeviceInfo(ctypes.Structure):
    pass


_USBRelayDeviceInfoPtr = ctypes.POINTER(_USBRelayDeviceInfo)
_USBRelayDeviceInfo._fields_ = [
    ("serial_number", ctypes.POINTER(ctypes.c_ubyte)),
    ("device_path", ctypes.c_char_p),
    ("type", ctypes.c_int),
    ("next", _USBRelayDeviceInfoPtr),
]

_vendor_usb_relay_lib = None
_vendor_usb_relay_lib_error = None
_resolved_usb_relay_target = None
_resolved_usb_relay_target_key = None
_spinner_controller = None
_spinner_target_rpm = 0.0
_spinner_command_lock = threading.RLock()

USB_RELAY_HID_VENDOR_ID = 0x16C0
USB_RELAY_HID_PRODUCT_ID = 0x05DF
USB_RELAY_HID_PRODUCT_LABEL = "USBRelay4(4ch)"


def _ensure_vendor_usb_relay_bundle_extracted():
    """Extract the vendor relay bundle from the shipped zip if the DLL tools are not yet unpacked."""
    for bundle_dir in _RELAY_VENDOR_BUNDLE_DIR_CANDIDATES:
        if os.path.isdir(bundle_dir):
            return

    last_error = None
    for zip_path, bundle_dir in zip(_RELAY_VENDOR_ZIP_CANDIDATES, _RELAY_VENDOR_BUNDLE_DIR_CANDIDATES):
        if not os.path.isfile(zip_path):
            continue
        try:
            target_root = os.path.dirname(bundle_dir)
            os.makedirs(target_root, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zip_file:
                zip_file.extractall(target_root)
            if os.path.isdir(bundle_dir):
                return
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise RuntimeError(
            "Vendor USB relay bundle zip was found but could not be extracted. "
            f"Checked zips: {_RELAY_VENDOR_ZIP_CANDIDATES}. "
            f"Last error: {last_error}"
        )


def _find_existing_vendor_command_app():
    for command_path in _RELAY_VENDOR_COMMAND_CANDIDATES:
        if os.path.isfile(command_path):
            return command_path
    return None


def _find_vendor_powershell_host():
    """Return a PowerShell host that can load the vendor relay DLL bitness."""
    if os.name != 'nt':
        return None

    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    is_64bit_python = ctypes.sizeof(ctypes.c_void_p) == 8
    candidates = []

    if is_64bit_python:
        candidates.append(
            os.path.join(system_root, "SysWOW64", "WindowsPowerShell", "v1.0", "powershell.exe")
        )
    candidates.append(
        os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    )

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _enumerate_vendor_usb_relays_via_helper():
    """Enumerate relay serials through the vendor DLL in a helper process that matches DLL bitness."""
    if os.name != 'nt':
        return []

    powershell_host = _find_vendor_powershell_host()
    if powershell_host is None:
        raise RuntimeError(
            "No compatible PowerShell host was found to enumerate the vendor USB relay DLL."
        )

    dll_path = None
    for candidate in _RELAY_VENDOR_DLL_CANDIDATES:
        if os.path.isfile(candidate):
            dll_path = candidate
            break
    if dll_path is None:
        raise RuntimeError(
            "Vendor USB relay DLL was not found after bundle extraction. "
            f"Checked: {_RELAY_VENDOR_DLL_CANDIDATES}"
        )

    script = r'''
$ErrorActionPreference = "Stop"
$dllPath = $env:USB_RELAY_VENDOR_DLL_PATH
if (-not (Test-Path $dllPath)) {
    throw "Vendor DLL not found at $dllPath"
}
$dllDir = Split-Path -Parent $dllPath
$env:PATH = "$dllDir;$env:PATH"
Set-Location $dllDir

$signature = @"
using System;
using System.Runtime.InteropServices;

public static class UsbRelayNative
{
    [StructLayout(LayoutKind.Sequential)]
    public struct usb_relay_device_info
    {
        public IntPtr serial_number;
        public IntPtr device_path;
        public Int32 type;
        public IntPtr next;
    }

    [DllImport("usb_relay_device.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern Int32 usb_relay_init();

    [DllImport("usb_relay_device.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern Int32 usb_relay_exit();

    [DllImport("usb_relay_device.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr usb_relay_device_enumerate();

    [DllImport("usb_relay_device.dll", CallingConvention = CallingConvention.Cdecl)]
    public static extern void usb_relay_device_free_enumerate(IntPtr p);
}
"@

Add-Type -TypeDefinition $signature -Language CSharp

$initStatus = [UsbRelayNative]::usb_relay_init()
if ($initStatus -ne 0) {
    throw "usb_relay_init failed with status $initStatus"
}

$head = [UsbRelayNative]::usb_relay_device_enumerate()
try {
    $devices = New-Object System.Collections.ArrayList
    $current = $head
    while ($current -ne [IntPtr]::Zero) {
        $info = [System.Runtime.InteropServices.Marshal]::PtrToStructure(
            $current,
            [type][UsbRelayNative+usb_relay_device_info]
        )
        $serial = ""
        $path = ""
        if ($info.serial_number -ne [IntPtr]::Zero) {
            $serial = [System.Runtime.InteropServices.Marshal]::PtrToStringAnsi($info.serial_number)
        }
        if ($info.device_path -ne [IntPtr]::Zero) {
            $path = [System.Runtime.InteropServices.Marshal]::PtrToStringAnsi($info.device_path)
        }
        [void]$devices.Add([pscustomobject]@{
            serial_number = $serial
            device_path = $path
            type = $info.type
        })
        $current = $info.next
    }
    [Console]::Out.Write(($devices | ConvertTo-Json -Compress))
}
finally {
    if ($head -ne [IntPtr]::Zero) {
        [UsbRelayNative]::usb_relay_device_free_enumerate($head)
    }
    [void][UsbRelayNative]::usb_relay_exit()
}
'''

    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    env = os.environ.copy()
    env["USB_RELAY_VENDOR_DLL_PATH"] = dll_path

    result = subprocess.run(
        [
            powershell_host,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded_script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Vendor relay helper enumeration failed. "
            f"PowerShell host: {powershell_host}. Return code: {result.returncode}. "
            f"stdout: {result.stdout.strip()} stderr: {result.stderr.strip()}"
        )

    output = (result.stdout or "").strip()
    if not output:
        return []

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Vendor relay helper enumeration returned non-JSON output. "
            f"Output: {output}"
        ) from exc

    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    raise RuntimeError(
        "Vendor relay helper enumeration returned an unexpected JSON payload. "
        f"Payload type: {type(parsed).__name__}"
    )


def _enumerate_windows_hid_relays():
    """Enumerate HID relay devices using the Windows HID/SetupAPI stack."""
    if os.name != 'nt':
        return []

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class _SPDeviceInterfaceData(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("InterfaceClassGuid", _GUID),
            ("Flags", wintypes.DWORD),
            ("Reserved", ctypes.c_void_p),
        ]

    class _HIDDAttributes(ctypes.Structure):
        _fields_ = [
            ("Size", wintypes.ULONG),
            ("VendorID", wintypes.USHORT),
            ("ProductID", wintypes.USHORT),
            ("VersionNumber", wintypes.USHORT),
        ]

    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    hid = ctypes.WinDLL("hid", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(_GUID),
        wintypes.LPCWSTR,
        wintypes.HWND,
        wintypes.DWORD,
    ]
    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        ctypes.POINTER(_SPDeviceInterfaceData),
    ]
    setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_SPDeviceInterfaceData),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

    hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(_GUID)]
    hid.HidD_GetHidGuid.restype = None
    hid.HidD_GetAttributes.argtypes = [ctypes.c_void_p, ctypes.POINTER(_HIDDAttributes)]
    hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
    hid.HidD_GetSerialNumberString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_GetSerialNumberString.restype = wintypes.BOOLEAN
    hid.HidD_GetProductString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG]
    hid.HidD_GetProductString.restype = wintypes.BOOLEAN

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = wintypes.BOOL

    DIGCF_PRESENT = 0x00000002
    DIGCF_DEVICEINTERFACE = 0x00000010
    ERROR_NO_MORE_ITEMS = 259
    ERROR_INSUFFICIENT_BUFFER = 122
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    detail_cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6

    hid_guid = _GUID()
    hid.HidD_GetHidGuid(ctypes.byref(hid_guid))
    dev_info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(hid_guid),
        None,
        None,
        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
    )
    if dev_info == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())

    devices = []
    try:
        index = 0
        while True:
            interface_data = _SPDeviceInterfaceData()
            interface_data.cbSize = ctypes.sizeof(_SPDeviceInterfaceData)
            ok = setupapi.SetupDiEnumDeviceInterfaces(
                dev_info,
                None,
                ctypes.byref(hid_guid),
                index,
                ctypes.byref(interface_data),
            )
            if not ok:
                err = ctypes.get_last_error()
                if err == ERROR_NO_MORE_ITEMS:
                    break
                raise ctypes.WinError(err)

            required_size = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info,
                ctypes.byref(interface_data),
                None,
                0,
                ctypes.byref(required_size),
                None,
            )
            err = ctypes.get_last_error()
            if err not in (0, ERROR_INSUFFICIENT_BUFFER):
                raise ctypes.WinError(err)

            path_chars = max(1, required_size.value // ctypes.sizeof(ctypes.c_wchar))

            class _SPDeviceInterfaceDetailDataW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("DevicePath", ctypes.c_wchar * path_chars),
                ]

            detail_data = _SPDeviceInterfaceDetailDataW()
            detail_data.cbSize = detail_cb_size
            ok = setupapi.SetupDiGetDeviceInterfaceDetailW(
                dev_info,
                ctypes.byref(interface_data),
                ctypes.byref(detail_data),
                required_size,
                ctypes.byref(required_size),
                None,
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())

            device_path = detail_data.DevicePath
            handle = kernel32.CreateFileW(
                device_path,
                0,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
            index += 1
            if handle == INVALID_HANDLE_VALUE:
                continue

            try:
                attrs = _HIDDAttributes()
                attrs.Size = ctypes.sizeof(_HIDDAttributes)
                if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                    continue
                if attrs.VendorID != USB_RELAY_HID_VENDOR_ID or attrs.ProductID != USB_RELAY_HID_PRODUCT_ID:
                    continue

                serial_buffer = ctypes.create_unicode_buffer(256)
                product_buffer = ctypes.create_unicode_buffer(256)
                serial_number = ""
                product_string = ""

                if hid.HidD_GetSerialNumberString(
                    handle,
                    serial_buffer,
                    ctypes.sizeof(serial_buffer),
                ):
                    serial_number = serial_buffer.value.strip()

                if hid.HidD_GetProductString(
                    handle,
                    product_buffer,
                    ctypes.sizeof(product_buffer),
                ):
                    product_string = product_buffer.value.strip()

                devices.append(
                    {
                        "serial_number": serial_number,
                        "product_string": product_string,
                        "device_path": device_path,
                        "vendor_id": int(attrs.VendorID),
                        "product_id": int(attrs.ProductID),
                    }
                )
            finally:
                kernel32.CloseHandle(handle)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(dev_info)

    return devices


def _resolve_vendor_cli_target(command_app_path, preferred_serial=None):
    """Use Windows HID enumeration to auto-select a single relay for the vendor CLI."""
    if command_app_path is None:
        return None

    preferred_serial = (preferred_serial or "").strip()
    if preferred_serial:
        return {
            "backend": "vendor_cli",
            "serial_number": preferred_serial,
            "command_app": command_app_path,
        }

    helper_devices = _enumerate_vendor_usb_relays_via_helper()
    print(f"USB relay resolution: vendor helper devices detected = {len(helper_devices)}")
    if helper_devices:
        if len(helper_devices) > 1:
            available_serials = ", ".join(
                f"{(device.get('serial_number') or '').strip() or '<no serial>'}"
                for device in helper_devices
            )
            raise RuntimeError(
                "Multiple HID USB relay devices were detected by the vendor helper. "
                f"Set usbRelaySerialNumber explicitly. Available serial numbers: {available_serials}"
            )

        device = helper_devices[0]
        serial_number = (device.get("serial_number") or "").strip()
        if not serial_number:
            raise RuntimeError(
                "The vendor helper detected one HID relay, but it did not return a usable serial number."
            )

        print(f"USB relay resolution: auto-selected vendor helper serial = {serial_number}")
        return {
            "backend": "vendor_cli",
            "serial_number": serial_number,
            "command_app": command_app_path,
            "device_path": device.get("device_path"),
            "type": device.get("type"),
        }

    hid_devices = _enumerate_windows_hid_relays()
    print(f"USB relay resolution: HID devices detected = {len(hid_devices)}")
    if not hid_devices:
        return None

    if len(hid_devices) > 1:
        available_serials = ", ".join(
            f"{device['serial_number'] or '<no serial>'}"
            for device in hid_devices
        )
        raise RuntimeError(
            "Multiple HID USB relay devices were detected. "
            f"Set usbRelaySerialNumber explicitly. Available serial numbers: {available_serials}"
        )

    device = hid_devices[0]
    serial_number = (device.get("serial_number") or "").strip()
    if not serial_number:
        raise RuntimeError(
            "A HID USB relay device was detected, but it did not expose a serial number string. "
            "Set usbRelaySerialNumber explicitly or use the vendor GUI once to confirm the device serial."
        )

    print(
        "USB relay resolution: auto-selected HID relay "
        f"serial={serial_number} product={device.get('product_string') or USB_RELAY_HID_PRODUCT_LABEL}"
    )
    return {
        "backend": "vendor_cli",
        "serial_number": serial_number,
        "command_app": command_app_path,
        "device_path": device.get("device_path"),
        "product_string": device.get("product_string"),
    }


def _load_vendor_usb_relay_lib():
    """Load the vendor relay DLL on Windows so we can enumerate devices by serial number."""
    global _vendor_usb_relay_lib, _vendor_usb_relay_lib_error

    if _vendor_usb_relay_lib is not None:
        return _vendor_usb_relay_lib

    if _vendor_usb_relay_lib_error is not None:
        return None

    if os.name != 'nt':
        _vendor_usb_relay_lib_error = RuntimeError(
            "Vendor USB relay DLL backend is only available on Windows."
        )
        return None

    try:
        _ensure_vendor_usb_relay_bundle_extracted()
    except Exception as exc:
        _vendor_usb_relay_lib_error = exc
        return None

    last_error = None
    for dll_path in _RELAY_VENDOR_DLL_CANDIDATES:
        if not os.path.isfile(dll_path):
            continue
        try:
            relay_lib = ctypes.WinDLL(dll_path)
            relay_lib.usb_relay_init.restype = ctypes.c_int
            relay_lib.usb_relay_exit.restype = ctypes.c_int
            relay_lib.usb_relay_device_enumerate.restype = _USBRelayDeviceInfoPtr
            relay_lib.usb_relay_device_free_enumerate.argtypes = [_USBRelayDeviceInfoPtr]
            relay_lib.usb_relay_device_open_with_serial_number.argtypes = [
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            relay_lib.usb_relay_device_open_with_serial_number.restype = ctypes.c_int
            relay_lib.usb_relay_device_close.argtypes = [ctypes.c_int]
            relay_lib.usb_relay_device_open_one_relay_channel.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
            ]
            relay_lib.usb_relay_device_open_one_relay_channel.restype = ctypes.c_int
            relay_lib.usb_relay_device_close_one_relay_channel.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
            ]
            relay_lib.usb_relay_device_close_one_relay_channel.restype = ctypes.c_int
            _vendor_usb_relay_lib = relay_lib
            return _vendor_usb_relay_lib
        except Exception as exc:
            last_error = exc

    _vendor_usb_relay_lib_error = RuntimeError(
        "Vendor USB relay DLL could not be loaded from any known location. "
        f"Checked: {_RELAY_VENDOR_DLL_CANDIDATES}. "
        f"Last error: {last_error}"
    )
    return None


def _enumerate_vendor_usb_relays():
    """Enumerate vendor-DLL relay devices. Each device is identified by a relay serial number."""
    relay_lib = _load_vendor_usb_relay_lib()
    if relay_lib is None:
        return []

    init_status = relay_lib.usb_relay_init()
    if init_status != 0:
        raise RuntimeError(
            f"Vendor USB relay DLL initialization failed with status {init_status}."
        )

    devices = []
    head = relay_lib.usb_relay_device_enumerate()
    try:
        current = head
        while current:
            info = current.contents
            serial_bytes = None
            if info.serial_number:
                serial_bytes = ctypes.cast(info.serial_number, ctypes.c_char_p).value
            device_path_bytes = info.device_path

            devices.append(
                {
                    "serial_number": (
                        serial_bytes.decode("utf-8", errors="ignore")
                        if serial_bytes else ""
                    ),
                    "device_path": (
                        device_path_bytes.decode("utf-8", errors="ignore")
                        if device_path_bytes else ""
                    ),
                    "type": int(info.type),
                }
            )
            current = info.next
    finally:
        if head:
            relay_lib.usb_relay_device_free_enumerate(head)
        relay_lib.usb_relay_exit()

    return devices


class VendorUSBRelay:
    """Wrapper around the NOYITO vendor DLL backend."""

    def __init__(self, serial_number):
        self.serial_number = str(serial_number)
        self.relay_lib = _load_vendor_usb_relay_lib()
        self.handle = 0

    def connect(self):
        if self.relay_lib is None:
            raise ConnectionError(
                "Vendor USB relay DLL backend is not available on this machine."
            )

        init_status = self.relay_lib.usb_relay_init()
        if init_status != 0:
            raise ConnectionError(
                f"Vendor USB relay DLL initialization failed with status {init_status}."
            )

        serial_bytes = self.serial_number.encode("utf-8")
        self.handle = self.relay_lib.usb_relay_device_open_with_serial_number(
            serial_bytes,
            len(serial_bytes),
        )
        if self.handle == 0:
            self.relay_lib.usb_relay_exit()
            raise ConnectionError(
                f"Failed to open USB relay with serial number {self.serial_number}."
            )

        time.sleep(RELAY_CONNECT_SETTLE_S)

    def disconnect(self):
        try:
            if self.handle != 0:
                self.relay_lib.usb_relay_device_close(self.handle)
                self.handle = 0
        finally:
            if self.relay_lib is not None:
                self.relay_lib.usb_relay_exit()

    def relay_on(self, relay_num):
        ret = self.relay_lib.usb_relay_device_open_one_relay_channel(self.handle, relay_num)
        if ret != 0:
            raise RuntimeError(
                f"Vendor USB relay open channel failed for relay {relay_num} with status {ret}."
            )

    def relay_off(self, relay_num):
        ret = self.relay_lib.usb_relay_device_close_one_relay_channel(self.handle, relay_num)
        if ret != 0:
            raise RuntimeError(
                f"Vendor USB relay close channel failed for relay {relay_num} with status {ret}."
            )


class VendorUSBRelayCLI:
    """Wrapper around the vendor command-line test app. Requires a known relay serial number."""

    def __init__(self, serial_number, command_app_path):
        self.serial_number = str(serial_number)
        self.command_app_path = command_app_path

    def connect(self):
        if not os.path.isfile(self.command_app_path):
            raise ConnectionError(
                f"Vendor relay command app was not found at {self.command_app_path}."
            )
        time.sleep(RELAY_CONNECT_SETTLE_S)

    def disconnect(self):
        pass

    def _run_command(self, operation, relay_num):
        cmd = [
            self.command_app_path,
            self.serial_number,
            operation,
            f"{int(relay_num):02d}",
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Vendor relay command app failed. "
                f"Command: {cmd}. Return code: {result.returncode}. "
                f"stdout: {result.stdout.strip()} stderr: {result.stderr.strip()}"
            )

    def relay_on(self, relay_num):
        self._run_command("open", relay_num)

    def relay_off(self, relay_num):
        self._run_command("close", relay_num)


class PythonModuleUSBRelayAdapter:
    """Adapter for the lab-tested usbrelay module imported from the NOYITO package."""

    def __init__(self, constructor_args):
        if USBRelay is None:
            raise RuntimeError("USBRelay module is not available.")
        self.constructor_args = tuple(constructor_args)
        self.relay = USBRelay(*self.constructor_args)

    def connect(self):
        self.relay.connect()

    def disconnect(self):
        self.relay.disconnect()

    def relay_on(self, relay_num):
        self.relay.relay_on(relay_num)

    def relay_off(self, relay_num):
        self.relay.relay_off(relay_num)


def _python_module_constructor_candidates():
    candidates = []
    if usbRelayPythonModuleArgument is not None:
        candidates.append((usbRelayPythonModuleArgument,))
    candidates.append(tuple())

    unique_candidates = []
    seen = set()
    for args in candidates:
        if args in seen:
            continue
        seen.add(args)
        unique_candidates.append(args)
    return unique_candidates


def _resolve_python_module_relay_target():
    if USBRelay is None or not usbRelayPreferPythonModule:
        return None

    errors = []
    for constructor_args in _python_module_constructor_candidates():
        try:
            relay = PythonModuleUSBRelayAdapter(constructor_args)
            for required_attr in ("connect", "relay_on", "relay_off", "disconnect"):
                if not hasattr(relay, required_attr):
                    raise RuntimeError(
                        f"USBRelay object is missing required method {required_attr}."
                    )

            return {
                "backend": "python_module",
                "constructor_args": list(constructor_args),
                "description": f"USBRelay{constructor_args}",
            }
        except Exception as exc:
            errors.append(f"USBRelay{constructor_args}: {exc}")

    raise RuntimeError(
        "The lab usbrelay module was found but could not be initialized with any tested constructor. "
        + " | ".join(errors)
    )


def _describe_usb_relay_target(target):
    backend = target["backend"]
    if backend == "python_module":
        return f"lab usbrelay module {target['description']}"
    if backend == "vendor_dll":
        return (
            f"vendor DLL serial={target['serial_number']} "
            f"type={target['type']}"
        )
    if backend == "vendor_cli":
        return f"vendor command app serial={target['serial_number']}"
    return f"serial port {target['port']}"


def resolve_usb_relay_target(preferred_port=None, preferred_serial=None):
    """Resolve the relay backend for the current machine."""
    global _resolved_usb_relay_target, _resolved_usb_relay_target_key

    preferred_serial = (preferred_serial or "").strip()
    cache_key = (
        str(preferred_port).strip().upper() if preferred_port is not None else None,
        preferred_serial,
        bool(usbRelayPreferPythonModule),
        bool(usbRelayAllowSerialFallback),
        usbRelayPythonModuleArgument,
    )
    if (
        _resolved_usb_relay_target is not None
        and _resolved_usb_relay_target_key == cache_key
    ):
        return dict(_resolved_usb_relay_target)

    python_module_error = None
    vendor_cli_error = None

    try:
        _ensure_vendor_usb_relay_bundle_extracted()
    except Exception as exc:
        _vendor_error = exc
    else:
        _vendor_error = _vendor_usb_relay_lib_error

    command_app_path = _find_existing_vendor_command_app()
    try:
        target = _resolve_vendor_cli_target(command_app_path, preferred_serial)
        if target is not None:
            _resolved_usb_relay_target = dict(target)
            _resolved_usb_relay_target_key = cache_key
            print(f"USB relay target: {_describe_usb_relay_target(target)}")
            return dict(target)
    except Exception as exc:
        vendor_cli_error = exc
        if preferred_serial and _vendor_error is not None:
            raise RuntimeError(
                "usbRelaySerialNumber is set, but the vendor relay tools are not usable. "
                f"Vendor tool status: {_vendor_error}"
            ) from exc

    try:
        python_module_target = _resolve_python_module_relay_target()
        if python_module_target is not None:
            _resolved_usb_relay_target = dict(python_module_target)
            _resolved_usb_relay_target_key = cache_key
            print(f"USB relay target: {_describe_usb_relay_target(python_module_target)}")
            return dict(python_module_target)
    except Exception as exc:
        python_module_error = exc

    vendor_devices = _enumerate_vendor_usb_relays()
    if vendor_devices:
        if preferred_serial:
            for device in vendor_devices:
                if device["serial_number"] == preferred_serial:
                    return {
                        "backend": "vendor_dll",
                        "serial_number": device["serial_number"],
                        "device_path": device["device_path"],
                        "type": device["type"],
                    }
            available_serials = ", ".join(
                device["serial_number"] for device in vendor_devices
            )
            raise RuntimeError(
                f"Preferred USB relay serial number {preferred_serial} was not found. "
                f"Available USB relay serial numbers: {available_serials}"
            )

        if len(vendor_devices) == 1:
            device = vendor_devices[0]
            target = {
                "backend": "vendor_dll",
                "serial_number": device["serial_number"],
                "device_path": device["device_path"],
                "type": device["type"],
            }
            _resolved_usb_relay_target = dict(target)
            _resolved_usb_relay_target_key = cache_key
            print(f"USB relay target: {_describe_usb_relay_target(target)}")
            return dict(target)

        available_serials = ", ".join(
            device["serial_number"] for device in vendor_devices
        )
        raise RuntimeError(
            "Multiple USB relay devices were detected through the vendor DLL. "
            f"Set usbRelaySerialNumber explicitly. Available serial numbers: {available_serials}"
        )

    if not usbRelayAllowSerialFallback:
        if vendor_cli_error is not None:
            raise RuntimeError(
                "USB relay HID auto-detection failed before a safe relay target could be selected. "
                f"HID auto-detection status: {vendor_cli_error}"
            )
        if (not usbRelayPreferPythonModule) and (not preferred_serial):
            raise RuntimeError(
                "USB relay is configured for HID control, but no HID relay could be auto-selected. "
                "Connect exactly one VID 16C0 / PID 05DF relay, or set usbRelaySerialNumber explicitly."
            )
        if _vendor_usb_relay_lib_error is not None:
            if command_app_path is not None:
                raise RuntimeError(
                    "USB relay could not be initialized through the lab usbrelay module or the vendor HID DLL backend. "
                    f"Lab usbrelay status: {python_module_error}. "
                    f"Vendor backend status: {_vendor_usb_relay_lib_error}. "
                    "The vendor command-line app is available, so set usbRelaySerialNumber "
                    "to the relay serial shown in GuiApp_English.exe to use the vendor_cli backend."
                )
            raise RuntimeError(
                "USB relay could not be initialized through the lab usbrelay module or the vendor HID backend. "
                f"Lab usbrelay status: {python_module_error}. "
                f"Vendor backend status: {_vendor_usb_relay_lib_error}"
            )
        raise RuntimeError(
            "USB relay could not be initialized through the lab usbrelay module, and the vendor tools detected no HID relay devices. "
            f"Lab usbrelay status: {python_module_error}. "
            "Run GuiApp_English.exe and click 'Find device'. "
            "If one relay is shown, set usbRelaySerialNumber explicitly; "
            "if none are shown, Windows is not exposing the HID relay to the vendor library."
        )

    try:
        relay_port = resolve_usb_relay_port(preferred_port)
        target = {
            "backend": "serial_port",
            "port": relay_port,
        }
        _resolved_usb_relay_target = dict(target)
        _resolved_usb_relay_target_key = cache_key
        print(f"USB relay target: {_describe_usb_relay_target(target)}")
        return dict(target)
    except Exception as serial_exc:
        if _vendor_usb_relay_lib_error is not None:
            raise RuntimeError(
                "USB relay could not be resolved through the vendor USB backend or serial COM backend. "
                f"Vendor backend status: {_vendor_usb_relay_lib_error}. "
                f"Serial backend status: {serial_exc}"
            ) from serial_exc
        raise RuntimeError(
            "USB relay could not be resolved. "
            "Vendor DLL tools loaded but detected no relay devices, and no relay COM port was found. "
            f"Serial backend status: {serial_exc}"
        ) from serial_exc


def resolve_usb_relay_port(preferred_port):
    """Resolve the relay COM port. This path is only for relay boards that enumerate as serial devices."""
    ports = list(serial.tools.list_ports.comports())
    device_map = {
        str(port.device).strip().upper(): str(port.device).strip()
        for port in ports
    }
    preferred_key = str(preferred_port).strip().upper()

    if preferred_key in device_map:
        return device_map[preferred_key]

    candidates = []
    for port in ports:
        description = (port.description or "").lower()
        if "ch340" in description:
            candidates.append(port.device)
            continue
        if getattr(port, 'vid', None) == 0x1A86 and getattr(port, 'pid', None) == 0x7523:
            candidates.append(port.device)

    if candidates:
        resolved = candidates[0]
        print(
            f"USB relay preferred port {preferred_port} not found. "
            f"Using detected CH340 relay port {resolved}."
        )
        return resolved

    port_summary = ", ".join(
        f"{port.device} ({port.description})" for port in ports
    ) or "no serial ports detected"
    raise RuntimeError(
        "USB relay COM port could not be resolved. "
        f"Preferred port {preferred_port} was not present. "
        f"Available ports: {port_summary}"
    )


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
    pumpSer.write(send.encode())  # encodes in hex and sends command to specified pump
    response = pumpSer.readline()  # pump always transmits data back
    return response
    # print(self.response.decode())


def send_n_recieve(cmd):
    send = '{command}\r'.format(command=cmd)  # \r is carriage return
    pumpSer.write(send.encode())  # encodes in hex and sends command to specified pump
    response = pumpSer.readline().decode()  # pump always transmits data back
    # print(response)
    return response


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

    sequenceName.append('Start pump')  # record time of syringe pump starting
    sequenceTime.append(time.time() - timeStart)

    # loops until pumping is stopped, then retracts arm
    # real time query of volume dispensed infused (I) or withdrawn (W) and volume units
    # status can be I, W, S, P, T, U, X
    cmd = '{number}DIS\r'.format(number=sn)
    pumpSer.write(cmd.encode())
    output = pumpSer.readline()  # output.decode() is 00SI0.200W0.000ML
    status = output[3:4].decode()  # Status starts at 3 and stops at 4 (not include)

    while status != 'S':
        pumpSer.write(cmd.encode())
        output = pumpSer.readline()
        status = output[3:4].decode()
        # exits loop when pumping Stops

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

    # loops until pumping is stopped, then retracts arm
    # real time query of volume dispensed infused (I) or withdrawn (W) and volume units
    # status can be I, W, S, P, T, U, X
    cmd = '{number}DIS\r'.format(number=sn)
    pumpSer.write(cmd.encode())
    output = pumpSer.readline()  # output.decode() is 00SI0.200W0.000ML
    status = output[3:4].decode()  # Status starts at 3 and stops at 4 (not include)

    while status != 'S':
        pumpSer.write(cmd.encode())
        output = pumpSer.readline()
        status = output[3:4].decode()
        # exits loop when pumping Stops


# set pump to withdraw (no servo movement)
def withdraw_Only(sn, volume):
    # set direction to withdraw
    directionWDR = '{number} DIR WDR'.format(number=sn)
    sendCMD(directionWDR)

    volC = checkVolUnit(sn, volume)
    volF = checkPumpFloat(volC)
    vol = '{number} VOL {float}'.format(number=sn, float=volF)
    sendCMD(vol)

    run = '{number} RUN'.format(number=sn)
    sendCMD(run)

    cmd = '{number}DIS\r'.format(number=sn)
    pumpSer.write(cmd.encode())
    output = pumpSer.readline()
    status = output[3:4].decode()

    while status != 'S':
        pumpSer.write(cmd.encode())
        output = pumpSer.readline()
        status = output[3:4].decode()


# set pump to infuse(dispense), moves servo arm over substrate, then starts and moves servo out of way when pumping is done
def dispense_n_withdraw(sn, volume, timeStart, delay):
    withdraw_Vol = 90

    # moves pump servo arm over substrate based on which pump is selected
    pumpArm.write(angle[sn])

    sequenceName.append('Servo move')  # record time of servo moving
    sequenceTime.append(time.time() - timeStart)

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
    cmd = '{number}DIS\r'.format(number=sn)
    pumpSer.write(cmd.encode())
    output = pumpSer.readline()  # output.decode() is 00SI0.200W0.000ML
    status = output[3:4].decode()  # Status starts at 3 and stops at 4 (not include)

    while status != 'S':
        pumpSer.write(cmd.encode())
        output = pumpSer.readline()
        status = output[3:4].decode()
        # exits loop when pumping Stops

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

    cmd = '{number}DIS\r'.format(number=sn)
    pumpSer.write(cmd.encode())
    output = pumpSer.readline()  # output.decode() is 00SI0.200W0.000ML
    status = output[3:4].decode()  # Status starts at 3 and stops at 4 (not include)

    while status != 'S':
        pumpSer.write(cmd.encode())
        output = pumpSer.readline()
        status = output[3:4].decode()


# set pump to withdraw material out of vial and then proceeds to dispsenes to aliavate air gap
def prime(sn, volume):
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
    cmd = '{number}DIS\r'.format(number=sn)
    pumpSer.write(cmd.encode())
    output = pumpSer.readline()  # output.decode() is 00SI0.200W0.000ML
    status = output[3:4].decode()  # Status starts at 3 and stops at 4 (not include)

    while status != 'S':
        pumpSer.write(cmd.encode())
        output = pumpSer.readline()
        status = output[3:4].decode()
        # exits loop when pumping Stops

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

    sequenceName.append('Set Spinner to ' + str(target_rpm) + '(' + str(degrees) + ' degree)')
    sequenceTime.append(time.time() - timeStart)  # record time spinner set to specified speed


# function that ramps the spinner speed from its current RPM to the target RPM
def rampSpinner(speed, rampTime, timeStart):
    target_rpm = max(0.0, float(speed))
    ramp_time_s = max(0.0, float(rampTime))

    sequenceName.append('Start spinner function')  # record time spinning starts
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
            if current_rpm > 0:
                stop_ramp_rpm_per_s = max(
                    spinnerDefaultDecelRPMPerS,
                    current_rpm / max(0.1, spinnerTargetStopTimeS),
                )
                _command_spinner_rpm(0.0, stop_ramp_rpm_per_s)
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
    if ledSer is None:
        return
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
    try:
        ledSer.close()
    except Exception:
        pass
    try:
        pumpSer.close()
    except Exception:
        pass
    try:
        arduinoB.exit()
    except Exception:
        pass


# Nitrogen Gas Quenching


def doQuench(sn, timeStart, duration):
    relay_target = resolve_usb_relay_target(usbRelayPort, usbRelaySerialNumber)
    if relay_target["backend"] == "python_module":
        relay = PythonModuleUSBRelayAdapter(relay_target["constructor_args"])
    elif relay_target["backend"] == "vendor_dll":
        relay = VendorUSBRelay(relay_target["serial_number"])
    elif relay_target["backend"] == "vendor_cli":
        relay = VendorUSBRelayCLI(
            relay_target["serial_number"],
            relay_target["command_app"],
        )
    else:
        if USBRelay is None:
            raise RuntimeError(
                "USBRelay module could not be imported. "
                "Check the NOYITO relay driver path before running gas quench."
            )
        relay = USBRelay(relay_target["port"])
    relay.connect()
    relay_1_open = False

    try:
        # Action: move the gas nozzle over the spinning substrate.
        sequenceName.append('Servo move over substrate for gas quenching')
        sequenceTime.append(time.time() - timeStart)
        pumpArm.write(angle[sn])

        # Action: wait for the servo motion to settle before opening the gas valve.
        time.sleep(1)

        # Action: open the gas valve for the requested quench pulse.
        print("Gas Quenching Valve Opened")
        relay.relay_on(1)
        relay_1_open = True
        sequenceName.append('Gas Valve Opened')
        sequenceTime.append(time.time() - timeStart)

        # Action: hold the valve open for the commanded pulse duration.
        time.sleep(max(0.0, float(duration)))

        # Action: close the gas valve at the end of the pulse.
        print("Gas Quenching Valve Closed")
        relay.relay_off(1)
        relay_1_open = False
        sequenceName.append('Gas Valve Closed')
        sequenceTime.append(time.time() - timeStart)

    finally:
        if relay_1_open:
            try:
                print("Gas Quenching Valve Closed (failsafe)")
                relay.relay_off(1)
                sequenceName.append('Gas Valve Closed (failsafe)')
                sequenceTime.append(time.time() - timeStart)
            except Exception:
                pass

        # Action: return the arm to the home position after the pulse.
        pumpArm.write(retract)
        sequenceName.append('Servo moved home')
        sequenceTime.append(time.time() - timeStart)

        try:
            relay.disconnect()
        except Exception:
            pass


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
usbRelayPort = None  # HID configuration does not use a COM-port path.
usbRelayPreferPythonModule = False  # Disable the serial-style usbrelay.py path for the HID relay workflow.
usbRelayPythonModuleArgument = None  # No Python-module constructor argument is used in HID mode.
usbRelaySerialNumber = "QAAMZ"  # Pin the lab relay identity so every run uses the intended device.
usbRelayAllowSerialFallback = False  # Keep COM-port fallback disabled for the HID relay workflow.

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
angle = [63, 73, 58, 63, 78]  # Gas Quench Tube & Perovskite washing = 3rd pump but 4th spot

# angle =  [73, 85, 57, 63] # for angled perovskite arm


retract = 90
over_retract = 95

pumpArm.write(retract)  # 65 top, 130 bottom
# lightArm.write(167)         # 167 is over center of spinner
plLED.write(0)  # ensures PL led is off to start
irLamp.write(0)

## set up serial communication with broadband LED for reflection measurements ##
error = False
ledSer = None
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
