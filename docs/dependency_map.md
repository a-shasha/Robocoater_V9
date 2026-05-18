# Dependency Map

This baseline is a stabilization snapshot. It preserves the current Robocoater V9 operating layout and required hardware support, but it is not yet fully portable because several lab-machine paths and hardware identifiers remain hard-coded.

## ODrive Spinner Support

- Tracked location: `odrive-code/`
- Source used for baseline completion: `Automated-Spin-Coating/In-Situ/Dual/odrive-code/`
- Purpose: Provides ODrive spinner control used by the V9 hardware command layer.
- Dependent workflows:
  - `antisolvent_v9/`
  - `gas_quench_v9/`

Both workflows search for `odrive-code/` relative to their workflow folder and enable the ODrive spinner backend with `useODriveSpinner = True`.

## NOYITO Relay Support

- Tracked location: `Gas-Quenching/NOYITO-USB-Relay-Module-GUI/`
- Source used for baseline completion: `Automated-Spin-Coating/In-Situ/Dual/Gas-Quenching/NOYITO-USB-Relay-Module-GUI/`
- Purpose: Provides NOYITO USB relay support for gas valve control.
- Dependent workflows:
  - `gas_quench_v9/` requires this for gas-quench valve actuation.
  - `antisolvent_v9/` contains legacy gas-quench relay references, but the active antisolvent recipe does not appear to depend on valve actuation.

The duplicate source folder at `Automated-Spin-Coating/Gas-Quenching/NOYITO-USB-Relay-Module-GUI/` was compared against the selected source, excluding `.git/`, `.idea/`, and `__pycache__/`; the support content was identical.

## Documented Hard-Coded Paths And Identifiers

These are documented for baseline awareness and are not fixed in this commit:

- `antisolvent_v9/Analysis_2/Film_Classification_2.py` and `gas_quench_v9/Analysis_2/Film_Classification_2.py` hard-code the model folder to the old `Self_Driving_V9` path on the lab PC.
- `antisolvent_v9/run_campaign.py` hard-codes `C:\Users\Admin\Desktop\Holmes_Campaign_V9`.
- `gas_quench_v9/run_campaign.py` hard-codes `C:\Users\Admin\Desktop\Holmes_Campaign_V9_GQ`.
- Both campaign runners hard-code `BASE_URL = "http://127.0.0.1:5000/holmes"`.
- Both `Spectroscopy_Calibration.py` files hard-code `C:\Users\Admin\Desktop\Holmes_Spectroscopy_Calibration`.
- Both `Dual_Send_Commands.py` files hard-code Arduino, syringe pump, LED, and relay identifiers.
- Both `Dual_Send_OceanFlame.py` files hard-code spectrometer serial `FLMS19677`.
- Both `New_Visual_test.py` files contain local visualization paths under `/Users/alishashaani/Desktop/Courses/NCSU/RC_workspace2/visual output test/`.

## Baseline Interpretation

The baseline commit should capture the current stabilization state and required hardware support without modifying operational Python behavior. Later approved work should replace hard-coded paths with documented configuration and update workflow docs after lab verification.
