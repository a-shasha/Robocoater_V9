"""
ODrive Motor Control Module
Reconstructed from Node-RED odrive.js library.

Provides connection, configuration, motor control (position/velocity),
spin-coating routines, initialization sequences, and status reporting
for an ODrive motor controller with RS485 AMT21 encoder.
"""

import odrive
from odrive.enums import (
    MotorType, InputMode, ControlMode, AxisState, Protocol,
    Rs485EncoderMode, EncoderId,
)
import time
import json


class ODriveController:
    """High-level ODrive motor controller interface."""

    def __init__(self):
        self.odrv0 = None

    # ── Connection ────────────────────────────────────────────────────

    def connect(self):
        """Find and connect to an ODrive."""
        self.odrv0 = odrive.find_any()
        info = {
            "status": "connected",
            "vbus_voltage": self.odrv0.vbus_voltage,
            "serial_number": (
                hex(self.odrv0.serial_number)
                if hasattr(self.odrv0, "serial_number")
                else "unknown"
            ),
        }
        print(json.dumps(info))
        return info

    # ── Configuration ─────────────────────────────────────────────────

    def configure(
        self,
        dc_bus_overvoltage: float = 26,
        dc_bus_undervoltage: float = 20,
        dc_max_positive_current: float = 10,
        dc_max_negative_current: float = -10,
        torque_constant: float = 0.02506060606060606,
        pole_pairs: int = 7,
        current_soft_max: float = 40,
        current_hard_max: float = 60,
        calibration_current: float = 10,
        resistance_calib_max_voltage: float = 2,
        torque_soft_min: float = -0.2004848484848485,
        torque_soft_max: float = 0.2004848484848485,
        vel_ramp_rate: float = 10,
        vel_gain: float = 0.167,
    ):
        """Apply full ODrive + motor + controller + encoder configuration."""
        odrv0 = self._require_connection()

        # DC bus limits
        odrv0.config.dc_bus_overvoltage_trip_level = dc_bus_overvoltage
        odrv0.config.dc_bus_undervoltage_trip_level = dc_bus_undervoltage
        odrv0.config.dc_max_positive_current = dc_max_positive_current
        odrv0.config.dc_max_negative_current = dc_max_negative_current

        # Motor
        odrv0.axis0.config.motor.motor_type = MotorType.HIGH_CURRENT
        odrv0.axis0.config.motor.torque_constant = torque_constant
        odrv0.axis0.config.motor.pole_pairs = pole_pairs
        odrv0.axis0.config.motor.current_soft_max = current_soft_max
        odrv0.axis0.config.motor.current_hard_max = current_hard_max
        odrv0.axis0.config.motor.calibration_current = calibration_current
        odrv0.axis0.config.motor.resistance_calib_max_voltage = resistance_calib_max_voltage

        # Calibration lockin current
        odrv0.axis0.config.calibration_lockin.current = calibration_current

        # Controller — position control with passthrough
        odrv0.axis0.controller.config.input_mode = InputMode.PASSTHROUGH
        odrv0.axis0.controller.config.control_mode = ControlMode.POSITION_CONTROL
        odrv0.axis0.config.torque_soft_min = torque_soft_min
        odrv0.axis0.config.torque_soft_max = torque_soft_max
        odrv0.axis0.controller.config.vel_ramp_rate = vel_ramp_rate
        odrv0.axis0.controller.config.vel_gain = vel_gain

        # Communication — disable CAN protocol and UART
        odrv0.can.config.protocol = Protocol.NONE
        odrv0.config.enable_uart_a = False

        # RS485 AMT21 encoder
        odrv0.rs485_encoder_group0.config.mode = Rs485EncoderMode.AMT21_EVENT_DRIVEN
        odrv0.axis0.config.load_encoder = EncoderId.RS485_ENCODER0
        odrv0.axis0.config.commutation_encoder = EncoderId.RS485_ENCODER0

        # Save configuration to NVM (ODrive reboots automatically)
        print("Saving configuration...")
        try:
            odrv0.save_configuration()
        except Exception:
            pass  # ODrive reboots on save, connection drops briefly

        # Reconnect after reboot
        print("Reconnecting after reboot...")
        self.odrv0 = odrive.find_any()

        result = {"status": "configured", "vbus_voltage": self.odrv0.vbus_voltage}
        print(json.dumps(result))
        return result

    # ── Initialization ────────────────────────────────────────────────

    def initialize(self, test_sequence: bool = True):
        """
        Enter closed-loop position control and optionally run a
        quarter-turn test sequence (0 → 0.25 → 0.5 → 0.75 → 1 turn).
        """
        odrv0 = self._require_connection()

        odrv0.axis0.controller.config.circular_setpoints = True
        odrv0.axis0.pos_vel_mapper.config.offset_valid = True
        odrv0.axis0.controller.config.input_mode = InputMode.PASSTHROUGH

        odrv0.axis0.requested_state = AxisState.CLOSED_LOOP_CONTROL
        odrv0.axis0.controller.config.control_mode = ControlMode.POSITION_CONTROL
        odrv0.axis0.controller.config.vel_limit = 10

        # Go to initial position
        odrv0.axis0.controller.input_pos = 0
        time.sleep(2)

        if test_sequence:
            for pos in [0.25, 0.5, 0.75, 1.0]:
                odrv0.axis0.controller.input_pos = pos
                time.sleep(2)

        result = {"status": "initialized", "test_sequence": test_sequence}
        print(json.dumps(result))
        return result

    # ── Motor Control ─────────────────────────────────────────────────

    def set_position(self, position: float, vel_limit: float = 10):
        """
        Move to an absolute position (in turns: 0 = 0°, 0.5 = 180°, 1 = 360°).
        Uses circular/absolute setpoints and passthrough input mode.
        """
        odrv0 = self._require_connection()

        # Ensure closed-loop control
        if odrv0.axis0.current_state != AxisState.CLOSED_LOOP_CONTROL:
            odrv0.axis0.requested_state = AxisState.CLOSED_LOOP_CONTROL
            time.sleep(0.5)

        odrv0.axis0.controller.config.control_mode = ControlMode.POSITION_CONTROL
        odrv0.axis0.controller.config.input_mode = InputMode.PASSTHROUGH
        odrv0.axis0.controller.config.absolute_setpoints = True
        odrv0.axis0.controller.config.circular_setpoints = True
        odrv0.axis0.controller.config.vel_limit = vel_limit

        if hasattr(odrv0.axis0, "pos_vel_mapper"):
            odrv0.axis0.pos_vel_mapper.config.offset_valid = True

        odrv0.axis0.controller.input_pos = position
        time.sleep(0.1)

        actual_position = self._get_position()

        result = {
            "status": "success",
            "mode": "position",
            "target_position": position,
            "actual_position": actual_position,
            "axis_state": odrv0.axis0.current_state,
            "control_mode": odrv0.axis0.controller.config.control_mode,
        }
        print(json.dumps(result))
        return result

    def set_velocity(
        self, velocity: float, vel_ramp_rate: float = 16.67, vel_limit: float = 90
    ):
        """
        Set target velocity (turns/s) with configurable ramp rate.
        """
        odrv0 = self._require_connection()

        odrv0.axis0.controller.config.vel_ramp_rate = vel_ramp_rate
        odrv0.axis0.controller.config.control_mode = ControlMode.VELOCITY_CONTROL
        odrv0.axis0.controller.config.input_mode = InputMode.VEL_RAMP
        odrv0.axis0.controller.config.vel_limit = vel_limit

        odrv0.axis0.controller.input_vel = velocity

        # Read back actual velocity
        actual_velocity = 0
        if hasattr(odrv0.axis0, "pos_vel_mapper"):
            actual_velocity = getattr(odrv0.axis0.pos_vel_mapper, "vel", 0)
        elif hasattr(odrv0.axis0, "encoder"):
            actual_velocity = getattr(odrv0.axis0.encoder, "vel_estimate", 0)

        result = {
            "status": "success",
            "mode": "velocity",
            "target_velocity": velocity,
            "actual_velocity": actual_velocity,
        }
        print(json.dumps(result))
        return result

    # ── Spin Coater ───────────────────────────────────────────────────

    def spin_coat(
        self,
        rpm: float = 1500,
        acceleration: float = 16.67,
        deceleration: float = 3,
        spin_time: float = 40,
    ):
        """
        Execute a full spin-coat recipe:
          1. Ramp up to target RPM (vel_ramp_rate = acceleration)
          2. Hold at speed for spin_time seconds
          3. Ramp down to 0 (vel_ramp_rate = deceleration)
          4. Return to position control and go to home (pos = 1)

        Args:
            rpm:          Target motor RPM.
            acceleration: Ramp-up rate in turns/s² (ODrive vel_ramp_rate).
            deceleration: Ramp-down rate in turns/s² (ODrive vel_ramp_rate).
            spin_time:    Seconds at target speed after ramp-up completes.
        """
        odrv0 = self._require_connection()
        target_revs = rpm / 60  # RPM → turns/s

        # ── Ramp up ──
        odrv0.axis0.controller.config.vel_ramp_rate = acceleration
        odrv0.axis0.controller.config.control_mode = ControlMode.VELOCITY_CONTROL
        odrv0.axis0.controller.config.input_mode = InputMode.VEL_RAMP
        odrv0.axis0.controller.config.vel_limit = 90

        odrv0.axis0.controller.input_vel = target_revs

        ramp_up_time = target_revs / acceleration
        time.sleep(ramp_up_time)

        # ── Hold ──
        time.sleep(spin_time)

        # ── Ramp down ──
        odrv0.axis0.controller.config.vel_ramp_rate = deceleration
        odrv0.axis0.controller.input_vel = 0

        ramp_down_time = target_revs / deceleration
        time.sleep(ramp_down_time + 0.5)  # buffer for full stop

        # ── Return to position control ──
        odrv0.axis0.controller.config.control_mode = ControlMode.POSITION_CONTROL
        odrv0.axis0.controller.config.input_mode = InputMode.PASSTHROUGH
        odrv0.axis0.controller.config.absolute_setpoints = True
        odrv0.axis0.controller.config.circular_setpoints = True
        odrv0.axis0.controller.config.vel_limit = 10

        if hasattr(odrv0.axis0, "pos_vel_mapper"):
            odrv0.axis0.pos_vel_mapper.config.offset_valid = True

        if odrv0.axis0.current_state != AxisState.CLOSED_LOOP_CONTROL:
            odrv0.axis0.requested_state = AxisState.CLOSED_LOOP_CONTROL
            time.sleep(0.5)

        odrv0.axis0.controller.input_pos = 1  # home position

        result = {
            "status": "complete",
            "rpm": rpm,
            "acceleration": acceleration,
            "deceleration": deceleration,
            "spin_time": spin_time,
        }
        print(json.dumps(result))
        return result

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self):
        """Read comprehensive status: voltage, position, velocity, current, errors."""
        odrv0 = self._require_connection()

        # Errors
        axis_error = getattr(odrv0.axis0, "error", 0) if hasattr(odrv0, "axis0") else 0
        motor_error = (
            getattr(odrv0.axis0.motor, "error", 0)
            if hasattr(odrv0.axis0, "motor")
            else 0
        )
        controller_error = (
            getattr(odrv0.axis0.controller, "error", 0)
            if hasattr(odrv0.axis0, "controller")
            else 0
        )
        encoder_error = (
            getattr(odrv0.axis0.encoder, "error", 0)
            if hasattr(odrv0.axis0, "encoder")
            else 0
        )

        # Position & velocity
        position = self._get_position()
        velocity = self._get_velocity()

        # Current (Iq)
        current = 0
        try:
            if hasattr(odrv0.axis0, "motor"):
                if hasattr(odrv0.axis0.motor, "foc"):
                    current = odrv0.axis0.motor.foc.Iq_measured
                elif hasattr(odrv0.axis0.motor, "current_control"):
                    current = odrv0.axis0.motor.current_control.Iq_measured
        except Exception:
            pass

        # Control mode
        controller_mode = "unknown"
        try:
            controller_mode = odrv0.axis0.controller.config.control_mode
        except Exception:
            pass

        result = {
            "status": "connected",
            "vbus_voltage": odrv0.vbus_voltage,
            "axis_state": odrv0.axis0.current_state,
            "position": position,
            "velocity": velocity,
            "current": current,
            "controller_mode": controller_mode,
            "errors": {
                "axis": axis_error,
                "motor": motor_error,
                "controller": controller_error,
                "encoder": encoder_error,
            },
        }
        print(json.dumps(result))
        return result

    # ── Helpers ────────────────────────────────────────────────────────

    def _require_connection(self):
        if self.odrv0 is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self.odrv0

    def _get_position(self) -> float:
        odrv0 = self.odrv0
        if hasattr(odrv0.axis0, "pos_vel_mapper"):
            try:
                return odrv0.axis0.pos_vel_mapper.pos_rel
            except Exception:
                pass
        if hasattr(odrv0.axis0, "encoder"):
            try:
                return odrv0.axis0.encoder.pos_estimate
            except Exception:
                pass
        try:
            return odrv0.axis0.controller.input_pos
        except Exception:
            return 0

    def _get_velocity(self) -> float:
        odrv0 = self.odrv0
        if hasattr(odrv0.axis0, "pos_vel_mapper"):
            try:
                return odrv0.axis0.pos_vel_mapper.vel
            except Exception:
                pass
        if hasattr(odrv0.axis0, "encoder"):
            try:
                return odrv0.axis0.encoder.vel_estimate
            except Exception:
                pass
        return 0


# ── CLI usage ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ODrive Motor Control")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("connect", help="Connect to ODrive and print info")
    sub.add_parser("configure", help="Apply default configuration")
    sub.add_parser("status", help="Print status JSON")

    p_init = sub.add_parser("initialize", help="Enter closed-loop and optionally test")
    p_init.add_argument("--no-test", action="store_true", help="Skip test sequence")

    p_pos = sub.add_parser("position", help="Set position (turns)")
    p_pos.add_argument("value", type=float, help="Target position in turns")
    p_pos.add_argument("--vel-limit", type=float, default=10)

    p_vel = sub.add_parser("velocity", help="Set velocity (turns/s)")
    p_vel.add_argument("value", type=float, help="Target velocity in turns/s")
    p_vel.add_argument("--ramp-rate", type=float, default=16.67)

    p_spin = sub.add_parser("spin", help="Run spin-coat recipe")
    p_spin.add_argument("--rpm", type=float, default=1500)
    p_spin.add_argument("--accel", type=float, default=16.67)
    p_spin.add_argument("--decel", type=float, default=16.67)
    p_spin.add_argument("--time", type=float, default=40, dest="spin_time")

    args = parser.parse_args()
    ctrl = ODriveController()

    try:
        if args.command == "connect":
            ctrl.connect()

        elif args.command == "configure":
            ctrl.connect()
            ctrl.configure()

        elif args.command == "status":
            ctrl.connect()
            ctrl.get_status()

        elif args.command == "initialize":
            ctrl.connect()
            ctrl.initialize(test_sequence=not args.no_test)

        elif args.command == "position":
            ctrl.connect()
            ctrl.set_position(args.value, vel_limit=args.vel_limit)

        elif args.command == "velocity":
            ctrl.connect()
            ctrl.set_velocity(args.value, vel_ramp_rate=args.ramp_rate)

        elif args.command == "spin":
            ctrl.connect()
            ctrl.spin_coat(
                rpm=args.rpm,
                acceleration=args.accel,
                deceleration=args.decel,
                spin_time=args.spin_time,
            )

        else:
            parser.print_help()

    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}))
