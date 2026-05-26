print('Perovskite Recipe (V9 - Synced with Batch Logic)')

# --- Fully isolated imports for Self-Driving pipeline ---
from . import Dual_Send_Commands as DSC
from . import Dual_Send_OceanFlame as DSO
from . import Dual_Send_Camera as DSCC
from . import Save_Data
from .Wash_Recipe_SD import run_Double_Wash_Perovskite
from .Analysis_SD import analyze_Data
from .Analysis_2.Save_Campaign_Log import save_experiment_log
# ---


import time
import threading
import pandas as pd
import traceback
from datetime import datetime

# --- Configuration copied from Batch version for consistency ---
perovPump = 0
antiPump = 1
dmfPump = 2
gasQuenchSlot = 4

extendedTime = 0
rampTime = 10
antisolventDripEdgeCompensationS = 2.1


# ---


def multi_spin(low_rpm, high_rpm, timeStart, ramp_time):
    tSpin_Low = threading.Thread(target=DSC.setSpinner, args=(low_rpm, timeStart))
    tSpin_High = threading.Thread(target=DSC.setSpinner, args=(high_rpm, timeStart))
    tSpin_Low.start()
    time.sleep(ramp_time)
    tSpin_High.start()


def _format_universal_timestamp(epoch_seconds):
    """Format epoch seconds as M/D/YYYY HH:MM:SS for cross-run event alignment."""
    dt = datetime.fromtimestamp(float(epoch_seconds))
    return f"{dt.month}/{dt.day}/{dt.year} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def run_Perovskite_Recipe(
        timeStart,
        measType,
        perovVol,
        spreadTime,
        rpm,
        runTime,
        dripTime,
        dripVol,
        dripRate,
        fileFolder,
        fileName,
        quenchOrAntisolvent="Antisolvent",
        quenchStart=0,
        quenchDuration=0
):
    """
    Hardened lifecycle:
    - Joins the in-situ thread before save/analysis.
    - try/finally to shut hardware down on errors.
    - Wash starts after analysis/logging completes.
    """
    exp_label = fileName
    tInsitu = None
    tDispense = None
    tPerovPostWithdraw = None
    tAntiPrep = None

    print(f"[{exp_label}] Starting Perovskite Recipe")

    def _log_event(event_name, details=""):
        DSC.log_operation_event(event_name, details=details)

    try:
        _log_event(
            "perovskite_pump_rate_set",
            details=(
                f"pump_number={perovPump}, configured_rate_ml_min={getattr(DSC, 'p1Rate', '')}, "
                f"configured_rate_units={getattr(DSC, 'p1Unit', '')}, source=existing_config"
            ),
        )

        # 1) Set the flow rate for the antisolvent pump (Pump 1)
        DSC.changeFlowRate(antiPump, dripRate, 'MM')

        # 2) Deposit perovskite solution at time 0
        # Pre-prime and post-withdraw to prevent stray droplets while arm moves.
        if int(perovVol) != 0:
            perov_preprime_vol = 25.0   # uL push-forward before dispense
            perov_post_withdraw_vol = 25.0  # uL pull-back after dispense
            perov_preprime_margin = 0.2  # s buffer after pre-prime

            if perov_preprime_vol > 0:
                DSC.dispense_Only(perovPump, perov_preprime_vol)
                time.sleep(perov_preprime_margin)

            tDispense = threading.Thread(target=DSC.dispense, args=(perovPump, perovVol, timeStart, 2))
            _log_event(
                "perovskite_dispense_thread_scheduled",
                details=f"pump_number={perovPump}, requested_volume_ul={perovVol}, retract_delay_s=2",
            )
            tDispense.start()

            if perov_post_withdraw_vol > 0:
                def _perov_post_withdraw(t_dispense):
                    t_dispense.join()
                    DSC.withdraw_Only(perovPump, perov_post_withdraw_vol)

                tPerovPostWithdraw = threading.Thread(
                    target=_perov_post_withdraw,
                    args=(tDispense,),
                    name='PerovPostWithdrawThread',
                )
                tPerovPostWithdraw.start()

        # 2b) Prep antisolvent line early so drip-edge timing only handles servo + RUN.
        # Wait for perovskite dispense to finish first to avoid concurrent pump serial traffic.
        if quenchOrAntisolvent == "Antisolvent" and int(dripVol) != 0:
            anti_prep_vol = 50.0  # 25 uL historical prime + 15 uL moved from late pre-drip path
            anti_prep_details = (
                f"pump_number={antiPump}, prep_volume_ul={anti_prep_vol}, "
                f"requested_drip_time_s={dripTime}, requested_volume_ul={dripVol}, "
                f"requested_rate_ml_min={dripRate}, note=prep_not_commanded_substrate_drip"
            )

            def _prepare_antisolvent(perov_thread, perov_withdraw_thread):
                if perov_thread is not None:
                    perov_thread.join()
                if perov_withdraw_thread is not None:
                    perov_withdraw_thread.join()
                DSC.dispense_Only(antiPump, anti_prep_vol)

            tAntiPrep = threading.Thread(
                target=_prepare_antisolvent,
                args=(tDispense, tPerovPostWithdraw),
            )
            _log_event("antisolvent_prep_thread_scheduled", details=anti_prep_details)
            tAntiPrep.start()

        # 3) Wait spread time for it to spread out
        time.sleep(spreadTime)

        # 4) Spin ramp from 2000 → rpm
        _log_event(
            "spinner_ramp_command_sent",
            details=f"low_rpm=2000, high_rpm={rpm}, ramp_time_s={rampTime}",
        )
        tSpin = threading.Thread(target=multi_spin, args=(2000, rpm, timeStart, rampTime))
        tSpin.start()

        # 5) Start In-Situ measurements (single spectro thread)
        if measType == 1:
            collectStartTime = time.time()
            tInsitu = threading.Thread(target=DSO.run_reflc_InSitu, args=(collectStartTime, runTime))
            tInsitu.start()
            _log_event("in_situ_thread_start", details=f"mode=reflection, run_time_s={runTime}")
            DSC.sequenceName.append('Start Reflection In-Situ')
            DSC.sequenceTime.append(collectStartTime - timeStart)
        elif measType == 2:
            collectStartTime = time.time()
            tInsitu = threading.Thread(target=DSO.run_pl_InSitu, args=(collectStartTime, runTime))
            tInsitu.start()
            _log_event("in_situ_thread_start", details=f"mode=pl, run_time_s={runTime}")
            DSC.sequenceName.append('Start PL In-Situ')
            DSC.sequenceTime.append(collectStartTime - timeStart)
        elif measType == 3:
            collectStartTime = time.time()
            tInsitu = threading.Thread(target=DSO.run_dual_InSitu, args=(collectStartTime, runTime))
            tInsitu.start()
            _log_event("in_situ_thread_start", details=f"mode=dual, run_time_s={runTime}")
            DSC.sequenceName.append('Start Reflection and PL In-Situ')
            DSC.sequenceTime.append(collectStartTime - timeStart)

        # 6) Antisolvent drip (if using antisolv mode)
        # V7-style timing edge: schedule drip using fixed servo compensation near target.
        remainingSpinTime = 0
        if quenchOrAntisolvent == "Antisolvent" and int(dripVol) != 0:
            print(f"[{exp_label}] Antisolvent Drip Running")
            _log_event(
                "requested_antisolvent_drip_time",
                details=(
                    f"requested_drip_time_s={dripTime}, requested_volume_ul={dripVol}, "
                    f"requested_rate_ml_min={dripRate}, mode={quenchOrAntisolvent}"
                ),
            )
            if tAntiPrep is not None:
                _log_event(
                    "antisolvent_prep_join_start",
                    details=(
                        f"pump_number={antiPump}, prep_volume_ul=50.0, requested_drip_time_s={dripTime}, "
                        f"requested_volume_ul={dripVol}, requested_rate_ml_min={dripRate}, "
                        f"note=prep_not_commanded_substrate_drip"
                    ),
                )
                tAntiPrep.join()
                _log_event(
                    "antisolvent_prep_join_end",
                    details=(
                        f"pump_number={antiPump}, prep_volume_ul=50.0, requested_drip_time_s={dripTime}, "
                        f"requested_volume_ul={dripVol}, requested_rate_ml_min={dripRate}, "
                        f"note=prep_not_commanded_substrate_drip"
                    ),
                )
            pre_drip_wait_s = max(0, dripTime - antisolventDripEdgeCompensationS)
            _log_event(
                "antisolvent_pre_drip_wait_start",
                details=(
                    f"requested_drip_time_s={dripTime}, requested_volume_ul={dripVol}, "
                    f"requested_rate_ml_min={dripRate}, "
                    f"drip_edge_compensation_s={antisolventDripEdgeCompensationS:.3f}, "
                    f"computed_pre_drip_wait_s={pre_drip_wait_s:.3f}, "
                    f"wait_duration_s={pre_drip_wait_s:.3f}"
                ),
            )
            time.sleep(pre_drip_wait_s)
            _log_event(
                "antisolvent_pre_drip_wait_end",
                details=(
                    f"requested_drip_time_s={dripTime}, requested_volume_ul={dripVol}, "
                    f"requested_rate_ml_min={dripRate}, "
                    f"drip_edge_compensation_s={antisolventDripEdgeCompensationS:.3f}, "
                    f"computed_pre_drip_wait_s={pre_drip_wait_s:.3f}, "
                    f"wait_duration_s={pre_drip_wait_s:.3f}"
                ),
            )
            tAntiDispense = threading.Thread(target=DSC.dispense, args=(antiPump, dripVol, timeStart, 1))
            _log_event(
                "antisolvent_dispense_thread_scheduled",
                details=(
                    f"pump_number={antiPump}, requested_drip_time_s={dripTime}, "
                    f"requested_volume_ul={dripVol}, requested_rate_ml_min={dripRate}, "
                    f"retract_delay_s=1"
                ),
            )
            tAntiDispense.start()
            _log_event(
                "antisolvent_dispense_thread_start_call_returned",
                details=(
                    f"pump_number={antiPump}, requested_drip_time_s={dripTime}, "
                    f"requested_volume_ul={dripVol}, requested_rate_ml_min={dripRate}, "
                    f"thread_start_call_returned=True, note=logged_after_start_call_to_avoid_pre_start_delay"
                ),
            )
            _log_event(
                "antisolvent_dispense_thread_started",
                details=(
                    f"pump_number={antiPump}, requested_drip_time_s={dripTime}, "
                    f"requested_volume_ul={dripVol}, requested_rate_ml_min={dripRate}, "
                    f"thread_is_alive={tAntiDispense.is_alive()}"
                ),
            )
            remainingSpinTime = dripTime

        # 7) Keep spinning until total runTime is reached
        time.sleep(max(0, runTime - remainingSpinTime))

        # 8) Stop spinner and allow film to dry
        _log_event("spinner_stop_command_sent", details="source=run_Perovskite_Recipe main flow")
        DSC.stopSpinner(timeStart)
        time.sleep(7)

        # 9) Capture film image with lighting off
        print(f"[{exp_label}] Capturing final film image...")
        _log_event("image_capture_start", details=f"file_folder={fileFolder}, file_name={fileName}")
        DSC.turnOff_rflc_led()  # ensure reflection LED is off
        DSC.plOFF()  # ensure PL LED is off
        time.sleep(0.2)  # brief settle
        DSCC.cap_Picture(fileFolder, fileName)
        _log_event("image_capture_end", details=f"file_folder={fileFolder}, file_name={fileName}")

        # 10) Data logging structures
        tags = {'Experiment Name': fileName, 'RPM': rpm, 'Spin Time': runTime,
                'Perovskite Volume': perovVol, 'Anti-Solvent Rate': dripRate,
                'Anti-Solvent Volume': dripVol, 'Anti-Solvent Drip Time': dripTime,
                'Measurement': measType}

        actions = ['Start Time, dispense perovskite', 'start spinner (spread)', 'start insitu', 'antisolvent dispense',
                   'Stop spinner & program', '', 'RPM', 'Spin Time', 'Drip After (s)', 'Pervoskite (uL)',
                   'Antisolvent (uL)',
                   'Pump 1 rate', 'Pump 2 rate']
        values = [0, spreadTime, spreadTime, (dripTime + spreadTime), (runTime + spreadTime), '',
                  rpm, runTime, dripTime, perovVol, dripVol, "N/A", f"{dripRate} MM"]

        action_universal_times = []
        for rel_t in DSC.sequenceTime:
            try:
                action_universal_times.append(_format_universal_timestamp(timeStart + float(rel_t)))
            except Exception:
                action_universal_times.append('')

        dfLog = pd.DataFrame({
            'Actions': pd.Series(DSC.sequenceName),
            'Action Times': pd.Series(DSC.sequenceTime),
            'Action Universal Times': pd.Series(action_universal_times),
            'Inputs': pd.Series(actions),
            'Values': pd.Series(values)
        })
        ddLog = dfLog.to_dict(orient='list')

        # 11) JOIN in-situ thread BEFORE saving / analysis
        if tInsitu is not None:
            print(f"[{exp_label}] Waiting for In-Situ thread to finish...")
            tInsitu.join()
            print(f"[{exp_label}] In-Situ thread finished.")

        # 12) Save data
        print(f"[{exp_label}] Saving Data...")
        Save_Data.save_Data(fileFolder, fileName, measType, dfLog, ddLog, tags)

        # 13) Analyze & compute utility
        print(f"[{exp_label}] Analyzing Data...")
        _log_event("analysis_start", details=f"analysis_target={fileName}")
        analyze_Data(fileFolder, fileName)
        _log_event("analysis_end", details=f"analysis_target={fileName}")

        # 14) Save the final observation for Holmes
        print(f"[{exp_label}] Saving experiment log...")
        save_experiment_log(fileFolder, fileName)

        # 15) Wash cycle (double, blocking)
        print(f"[{exp_label}] Starting double wash cycle...")
        _log_event("wash_start", details="wash_mode=double")
        tWash = threading.Thread(target=run_Double_Wash_Perovskite)
        tWash.start()
        tWash.join()
        _log_event("wash_end", details="wash_mode=double")
        print(f"[{exp_label}] Double wash cycle complete.")
        _log_event("sample_end", details=f"file_name={fileName}")
        print(f"[{exp_label}] Recipe execution finished.")








    except Exception as e:
        print(f"[{exp_label}] ERROR in run_Perovskite_Recipe: {e}")
        _log_event("sample_exception", details=f"error={repr(e)}")
        traceback.print_exc()
        raise








    finally:
        _log_event("finally_shutdown_event", details="entering recipe finally hardware-safe shutdown")
        # Safety net: ensure spinner and LEDs are off, even if something blew up
        try:
            _log_event("spinner_stop_command_sent", details="source=run_Perovskite_Recipe finally block")
            DSC.stopSpinner(timeStart)
        except Exception as e_stop:
            print(f"[{exp_label}] SAFETY: Error stopping spinner in finally: {e_stop}")
            _log_event("finally_shutdown_warning", details=f"spinner_stop_error={repr(e_stop)}")

        try:
            DSC.turnOff_rflc_led()
        except Exception as e_led:
            print(f"[{exp_label}] SAFETY: Error turning off reflection LED: {e_led}")
            _log_event("finally_shutdown_warning", details=f"reflection_led_error={repr(e_led)}")

        try:
            DSC.plOFF()
        except Exception as e_pl:
            print(f"[{exp_label}] SAFETY: Error turning off PL LED: {e_pl}")
            _log_event("finally_shutdown_warning", details=f"pl_led_error={repr(e_pl)}")
