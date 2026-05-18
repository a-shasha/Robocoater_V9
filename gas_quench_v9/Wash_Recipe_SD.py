print('Wash Perovskite Recipe')

# --- Corrected relative import for isolated pipeline ---
from . import Dual_Send_Commands as DSC
# ---

import time
import threading


# This script assumes pump #2 is the wash pump.
WashPump = 2
DSC.setSyringePump(WashPump, 12.45, 12, 'MM')

# Wash cycle settings
SOAK_TIME_S = 25
RAMP_TIME_S = 20
DRY_TIME_S = 45
WASH_VOL_UL = 70
LOW_RPM = 3000
HIGH_RPM = 7000
RAMP_OFFSET_S = 1.7
POST_STOP_PAUSE_S = 5
BETWEEN_CYCLES_PAUSE_S = 2


def run_Wash_Perovskite():
    """Single wash cycle: dispense, stationary soak, spin, ramp, dry, stop."""
    timeStart = time.time()
    print("--- Starting Wash Cycle ---")

    try:
        # Dispense wash solvent while stationary, then soak before spinning.
        tDispense = threading.Thread(
            target=DSC.dispense, args=(WashPump, WASH_VOL_UL, timeStart, 2)
        )
        tDispense.start()
        tDispense.join()
        time.sleep(SOAK_TIME_S)

        # Start low-speed spin after soak, then execute the legacy wash ramp in RPM units.
        DSC.setSpinner(LOW_RPM, timeStart)
        time.sleep(max(0, RAMP_OFFSET_S))
        DSC.rampSpinner(HIGH_RPM, RAMP_TIME_S, timeStart)

        # Hold for drying.
        time.sleep(DRY_TIME_S)

    finally:
        # Always stop spinner so orchestration remains stable on long campaigns.
        tStopSpinner = threading.Thread(target=DSC.stopSpinner, args=(timeStart,))
        tStopSpinner.start()
        tStopSpinner.join()

        time.sleep(POST_STOP_PAUSE_S)
        print("--- Wash Cycle Complete ---")


def run_Double_Wash_Perovskite():
    """
    Run two consecutive wash cycles on the substrate.

    Used by the self-driving pipeline so each fabricated film is followed by
    two full wash cycles.
    """
    print("=== Double Wash: Cycle 1/2 ===")
    run_Wash_Perovskite()

    time.sleep(BETWEEN_CYCLES_PAUSE_S)

    print("=== Double Wash: Cycle 2/2 ===")
    run_Wash_Perovskite()

    print("=== Double Wash complete ===")
