print('Perovskite Recipe (V9_GQ - Gas Quench Workflow)')

# --- Fully isolated imports for the gas-quench self-driving pipeline ---
from . import Dual_Send_Commands as DSC
from . import Dual_Send_OceanFlame as DSO
from . import Dual_Send_Camera as DSCC
from . import Save_Data
from .Wash_Recipe_SD import run_Double_Wash_Perovskite
from .Analysis_SD import analyze_Data
from .Analysis_2.Save_Campaign_Log import save_experiment_log
# ---

import threading
import time
import traceback

import pandas as pd


# --- Hardware map for the GQ workflow ---
perovPump = 0
gasQuenchSlot = 4

extendedTime = 0
rampTime = 10


def multi_spin(low_rpm, high_rpm, timeStart, ramp_time):
    """Ramp the spinner from the legacy low-RPM staging point to the target RPM."""
    DSC.setSpinner(low_rpm, timeStart)
    DSC.rampSpinner(high_rpm, ramp_time, timeStart)


def run_Perovskite_Recipe(
    timeStart,
    measType,
    perovVol,
    spreadTime,
    rpm,
    runTime,
    gqTime,
    gqDuration,
    fileFolder,
    fileName,
):
    """
    Complete gas-quench experiment lifecycle.

    Timing convention:
    - `gqTime` is measured from the start of spin/in-situ acquisition, matching V9 drip semantics.
    - `runTime` is measured from the same spin/in-situ zero.
    """
    exp_label = fileName
    tInsitu = None
    tDispense = None
    tGasQuench = None
    gas_quench_errors = []

    print(f"[{exp_label}] Starting Gas Quench Recipe")

    try:
        # 0) Resolve the relay port before deposition so a missing relay aborts cleanly.
        if float(gqDuration) > 0:
            DSC.resolve_usb_relay_target(DSC.usbRelayPort, DSC.usbRelaySerialNumber)

        # 1) Deposit the perovskite solution at time zero.
        # Pre-prime and post-withdraw reduce stray droplets as the arm moves.
        if int(perovVol) != 0:
            perov_preprime_vol = 15.0
            perov_post_withdraw_vol = 10.0
            perov_preprime_margin = 0.2

            # Action: push a small amount forward so the dispense starts cleanly.
            if perov_preprime_vol > 0:
                DSC.dispense_Only(perovPump, perov_preprime_vol)
                time.sleep(perov_preprime_margin)

            # Action: perform the full perovskite dispense over the substrate.
            tDispense = threading.Thread(
                target=DSC.dispense,
                args=(perovPump, perovVol, timeStart, 2),
            )
            tDispense.start()

            # Action: pull back slightly after dispense to prevent tail droplets.
            if perov_post_withdraw_vol > 0:
                def _perov_post_withdraw(t_dispense):
                    t_dispense.join()
                    DSC.withdraw_Only(perovPump, perov_post_withdraw_vol)

                threading.Thread(target=_perov_post_withdraw, args=(tDispense,)).start()

        # 2) Hold during the spread stage before spin-up.
        time.sleep(spreadTime)

        # 3) Ramp the spinner from the low-speed start to the target speed.
        tSpin = threading.Thread(target=multi_spin, args=(2000, rpm, timeStart, rampTime))
        tSpin.start()

        # 4) Start the requested in-situ measurement stream.
        if measType == 1:
            collectStartTime = time.time()
            tInsitu = threading.Thread(target=DSO.run_reflc_InSitu, args=(collectStartTime, runTime))
            tInsitu.start()
            DSC.sequenceName.append('Start Reflection In-Situ')
            DSC.sequenceTime.append(collectStartTime - timeStart)
        elif measType == 2:
            collectStartTime = time.time()
            tInsitu = threading.Thread(target=DSO.run_pl_InSitu, args=(collectStartTime, runTime))
            tInsitu.start()
            DSC.sequenceName.append('Start PL In-Situ')
            DSC.sequenceTime.append(collectStartTime - timeStart)
        elif measType == 3:
            collectStartTime = time.time()
            tInsitu = threading.Thread(target=DSO.run_dual_InSitu, args=(collectStartTime, runTime))
            tInsitu.start()
            DSC.sequenceName.append('Start Reflection and PL In-Situ')
            DSC.sequenceTime.append(collectStartTime - timeStart)

        # 5) Schedule the gas quench so the valve opens at the requested GQ time.
        # `doQuench()` includes relay connect plus servo-settle overhead from the relay driver.
        remainingSpinTime = 0
        gas_pretrigger_s = getattr(DSC, 'GAS_QUENCH_PRETRIGGER_S', 3.0)
        if float(gqDuration) > 0:
            print(f"[{exp_label}] Gas Quench Running")
            time.sleep(max(0, gqTime - gas_pretrigger_s))

            def _run_gas_quench():
                try:
                    DSC.doQuench(gasQuenchSlot, timeStart, gqDuration)
                except Exception as exc:
                    gas_quench_errors.append(exc)

            tGasQuench = threading.Thread(
                target=_run_gas_quench,
                name='GasQuenchThread',
            )
            tGasQuench.start()
            remainingSpinTime = gqTime

        # 6) Keep spinning and collecting data until the requested runtime is reached.
        remaining_runtime = max(0, runTime - remainingSpinTime)
        wait_deadline = time.time() + remaining_runtime
        while time.time() < wait_deadline:
            if gas_quench_errors:
                raise RuntimeError(
                    f"Gas quench thread failed: {gas_quench_errors[0]}"
                ) from gas_quench_errors[0]
            time.sleep(min(0.2, wait_deadline - time.time()))

        # 7) Confirm the gas event is fully finished before shutdown steps begin.
        if tGasQuench is not None:
            tGasQuench.join()
        if gas_quench_errors:
            raise RuntimeError(
                f"Gas quench thread failed: {gas_quench_errors[0]}"
            ) from gas_quench_errors[0]

        # 8) Stop the spinner and allow the film to dry before imaging.
        DSC.stopSpinner(timeStart)
        time.sleep(7)

        # 9) Capture the final film image with both light sources forced off.
        print(f"[{exp_label}] Capturing final film image...")
        DSC.turnOff_rflc_led()
        DSC.plOFF()
        time.sleep(0.2)
        DSCC.cap_Picture(fileFolder, fileName)

        # 10) Build the tag block that will travel with the saved raw JSON.
        tags = {
            'Experiment Name': fileName,
            'Process Mode': 'Gas Quench',
            'RPM': rpm,
            'Spin Time': runTime,
            'Perovskite Volume': perovVol,
            'Gas Quench Start Time': gqTime,
            'Gas Quench Duration': gqDuration,
            'Measurement': measType,
        }

        # 11) Build the operator-readable action/value log.
        actions = [
            'Start Time, dispense perovskite',
            'Start spinner after spread stage',
            'Start in-situ measurement',
            'Start gas quench',
            'Stop spinner & program',
            '',
            'RPM',
            'Spin Time',
            'Gas Quench Start After Spread (s)',
            'Gas Quench Duration (s)',
            'Perovskite Volume (uL)',
            'Process Mode',
        ]
        values = [
            0,
            spreadTime,
            spreadTime,
            (gqTime + spreadTime),
            (runTime + spreadTime),
            '',
            rpm,
            runTime,
            gqTime,
            gqDuration,
            perovVol,
            'Gas Quench',
        ]

        dfLog = pd.DataFrame({
            'Actions': pd.Series(DSC.sequenceName),
            'Action Times': pd.Series(DSC.sequenceTime),
            'Inputs': pd.Series(actions),
            'Values': pd.Series(values),
        })
        ddLog = dfLog.to_dict(orient='list')

        # 12) Join the in-situ thread before save/analysis so the data are complete.
        if tInsitu is not None:
            print(f"[{exp_label}] Waiting for In-Situ thread to finish...")
            tInsitu.join()
            print(f"[{exp_label}] In-Situ thread finished.")

        # 13) Save the raw experiment package to disk.
        print(f"[{exp_label}] Saving Data...")
        Save_Data.save_Data(fileFolder, fileName, measType, dfLog, ddLog, tags)

        # 14) Analyze the saved data and generate the report products.
        print(f"[{exp_label}] Analyzing Data...")
        analyze_Data(fileFolder, fileName)

        # 15) Append the final observation to Campaign_Experiments.json for Holmes.
        print(f"[{exp_label}] Saving experiment log...")
        save_experiment_log(fileFolder, fileName)

        # 16) Run the standard double wash so the system is ready for the next sample.
        print(f"[{exp_label}] Starting double wash cycle...")
        tWash = threading.Thread(target=run_Double_Wash_Perovskite)
        tWash.start()
        tWash.join()
        print(f"[{exp_label}] Double wash cycle complete.")
        print(f"[{exp_label}] Recipe execution finished.")

    except Exception as e:
        print(f"[{exp_label}] ERROR in run_Perovskite_Recipe: {e}")
        traceback.print_exc()
        raise

    finally:
        # Safety action: always stop the spinner, even after failures.
        try:
            DSC.stopSpinner(timeStart)
        except Exception as e_stop:
            print(f"[{exp_label}] SAFETY: Error stopping spinner in finally: {e_stop}")

        # Safety action: always force the reflection LED off.
        try:
            DSC.turnOff_rflc_led()
        except Exception as e_led:
            print(f"[{exp_label}] SAFETY: Error turning off reflection LED: {e_led}")

        # Safety action: always force the PL LED off.
        try:
            DSC.plOFF()
        except Exception as e_pl:
            print(f"[{exp_label}] SAFETY: Error turning off PL LED: {e_pl}")
