# Antisolvent V9 Architecture

Audit date: 2026-05-18

This document maps the antisolvent workflow as it exists in the baseline. It is a read-only audit of the current code path and does not modify behavior.

## Campaign Entry Point

Primary entry point:

- `antisolvent_v9/run_campaign.py`

The `main()` function runs a 45-experiment campaign with:

- deterministic LHS warm start
- adaptive HOLMES suggestions after the warm start
- periodic best-so-far replicate checks
- a pause every three completed experiments for hardware adjustment
- final hardware shutdown in `finally`

The action space is:

- drip time, bounded by `HOLMES_BOUNDS[0]`
- drip rate, bounded by `HOLMES_BOUNDS[1]`
- drip volume, bounded by `HOLMES_BOUNDS[2]`

HOLMES rows are read from `Campaign_Experiments.json`, normalized into `[0, 1]^3`, and sent to `BASE_URL + "/basic/suggest"`.

## Execution Flow

High-level call flow:

```text
run_campaign.main()
  -> _build_lhs_seed()
  -> run_experiment(params, file_folder, fileName)
    -> constrain_parameters()
    -> DSC.configure_operation_event_logger()
    -> DSC.init_List()
    -> DSO.create_Dataframes()
    -> DSO.reflc_Baseline(rpm, keep_spinner_on=True)
    -> DSO.pl_Baseline(rpm, spinner_already_on=True)
    -> run_Perovskite_Recipe(...)
      -> perovskite dispense
      -> antisolvent prep and timed drip
      -> spinner ramp
      -> in-situ spectroscopy
      -> final camera capture
      -> Save_Data.save_Data()
      -> Analysis_SD.analyze_Data()
      -> Save_Campaign_Log.save_experiment_log()
      -> run_Double_Wash_Perovskite()
  -> shutdown in finally
```

## Recipe Orchestration

Recipe file:

- `antisolvent_v9/Perovskite_Recipe_SD.py`

Primary recipe function:

- `run_Perovskite_Recipe(...)`

The recipe sequence is:

1. Set antisolvent pump flow rate from the campaign action.
2. Pre-prime the perovskite pump.
3. Dispense perovskite over the substrate.
4. Post-withdraw the perovskite line.
5. Pre-prime the antisolvent line.
6. Wait through `spreadTime`.
7. Start spinner ramp from 2000 rpm to target `rpm`.
8. Start reflection, PL, or dual in-situ acquisition based on `measType`.
9. Wait until the compensated drip time.
10. Dispense antisolvent volume.
11. Continue spinning until `runTime`.
12. Stop spinner, dry briefly, turn off light sources.
13. Capture final image.
14. Save raw JSON.
15. Analyze and classify the run.
16. Append campaign observation.
17. Run double wash.

## Pump Control

Pump control is centralized in:

- `antisolvent_v9/Dual_Send_Commands.py`

Primary pump functions used by the recipe:

- `setSyringePump(...)`
- `changeFlowRate(...)`
- `dispense(...)`
- `dispense_Only(...)`
- `withdraw_Only(...)`

The recipe uses pump indexes:

- `perovPump = 0`
- `antiPump = 1`
- `dmfPump = 2` for wash support

The hardware command layer opens the syringe pump serial connection at import time using `syringePort = 'COM7'`.

## Antisolvent Timing

The antisolvent action is controlled by:

- `dripTime`
- `dripRate`
- `dripVol`

`Perovskite_Recipe_SD.py` applies `antisolventDripEdgeCompensationS = 2.1`, then waits `max(0, dripTime - 2.1)` before calling `DSC.dispense(antiPump, dripVol, timeStart, 1)`.

`runTime` is calculated in `run_campaign.py` as `dripTime + timeAfterDrip`, so acquisition and spin duration are tied to the requested drip time.

## Perovskite Dispense

Perovskite dispense is performed before spin-up:

- pre-prime volume: 25.0 uL
- campaign dispense volume: `perovVol`
- post-withdraw volume: 10.0 uL
- servo delay argument to `DSC.dispense(...)`: 2 seconds

The dispense runs in a thread so other post-dispense steps can be coordinated around pump completion.

## Spinner And ODrive Control

Spinner commands flow through:

- `antisolvent_v9/Dual_Send_Commands.py`
- `odrive-code/odrive_control.py` or `odrive-code/odrive-spinner.py`

The antisolvent command layer sets `useODriveSpinner = True`. Spinner functions convert recipe RPM to ODrive turns per second and issue commands through the loaded ODrive backend.

Recipe-level spinner functions:

- `multi_spin(2000, rpm, timeStart, rampTime)`
- `DSC.setSpinner(...)`
- `DSC.rampSpinner(...)`
- `DSC.stopSpinner(...)`

The antisolvent ODrive shutdown path attempts a fixed-angle stop when `spinnerStopAtFixedAngle = True`.

## Spectroscopy Acquisition

Spectroscopy file:

- `antisolvent_v9/Dual_Send_OceanFlame.py`

The module opens the Ocean Insight spectrometer at import time using serial `FLMS19677`.

Campaign run setup:

- `DSO.create_Dataframes()`
- `DSO.reflc_Baseline(rpm, keep_spinner_on=True)`
- `DSO.pl_Baseline(rpm, spinner_already_on=True)`

In-situ acquisition functions:

- `DSO.run_reflc_InSitu(...)`
- `DSO.run_pl_InSitu(...)`
- `DSO.run_dual_InSitu(...)`

Dual acquisition alternates reflection and PL source control while writing measurements into module-level dictionaries that are finalized during save.

## Camera Capture

Camera file:

- `antisolvent_v9/Dual_Send_Camera.py`

The recipe turns off reflection and PL sources, waits briefly, then calls:

- `DSCC.cap_Picture(fileFolder, fileName)`

The resulting image is consumed by film classification during analysis.

## Analysis And Classification

Primary analysis file:

- `antisolvent_v9/Analysis_SD.py`

Film classification file:

- `antisolvent_v9/Analysis_2/Film_Classification_2.py`

The analysis step:

- loads the raw experiment JSON
- writes an analyzed JSON copy
- classifies the final image with a joblib random forest model
- computes utility components
- writes updated analyzed JSON
- updates master JSON files for utility, normalized parameters, observations, time points, and validity

The active classifier artifact appears to be:

- `antisolvent_v9/Analysis_2/randomForest_filmClass_V2.joblib`

The classifier code currently loads the model from a hard-coded old Windows path, despite the model also being present in the repo.

## HOLMES Communication

HOLMES interaction is in:

- `antisolvent_v9/run_campaign.py`

The campaign runner posts normalized training rows to:

- `http://127.0.0.1:5000/holmes/basic/suggest`

Requested policies:

- `{xplt}`
- `{maxvar}`
- `{mcei}`
- `{gpei}`

The adaptive loop alternates exploit and explore cadence with `EXPLORE_EVERY = 3`, using `gpei` for exploit and `maxvar` for exploration.

## JSON And Report Saving

Raw experiment package:

- `antisolvent_v9/Save_Data.py`
- output: `<fileName>.json`

Analyzed experiment package:

- `antisolvent_v9/Analysis_SD.py`
- output: `<fileName>_analyzed.json`

Campaign and master outputs:

- `Campaign_Experiments.json`
- `MasterUtility.json`
- `TimePoints_MasterUtility.json`
- `NormParameters_MasterUtility.json`
- `Observations_MasterUtility.json`
- `Valid_MasterUtility.json`

Generated outputs are campaign artifacts and are intentionally not part of the baseline source tree.

## Wash Cycle Logic

Wash file:

- `antisolvent_v9/Wash_Recipe_SD.py`

The main recipe starts `run_Double_Wash_Perovskite()` after save, analysis, and campaign-log update. Each wash cycle:

- dispenses wash solvent with pump 2
- waits through a soak period
- spins at low RPM
- ramps to high RPM
- holds for drying
- stops the spinner in `finally`

The module configures pump 2 at import time.

## Shutdown And Error Handling

Campaign-level `finally` in `run_campaign.py` calls:

- `DSC.stopSpinner(time.time())`
- `DSC.close_Ser()`
- `DSO.close_spectrometer()`

Recipe-level `finally` in `Perovskite_Recipe_SD.py` attempts:

- stop spinner
- turn off reflection LED
- turn off PL LED

The recipe logs exceptions and re-raises them, so the campaign loop can stop while still entering hardware shutdown.

## Hard-Coded Issues To Stabilize Later

- Campaign output path: `C:\Users\Admin\Desktop\Holmes_Campaign_V9`
- HOLMES endpoint: `http://127.0.0.1:5000/holmes`
- Film-classifier model folder: old `Self_Driving_V9\Analysis_2` path
- Spectrometer serial: `FLMS19677`
- Arduino serial: `COM3`
- Syringe pump serial: `COM7`
- LED serial: `COM4`
- Legacy relay path and `usbRelayPort = "COM5"` are present even though the active antisolvent recipe does not appear to call gas quench
- Calibration output path: `C:\Users\Admin\Desktop\Holmes_Spectroscopy_Calibration`
- Local visualization paths in `New_Visual_test.py`

## Legacy Or Uncertain Items

- `randomForest_filmClass_1.joblib` appears superseded but should be retained until the model history is confirmed.
- `New_Visual_test.py` appears to be visualization/report support rather than the core campaign path.
- `Test_camera.py` is a test utility.
- `Spectroscopy_Calibration.py` is a calibration utility, operationally important but separate from normal campaign execution.
- `Analysis_2/*_video.py` and older analysis modules may be legacy or alternate report paths.
- `preflight_v9.py` and `pump_status_probe_v9.py` are useful safety utilities currently present only in antisolvent.
