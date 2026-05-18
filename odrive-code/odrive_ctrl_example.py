from odrive_control import ODriveController

ctrl = ODriveController()
ctrl.connect()
ctrl.configure()
ctrl.initialize(test_sequence=True)

# First coat
ctrl.spin_coat(rpm=1500, acceleration=16.67, deceleration=3, spin_time=40)

# Rotate substrate to a new position
ctrl.set_position(0.5)

# Second coat at higher speed
ctrl.spin_coat(rpm=3000, acceleration=25, deceleration=3, spin_time=30)

# Return home
ctrl.set_position(1.0)
