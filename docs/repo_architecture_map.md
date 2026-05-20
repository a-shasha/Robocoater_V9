# Robocoater V9 Repository Architecture Map

Audit date: 2026-05-18

This document maps the baseline monorepo as a stabilization snapshot. It describes what is present and how the major workflow folders relate to the hardware support folders. It does not claim the repo is portable yet.

## Top-Level Structure

Tracked baseline structure:

```text
Robocoater_V9/
  README.md
  antisolvent_v9/
  gas_quench_v9/
  odrive-code/
  Gas-Quenching/
    NOYITO-USB-Relay-Module-GUI/
  docs/
  validation/
  training/
  shared_notes/
```

Non-baseline local material still exists in the workspace but is not intended for this repo snapshot, including legacy `Automated-Spin-Coating/`, local HOLMES folders, generated campaign/analysis outputs, notebooks, caches, and local reports.

## Workflow Folders

`antisolvent_v9/` contains the antisolvent V9 self-driving workflow. Its campaign entry point is `run_campaign.py`, which drives a 3D action space:

- antisolvent drip time
- antisolvent drip rate
- antisolvent drip volume

`gas_quench_v9/` contains the gas-quench V9 self-driving workflow. Its campaign entry point is `run_campaign.py`, which drives a 2D action space:

- gas quench start time
- gas quench duration

The two workflow folders are mostly parallel copies with workflow-specific recipe, analysis, and hardware-command differences.

## Shared Dependencies

`odrive-code/` provides spinner control used by both workflows. Both `antisolvent_v9/Dual_Send_Commands.py` and `gas_quench_v9/Dual_Send_Commands.py` search for this folder relative to the workflow directory and enable `useODriveSpinner = True`.

`Gas-Quenching/NOYITO-USB-Relay-Module-GUI/` provides NOYITO relay support. `gas_quench_v9/Dual_Send_Commands.py` actively resolves this dependency for gas valve actuation. `antisolvent_v9/Dual_Send_Commands.py` contains legacy relay references, but the active antisolvent recipe does not appear to require gas valve actuation.

The HOLMES server is not included as a tracked dependency in this baseline. Both campaign runners expect a local endpoint at `http://127.0.0.1:5000/holmes`.

## Operationally Critical Files

Critical antisolvent files:

- `antisolvent_v9/run_campaign.py` - campaign loop, HOLMES requests, run naming, resume behavior.
- `antisolvent_v9/Perovskite_Recipe_SD.py` - deposition recipe, antisolvent timing, spectroscopy/camera/save/analyze/wash sequence.
- `antisolvent_v9/Dual_Send_Commands.py` - pump serial control, Arduino/LED control, ODrive spinner adapter, shutdown helpers.
- `antisolvent_v9/Dual_Send_OceanFlame.py` - spectrometer connection, reflection/PL baselines, in-situ acquisition.
- `antisolvent_v9/Dual_Send_Camera.py` - final image capture.
- `antisolvent_v9/Save_Data.py` - raw experiment JSON package.
- `antisolvent_v9/Analysis_SD.py` - analyzed JSON, utility metrics, summary outputs.
- `antisolvent_v9/Analysis_2/Film_Classification_2.py` - film classifier model loading and image ranking.
- `antisolvent_v9/Analysis_2/randomForest_filmClass_V2.joblib` - active film classifier artifact.
- `antisolvent_v9/Analysis_2/Save_Campaign_Log.py` - campaign observation append for HOLMES training data.
- `antisolvent_v9/Wash_Recipe_SD.py` - post-run double-wash sequence.

Critical gas-quench files:

- `gas_quench_v9/run_campaign.py` - campaign loop, relay preflight, HOLMES requests, run naming, resume behavior.
- `gas_quench_v9/Perovskite_Recipe_SD.py` - deposition recipe, gas-quench scheduling, spectroscopy/camera/save/analyze/wash sequence.
- `gas_quench_v9/Dual_Send_Commands.py` - pump serial control, Arduino/LED control, ODrive spinner adapter, relay resolution and gas valve actuation.
- `gas_quench_v9/Dual_Send_OceanFlame.py` - spectrometer connection, reflection/PL baselines, in-situ acquisition.
- `gas_quench_v9/Dual_Send_Camera.py` - final image capture.
- `gas_quench_v9/Save_Data.py` - raw experiment JSON package.
- `gas_quench_v9/Analysis_SD.py` - analyzed JSON, utility metrics, summary outputs.
- `gas_quench_v9/Analysis_2/Film_Classification_2.py` - film classifier model loading and image ranking.
- `gas_quench_v9/Analysis_2/randomForest_filmClass_V2.joblib` - active film classifier artifact.
- `gas_quench_v9/Analysis_2/Save_Campaign_Log.py` - campaign observation append for HOLMES training data.
- `gas_quench_v9/Wash_Recipe_SD.py` - post-run double-wash sequence.

Critical shared support files:

- `odrive-code/odrive_control.py`
- `odrive-code/odrive-spinner.py`
- `Gas-Quenching/NOYITO-USB-Relay-Module-GUI/usbrelay.py`
- `Gas-Quenching/NOYITO-USB-Relay-Module-GUI/NOYITO-Provided-Documentation-Software-Drivers/USB Relay External Use Development Library.zip`

## Hard-Coded Paths And Device Identifiers

Documented hard-coded output paths:

- `antisolvent_v9/run_campaign.py`: `C:\Users\Admin\Desktop\Holmes_Campaign_V9`
- `gas_quench_v9/run_campaign.py`: `C:\Users\Admin\Desktop\Holmes_Campaign_V9_GQ`
- both `Spectroscopy_Calibration.py` files: `C:\Users\Admin\Desktop\Holmes_Spectroscopy_Calibration`
- both `New_Visual_test.py` files: local `/Users/alishashaani/.../visual output test/` paths

Documented hard-coded model path:

- both `Analysis_2/Film_Classification_2.py` files load the model folder from `C:\Users\Admin\Documents\Automated-Spin-Coating\In-Situ\Dual\Self_Driving_V9\Analysis_2`

Documented hard-coded service endpoint:

- both `run_campaign.py` files use `BASE_URL = "http://127.0.0.1:5000/holmes"`

Documented hard-coded hardware identifiers:

- both `Dual_Send_Commands.py` files use `arduinoPort = 'COM3'`, `syringePort = 'COM7'`, and `ledPort = 'COM4'`
- both `Dual_Send_OceanFlame.py` files use spectrometer serial `FLMS19677`
- `antisolvent_v9/Dual_Send_Commands.py` has `usbRelayPort = "COM5"` for legacy relay code
- `gas_quench_v9/Dual_Send_Commands.py` has `usbRelaySerialNumber = "QAAMZ"` and HID relay settings

These are audit findings only. No path or device identifier was changed during this audit.

## Legacy, Duplicated, Or Uncertain Files

Files or folders that appear useful but need human classification before future cleanup:

- `randomForest_filmClass_1.joblib` in both workflow folders: appears older than `randomForest_filmClass_V2.joblib`.
- `Analysis_2/Analyze_2.py`, `PL_Analysis_2.py`, `PL_Analysis_2_video.py`, `Plot_Data_2.py`, and `UVvis_Analysis_2.py`: retained analysis components that may be legacy support or alternate analysis paths.
- `New_Visual_test.py` in both workflow folders: appears to be visualization/report support, not part of the core campaign path.
- `Test_camera.py` in both workflow folders: operator/test utility, not part of the campaign path.
- `Spectroscopy_Calibration.py` in both workflow folders: calibration utility, operationally important but outside the normal campaign flow.
- `antisolvent_v9/preflight_v9.py` and `antisolvent_v9/pump_status_probe_v9.py`: safety/preflight utilities currently present only in the antisolvent folder.
- `gas_quench_v9/LAB_IMPLEMENTATION_GQ.md`: workflow-specific notes that overlap with the newer repo-level docs.

No files should be deleted or moved based on this audit alone.
