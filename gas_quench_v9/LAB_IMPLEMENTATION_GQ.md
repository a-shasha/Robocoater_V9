# Self_Driving_V9_GQ Lab Implementation

## Purpose
This folder is a fully separate self-driving workflow for gas quench (GQ).
It does not modify the original antisolvent `Self_Driving_V9` workflow.

## Main files
- `run_campaign.py`: 2D Bayesian optimization campaign for `GQ time` and `GQ duration`.
- `Perovskite_Recipe_SD.py`: full deposition, spin, in-situ, gas-quench, image, save, analyze, wash sequence.
- `Dual_Send_Commands.py`: hardware control, including the NOYITO relay-based gas valve command.
- `Analysis_SD.py`: GQ-aware analysis and analyzed output generation.
- `New_Visual_test.py`: GQ-aware alternate visual report and BO surface visualization.

## Operator edits before lab use
1. Open `run_campaign.py`.
2. Set `file_folder` to the real campaign output folder on the lab PC.
3. Confirm `baseName`, `experiment_budget`, `spreadTime`, `rpm`, `perovVol`, and `timeAfterQuench`.
4. Confirm the BO bounds in `HOLMES_BOUNDS` match the intended safe GQ space.
5. Confirm the warm-start lists `LHS_GQ_TIMES` and `LHS_GQ_DURATION_LEVELS`.

## Hardware checks before first live run
1. Confirm the relay device is on the same port expected by `usbRelayPort` in `Dual_Send_Commands.py`.
2. Confirm the Arduino, syringe pump, and LED ports in `Dual_Send_Commands.py`.
3. Confirm the gas nozzle servo angle in `angle = [63, 73, 58, 63, 80]` still centers the GQ nozzle.
4. Confirm the NOYITO relay driver exists at:
   `Automated-Spin-Coating/In-Situ/Dual/Gas-Quenching/NOYITO-USB-Relay-Module-GUI`

## Recommended rollout sequence
1. Run one dry hardware-only check of the gas valve path with the substrate absent.
2. Run one manual single experiment with conservative GQ settings before launching BO.
3. Check that the raw JSON includes `Gas Quench Start Time` and `Gas Quench Duration`.
4. Check that the analyzed JSON writes `Actual parameters` as `[GQ time, GQ duration]`.
5. Check that `Campaign_Experiments.json` stores 2D actions.
6. After one successful manual run, launch the full campaign.

## Verification already completed in this workspace
- The entire `Self_Driving_V9_GQ` folder compiles successfully with `python3 -m compileall`.
- The relay import path resolves correctly to the local NOYITO driver folder in this workspace.

## Important note
Some copied helper scripts inside `Analysis_2/` remain legacy utilities from the V9 fork.
The active GQ execution path is:
`run_campaign.py -> Perovskite_Recipe_SD.py -> Save_Data.py -> Analysis_SD.py -> Analysis_2/Save_Campaign_Log.py`
