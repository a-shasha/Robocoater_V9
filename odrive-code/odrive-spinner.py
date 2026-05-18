# Python functions to control our ODrive spin coater.
# Joseph Schroedl
# June 25th, 2024
# https://github.com/Amassian-Group-NCSU/Automated-Spin-Coating/blob/main/ODrive/odrive-spinner.py

import time

import odrive
from odrive.enums import (
    AxisState,
    ControlMode,
    EncoderId,
    InputMode,
    MotorType,
    Protocol,
    Rs485EncoderMode,
)


def initialize_spinner(run_test_sequence=False):
    """Initialize the ODrive controller and return the connected device object."""
    print("Looking for an ODrive...")
    odrv0 = odrive.find_any()

    odrv0.config.dc_bus_overvoltage_trip_level = 26
    odrv0.config.dc_bus_undervoltage_trip_level = 20
    odrv0.config.dc_max_positive_current = 10
    odrv0.config.dc_max_negative_current = -10

    odrv0.axis0.config.motor.motor_type = MotorType.HIGH_CURRENT
    odrv0.axis0.config.motor.torque_constant = 0.02506060606060606
    odrv0.axis0.config.motor.pole_pairs = 7
    odrv0.axis0.config.motor.current_soft_max = 40
    odrv0.axis0.config.motor.current_hard_max = 60
    odrv0.axis0.config.motor.calibration_current = 10
    odrv0.axis0.config.motor.resistance_calib_max_voltage = 2
    odrv0.axis0.config.calibration_lockin.current = 10

    odrv0.axis0.controller.config.input_mode = InputMode.PASSTHROUGH
    odrv0.axis0.controller.config.control_mode = ControlMode.POSITION_CONTROL
    odrv0.axis0.config.torque_soft_min = -0.2004848484848485
    odrv0.axis0.config.torque_soft_max = 0.2004848484848485
    odrv0.axis0.controller.config.vel_ramp_rate = 10
    odrv0.axis0.controller.config.vel_gain = 0.167

    odrv0.can.config.protocol = Protocol.NONE
    odrv0.config.enable_uart_a = False

    odrv0.rs485_encoder_group0.config.mode = Rs485EncoderMode.AMT21_EVENT_DRIVEN
    odrv0.axis0.config.load_encoder = EncoderId.RS485_ENCODER0
    odrv0.axis0.config.commutation_encoder = EncoderId.RS485_ENCODER0

    print("Bus voltage is " + str(odrv0.vbus_voltage) + "V")

    odrv0.axis0.controller.config.circular_setpoints = True
    odrv0.axis0.pos_vel_mapper.config.offset_valid = True
    odrv0.axis0.controller.config.input_mode = InputMode.PASSTHROUGH
    odrv0.axis0.requested_state = AxisState.CLOSED_LOOP_CONTROL
    odrv0.axis0.controller.config.control_mode = ControlMode.POSITION_CONTROL
    odrv0.axis0.controller.config.vel_limit = 10

    if run_test_sequence:
        for position in (0.0, 0.25, 0.5, 0.75, 1.0):
            odrv0.axis0.controller.input_pos = position
            time.sleep(2)

    print("ODRIVE SETUP DONE")
    return odrv0


def run_spinner(odrv0=None, rps=0, ramp=0, total_spin_time=0):
    """Run the spinner at the requested velocity for the requested duration."""
    odrv0.axis0.controller.config.vel_ramp_rate = ramp
    odrv0.axis0.controller.config.control_mode = ControlMode.VELOCITY_CONTROL
    odrv0.axis0.controller.config.input_mode = InputMode.VEL_RAMP
    odrv0.axis0.controller.config.vel_limit = 90

    odrv0.axis0.controller.input_vel = rps
    time.sleep(total_spin_time)
    odrv0.axis0.controller.input_vel = 0

    time.sleep(2)

    odrv0.axis0.controller.config.circular_setpoints = True
    odrv0.axis0.pos_vel_mapper.config.offset_valid = True
    odrv0.axis0.controller.config.input_mode = InputMode.PASSTHROUGH
    odrv0.axis0.requested_state = AxisState.CLOSED_LOOP_CONTROL
    odrv0.axis0.controller.config.control_mode = ControlMode.POSITION_CONTROL
    odrv0.axis0.controller.config.vel_limit = 10
    odrv0.axis0.controller.input_pos = 1


def stop_spinner(odrv0=None, ramp=0):
    """Stop the spinner by ramping velocity to zero."""
    odrv0.axis0.controller.config.vel_ramp_rate = ramp
    odrv0.axis0.controller.config.control_mode = ControlMode.VELOCITY_CONTROL
    odrv0.axis0.controller.config.input_mode = InputMode.VEL_RAMP
    odrv0.axis0.controller.config.vel_limit = 90

    time.sleep(1)
    odrv0.axis0.controller.input_vel = 0

    time.sleep(1)
    odrv0.axis0.controller.config.vel_limit = 10
