# Post-Move Glovebox Bring-Up Checklist for RoboCoater V9

Post-move RC must not be treated as operation-ready until device identity, COM-port mapping, optical alignment, baselines, camera/crop geometry, and no-chemistry dry-run behavior are validated.

This is a remote-safe, documentation-only checklist. No physical validation was performed while preparing this document.

## Purpose and Scope

This checklist is for RoboCoater V9 bring-up after the physical move into the glovebox.

Scope:

- Applies to Antisolvent Dripping V9 (`antisolvent_v9/`) and Gas Quench V9 (`gas_quench_v9/`).
- Assumes work is being planned remotely, without physical access to RoboCoater or the lab computer.
- Uses the current repository state on `main`, which includes the AD/GQ report-output alignment audit and the GQ report delegation design.
- Treats Antisolvent V9 as the stronger current operational baseline.
- Treats Gas Quench V9 as requiring separate validation before code patching or physical campaign use.

Patch level:

- Level 0: documentation-only cleanup. This document is Level 0.
- Level 1: observability/logging-only code.
- Level 2: behavior-changing or hardware-adjacent code.

The open AD event-trace logging PR should not be merged until no-chemistry dry-run validation is complete, or until explicit logging-only risk acceptance is recorded.

## Current Constraints

The following cannot be performed from home:

- COM-port identification.
- Fiber-probe recalibration.
- Baseline validation.
- Camera/crop validation.
- Pump communication tests.
- Gas relay tests.
- Dry runs.
- Wet runs.

No lab-facing code changes should be made from this checklist alone. Physical evidence must be collected before editing device constants, COM-port values, recipe behavior, pump commands, HOLMES behavior, classifier/model logic, or gas-quench hardware control.

## Reference: Joe's Glovebox Gas-Control Manual

Joe's RoboCoater glovebox gas-control instruction manual should be treated as an operator-readiness input for the physical glovebox environment.

Topics to review before lab bring-up:

- Humodule main glovebox power-on and power-off.
- Main Box nitrogen valve OPEN and CLOSE states.
- Humidity setpoint process.
- Bypass valve use for fast glovebox fill.
- Antechamber transfer workflow and RH% matching.
- Gas-quench passthrough setup.
- Manual solenoid valve test utility for opening and closing the gas valve.
- Gas pressure and flow regulator setup.

These are physical and operator steps. They do not, by themselves, validate Python automation, COM-port mapping, relay targeting, spectrometer signal quality, camera crop geometry, ODrive/spinner behavior, pump identity, or campaign output integrity.

## Remote-Safe Preparation

### A. Files/constants to inspect later for COM ports

Inspect these files on the lab computer before changing anything:

| Workflow | File | Current identity or port constant to verify later |
| --- | --- | --- |
| AD | `antisolvent_v9/Dual_Send_Commands.py` | `arduinoPort = 'COM3'`, `syringePort = 'COM7'`, `ledPort = 'COM4'`, `usbRelayPort = 'COM5'`, `useODriveSpinner = True` |
| GQ | `gas_quench_v9/Dual_Send_Commands.py` | `arduinoPort = 'COM3'`, `syringePort = 'COM7'`, `ledPort = 'COM4'`, `usbRelayPort = None`, `usbRelaySerialNumber = "QAAMZ"`, `usbRelayAllowSerialFallback = False`, `useODriveSpinner = True` |
| AD | `antisolvent_v9/Dual_Send_OceanFlame.py` | `Spectrometer.from_serial_number("FLMS19677")` |
| GQ | `gas_quench_v9/Dual_Send_OceanFlame.py` | `Spectrometer.from_serial_number("FLMS19677")` |
| AD | `antisolvent_v9/Dual_Send_Camera.py` | `cv2.VideoCapture(0)` and crop `top, bottom, left, right = 70, 370, 120, 460` |
| GQ | `gas_quench_v9/Dual_Send_Camera.py` | `cv2.VideoCapture(0)` and crop `top, bottom, left, right = 70, 370, 120, 460` |
| Shared | `odrive-code/odrive_control.py` | ODrive is discovered through `odrive.find_any()` rather than a COM-port constant |
| GQ dependency | `Gas-Quenching/NOYITO-USB-Relay-Module-GUI/` | Manual NOYITO relay tools and Python relay support |

Do not update these values until device identity has been verified and recorded.

### B. Blank COM-port mapping table

Use the table below during lab bring-up.

| Device | Expected role | Old/default COM value if known | New COM value after move | How identity was verified | Test command or evidence | Verified by | Date | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Arduino / Firmata controller | Servo pins, PL LED TTL, IR lamp PWM, auxiliary I/O | `COM3` |  |  |  |  |  |  |
| Perovskite pump | Perovskite dispense syringe pump channel on shared pump serial bus | `COM7` shared pump serial |  |  |  |  |  |  |
| Antisolvent pump | Antisolvent dispense syringe pump channel on shared pump serial bus | `COM7` shared pump serial |  |  |  |  |  |  |
| Wash/DMF pump | Wash/DMF pump channel on shared pump serial bus | `COM7` shared pump serial |  |  |  |  |  |  |
| Reflection LED controller | Broadband reflection LED serial controller | `COM4` |  |  |  |  |  |  |
| Gas relay / NOYITO relay | Gas-quench solenoid relay | AD legacy `COM5`; GQ HID serial `QAAMZ` |  |  |  |  |  |  |
| ODrive / spinner interface if relevant | Spin coater motor control | USB discovery through ODrive backend |  |  |  |  |  |  |
| Ocean Insight spectrometer, if visible by serial rather than COM | PL/reflection spectra | `FLMS19677` |  |  |  |  |  |  |
| Camera index/device | Film image capture for classifier/report | OpenCV camera index `0` |  |  |  |  |  |  |

### C. Device identity verification procedure

1. Start with RoboCoater idle, pumps safe, spinner stopped, LEDs off, and gas valve closed.
2. Record the initial Windows Device Manager view or equivalent device list.
3. Connect or power one device at a time when possible.
4. Record hardware label, USB cable path, hub port, and observed device name.
5. Use safe identity queries only. Do not infer device identity from COM order alone.
6. Record response evidence before changing any repository file or local configuration.
7. If a device cannot be uniquely identified, stop and document the ambiguity.

### D. Fiber-probe recalibration checklist

This is lab-only. Joe noted that the fiber-probe position in the in-situ lens must be recalibrated after the glovebox move.

Checklist:

- Inspect physical probe and lens position after the glovebox move.
- Check probe stability and clearance from spinner, chuck, substrate, pump arms, gas-quench nozzle, and glovebox pass-through constraints.
- Verify the reflection signal with no wet chemistry.
- Verify the dark baseline with illumination off.
- Verify the PL signal path only under a controlled, explicitly safe light-source state.
- Confirm the probe does not drift during spinner idle, arm motion, or expected glovebox manipulation.
- Save representative dark, reflection, and PL spectra as validation evidence.
- Record before/after probe position notes and photos if available.

### E. Reflection/dark/PL baseline validation criteria

Baseline validation should happen before no-chemistry recipe dry runs and before any wet run.

Criteria to record:

- Spectrometer connects to the expected serial number.
- Dark baseline is acquired with sources off and saved.
- Reflection baseline is acquired with the reflection LED state known and saved.
- PL baseline is acquired with the PL excitation state known and saved.
- Signal is not saturated across the analysis wavelength windows.
- Signal is not near-zero when illumination is expected.
- Repeated baseline captures are stable enough for campaign reconstruction.
- The time and file names of baseline captures can be matched to the campaign folder.

### F. Camera/crop geometry checks

The current AD and GQ camera modules use OpenCV camera index `0` and resize a crop to `275 x 275` pixels for classifier/report use.

Checklist:

- Verify the camera device opened by index `0` is the intended RoboCoater camera.
- Capture a no-chemistry image with the glovebox lighting state documented.
- Confirm the substrate/chuck appears in the expected crop.
- Confirm crop boundaries do not cut off the film area after the glovebox move.
- Confirm the resized image still has the expected visual content for classifier/report review.
- Save raw and cropped evidence images if possible.
- Record whether camera focus, glare, glovebox reflections, or lighting changes affect classification readiness.

### G. No-chemistry dry-run checklist

No-chemistry dry runs are required before wet operation after the move.

Checklist:

- Confirm device mapping table is complete enough for a dry run.
- Confirm pumps are physically safe for no-liquid or dummy-liquid state.
- Confirm spinner area is clear.
- Confirm gas valve starts closed and remains safe unless a gas-relay test is explicitly planned.
- Confirm LEDs start off.
- Run AD V9 no-chemistry dry run first, because AD is the stronger baseline.
- Verify recipe prompts, pauses, and operator states are unambiguous.
- Verify event logs, raw JSON, analyzed JSON, report images, campaign logs, and master utility files are produced as expected.
- Confirm no code behavior was changed during the dry-run preparation unless separately approved.
- Do not run GQ physical gas-quench dry runs until relay identity and gas-control readiness are documented.

### H. First controlled wet-validation checklist

Wet validation is out of scope for remote work and should occur only after device identity, optical alignment, baselines, camera/crop geometry, and no-chemistry dry-run behavior pass.

Checklist:

- Confirm operator-readiness review of Joe's glovebox gas-control manual.
- Confirm stop conditions are understood before starting.
- Confirm AD wet validation plan is written before execution.
- Confirm GQ wet validation plan is separate from AD.
- Confirm campaign folder and sample naming are unique and will not overwrite old outputs.
- Confirm external humidity or glovebox sensor records can be aligned to campaign timestamps.
- Start with the smallest controlled validation run that answers the bring-up question.
- Record deviations immediately.

### I. Validation evidence to collect

Collect evidence in a campaign-independent folder or validation note before editing code constants:

- Final COM-port/device mapping table.
- Device Manager or equivalent screenshots.
- Safe query command outputs.
- Spectrometer connection evidence.
- Dark, reflection, and PL baseline files.
- Camera/crop images.
- ODrive/spinner identity and idle/readiness evidence.
- Pump identity and safe communication evidence.
- NOYITO relay identity evidence and closed-state evidence.
- No-chemistry dry-run logs.
- Operation event logs.
- Raw JSON, analyzed JSON, report image, campaign log, and master utility files from dry run.
- Notes on any mismatch from this checklist.

## COM-Port Mapping Table

Use this table as the authoritative bring-up record. Do not treat default values as valid until verified.

| Device | Expected role | Old/default COM value if known | New COM value after move | How identity was verified | Test command or evidence | Verified by | Date | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Arduino / Firmata controller | Servo pins, PL LED TTL, IR lamp PWM, auxiliary I/O | `COM3` |  |  |  |  |  |  |
| Perovskite pump | Pump channel for perovskite dispense | `COM7` shared pump serial |  |  |  |  |  |  |
| Antisolvent pump | Pump channel for antisolvent dispense | `COM7` shared pump serial |  |  |  |  |  |  |
| Wash/DMF pump | Pump channel for wash/DMF dispense | `COM7` shared pump serial |  |  |  |  |  |  |
| Reflection LED controller | Broadband LED for reflection measurements | `COM4` |  |  |  |  |  |  |
| Gas relay / NOYITO relay | Solenoid relay for gas quench | AD legacy `COM5`; GQ HID serial `QAAMZ` |  |  |  |  |  |  |
| ODrive / spinner interface if relevant | Spinner motor control | ODrive USB discovery |  |  |  |  |  |  |
| Ocean Insight spectrometer, if visible by serial rather than COM | Spectroscopy acquisition | `FLMS19677` |  |  |  |  |  |  |
| Camera index/device | Film image capture | OpenCV camera index `0` |  |  |  |  |  |  |

## Device Identity Verification Rules

- Never assign a COM port based on order in Device Manager alone.
- Verify one device at a time when possible.
- Confirm response or identity using safe query commands only.
- Do not run dispense, spin, gas, or light commands during identification unless the lab is prepared and the command is explicitly safe.
- Record evidence before editing code or config.
- If two devices report similar USB adapter names, treat both as ambiguous until safe device-specific evidence is collected.
- If any device identity cannot be verified, stop before dry-run or wet-run work.

## Fiber-Probe Recalibration Checklist, Lab-Only

Joe specifically noted that the fiber-probe position in the in-situ lens must be recalibrated.

Lab-only steps:

- Inspect physical probe/lens position after glovebox move.
- Check probe stability and clearance from spinner/substrate.
- Verify reflection signal.
- Verify dark signal.
- Verify PL signal only when the excitation state is controlled.
- Confirm the probe remains aligned through expected glovebox handling and RoboCoater arm/spinner positions.
- Record representative spectra and any camera photos needed to explain the final alignment.
- Do not proceed to wet validation if signal quality, clearance, or probe stability is uncertain.

## Baseline Validation Checklist, Lab-Only

| Check | Pass/fail | Evidence path | Verified by | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| Spectrometer serial `FLMS19677` connects or documented replacement is confirmed |  |  |  |  |  |
| Dark baseline captured with illumination off |  |  |  |  |  |
| Reflection baseline captured with reflection LED state documented |  |  |  |  |  |
| PL baseline captured with PL LED state documented |  |  |  |  |  |
| Baseline files are saved with unambiguous timestamps |  |  |  |  |  |
| Signals are not saturated in analysis windows |  |  |  |  |  |
| Signals are not near-zero when illumination is expected |  |  |  |  |  |
| External glovebox/humidity sensor timestamps can be aligned |  |  |  |  |  |

## Camera and Crop Geometry Checklist, Lab-Only

| Check | Pass/fail | Evidence path | Verified by | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| Intended camera opens at the documented index |  |  |  |  |  |
| Image capture works with glovebox lighting documented |  |  |  |  |  |
| Crop contains the film/substrate region after the move |  |  |  |  |  |
| Crop does not include dominant glare or obstruction |  |  |  |  |  |
| Final resized image is `275 x 275` pixels |  |  |  |  |  |
| Classifier/report image path resolves in dry-run output |  |  |  |  |  |

## Gas-Quench-Specific Bring-Up Notes

GQ validation must be separate from AD validation.

Before any GQ code patching or physical campaign:

- Verify Joe's gas-control manual has been reviewed for glovebox gas setup.
- Verify the gas-quench passthrough setup.
- Verify gas pressure and flow regulator setup.
- Verify the manual solenoid valve test utility only under prepared lab conditions.
- Verify the Python automation relay target separately from the manual utility.
- Confirm the NOYITO relay starts in a closed/safe state.
- Confirm the relay identity is pinned or documented before use.
- Confirm gas-quench output reports and campaign logs are generated from copied/sample data or no-chemistry runs before wet GQ campaigns.

## No-Chemistry Dry-Run Evidence Checklist

| Evidence | AD V9 | GQ V9 | Evidence path | Notes |
| --- | --- | --- | --- | --- |
| Device mapping table completed |  |  |  |  |
| Operation log created |  |  |  |  |
| Raw JSON created |  |  |  |  |
| Analyzed JSON created |  |  |  |  |
| Report image created |  |  |  |  |
| Campaign log updated |  |  |  |  |
| Master utility file updated as expected |  |  |  |  |
| External sensor timestamps can be aligned |  |  |  |  |
| No unexpected pump dispense occurred |  |  |  |  |
| No unexpected spinner motion occurred |  |  |  |  |
| No unexpected gas valve action occurred |  |  |  |  |
| No unexpected LED state occurred |  |  |  |  |

## Stop Conditions

Stop bring-up work if any of the following occur:

- A device identity is ambiguous.
- A COM-port value is guessed rather than verified.
- The fiber probe is unstable or has unsafe clearance.
- Baseline signals are saturated, near-zero, or inconsistent.
- Camera/crop geometry no longer captures the intended film area.
- Pump communication is ambiguous or affects the wrong pump channel.
- Gas relay identity or closed-state behavior is uncertain.
- ODrive/spinner identity or idle behavior is uncertain.
- Any dry-run output is missing or cannot be matched to timestamps.
- Any wet-run plan depends on unvalidated GQ relay behavior.

## Code Change Gating After Bring-Up

Only after validation evidence exists:

- Level 0 documentation updates may record the verified mapping and evidence.
- Level 1 observability/logging-only patches may be considered when they do not change recipe behavior.
- Level 2 behavior-changing or hardware-adjacent patches require explicit scope, rollback plan, and bench validation.

Do not use this checklist to approve:

- COM-port edits.
- Recipe timing changes.
- Pump volume or rate command changes.
- HOLMES behavior changes.
- Classifier/model changes.
- Gas-quench relay or hardware-control patches.
- Dashboard/UI work.
- Pump edge/drawback protocol implementation.

