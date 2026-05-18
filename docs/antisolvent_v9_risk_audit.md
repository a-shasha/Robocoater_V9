# Antisolvent V9 Risk Audit

Audit date: 2026-05-18

Scope: documentation-only review of `antisolvent_v9/`. No operational code was edited. Findings below describe current baseline behavior and candidate future work only.

## Executive Summary

Top 5 risks:

1. Antisolvent drip timing can drift later than the requested time because the recipe waits for antisolvent prep completion before starting the compensated pre-drip sleep.
2. The actual physical drip edge is inferred from software command/log timing, not directly detected at the nozzle or substrate.
3. Exceptions inside some worker threads, especially the antisolvent dispense thread and in-situ acquisition thread, may not stop the main recipe.
4. JSON writes and campaign-log updates are non-atomic, so interruption or corruption can erase or partially overwrite campaign state.
5. Operator-facing prompts and printed errors can be ambiguous during training; a camera failure can print an error while the recipe still logs image capture end and continues.

## Risk Table

| Risk ID | Category | Description | Severity | File/function | Physical consequence | Data consequence | Recommended next step |
|---|---|---|---|---|---|---|---|
| AS-R001 | Antisolvent timing mismatch | Requested drip time is defined by LHS/HOLMES parameters and clipped in `constrain_parameters()`, then passed as `dripTime` into the recipe. The recipe subtracts a fixed `antisolventDripEdgeCompensationS = 2.1` before scheduling dispense. | High | `antisolvent_v9/run_campaign.py::run_experiment`; `antisolvent_v9/Perovskite_Recipe_SD.py::run_Perovskite_Recipe` | Physical drip may occur later or earlier than the intended film-growth stage. | HOLMES may learn from labels that do not match the actual physical intervention time. | Add a validation-only timing test that compares requested time, command time, pump start, and visual/HC sensor response before changing code. |
| AS-R002 | Antisolvent timing mismatch | The recipe joins `tAntiPrep` before starting the compensated wait. If antisolvent prep overruns or blocks, `pre_drip_wait_s` still runs after prep, shifting the drip late. | High | `Perovskite_Recipe_SD.py::run_Perovskite_Recipe` | Late antisolvent delivery can change nucleation/crystallization window. | Reported `Anti-Solvent Drip Time` remains requested time, not late physical event time. | Later patch should log prep completion versus target time and fail or skip if prep misses the target window. |
| AS-R003 | Antisolvent timing mismatch | Actual pump command is issued in `Dual_Send_Commands.dispense()` after thread scheduling, servo movement, direction command, volume command, and RUN command. Software logs `antisolvent_dispense_thread_scheduled`, `antisolvent_dispense_command_sent`, wait start, and wait end, but not physical droplet exit. | High | `Perovskite_Recipe_SD.py`; `Dual_Send_Commands.py::dispense` | Physical droplet edge can lag software event because of servo travel, serial round trips, tubing compliance, air gaps, and pump response. | Timing reconstruction is command-based rather than physical-event-based. | Use external HC sensor/camera timing to estimate command-to-physical lag per recipe and add a documented offset model only after validation. |
| AS-R004 | Antisolvent timing mismatch | `tAntiDispense` is started but not joined or monitored by the main recipe. Exceptions inside that thread may print but not propagate to the recipe flow. | Critical | `Perovskite_Recipe_SD.py::run_Perovskite_Recipe`; `Dual_Send_Commands.py::dispense` | A failed or timed-out antisolvent dispense may not stop spinner/camera/save/analyze sequence at the right point. | JSON and campaign log can mark the run as completed even if antisolvent dispense failed in a worker thread. | Later patch should capture thread exceptions and join the antisolvent dispense thread before save/analysis or before sample success logging. |
| AS-R005 | Dispense-volume uncertainty | Drip volume and rate come from the campaign action. `changeFlowRate()` sends `RAT`, and `dispense()` sends `DIR INF`, `VOL`, and `RUN`. The code logs requested volume/rate but does not validate every command response. | High | `run_campaign.py::run_experiment`; `Dual_Send_Commands.py::changeFlowRate`; `Dual_Send_Commands.py::dispense` | Pump may accept a stale or malformed setting without immediate detection. | Saved parameters may reflect requested settings rather than confirmed pump state. | Later patch should parse and log command acknowledgements for rate, direction, volume unit, volume, and RUN. |
| AS-R006 | Dispense-volume uncertainty | Syringe diameters and default rates are configured at module import time before the per-sample event logger is configured. Those setup commands are not recorded in `Operation_Event_Log.csv`. | Medium | `Dual_Send_Commands.py::setSyringePump`; module initialization | Wrong syringe diameter can change delivered volume or flow rate calibration. | Per-sample records may not prove which diameter/rate state was active. | Add a preflight/config snapshot document or future event-log row after logger configuration that records active diameter/rate/unit for all pumps. |
| AS-R007 | Dispense-volume uncertainty | Antisolvent prep uses a fixed 50 uL `dispense_Only()` before the timed drip. The prep is intended to reduce late-path delay, but it may alter nozzle wetting, meniscus state, or residual drop state. | Medium | `Perovskite_Recipe_SD.py::run_Perovskite_Recipe`; `Dual_Send_Commands.py::dispense_Only` | Prep can cause residue or a partial droplet that changes the true delivered volume at the substrate. | Pump logs separate prep from requested drip, but physical delivered volume may not equal requested drip volume alone. | Validate prep protocol with mass/visual checks and document whether prep volume reaches waste, nozzle, or substrate-adjacent state. |
| AS-R008 | Dispense-volume uncertainty | Perovskite pre-prime and post-withdraw are intended to control stray droplets. They can affect line pressure and timing for downstream antisolvent prep because antisolvent prep waits for perovskite dispense and withdraw completion. | Medium | `Perovskite_Recipe_SD.py::run_Perovskite_Recipe` | Pressure/line-state interactions may shift fluid behavior or delay antisolvent readiness. | Event log can reconstruct order but not directly measure pressure or meniscus state. | Add operator validation checklist for nozzle state after pre-prime/post-withdraw before glovebox move. |
| AS-R009 | Dispense-volume uncertainty | Pump polling has a 120 s default timeout and attempts `STP` on timeout, so it should not block indefinitely under normal serial-timeout behavior. However, serial write/read exceptions or lock contention still need controlled testing. | Medium | `Dual_Send_Commands.py::_wait_until_pump_stops_locked`; `Dual_Send_Commands.py::_attempt_pump_abort_locked` | Pump may continue or stop unexpectedly if timeout/abort behavior is not verified on the lab hardware. | Timeout event may be logged, but thread exception propagation is incomplete for worker threads. | Bench-test timeout and `STP` behavior with a harmless pump setup and confirm the command actually stops the pump. |
| AS-R010 | Dispense-volume uncertainty | Pump completion can be accepted by status `S` or by parsed volume reaching target while status remains `I` or `W`. This reduces false timeouts but is not an independent delivered-volume measurement. | Medium | `Dual_Send_Commands.py::_wait_until_pump_stops_locked` | A pump counter may indicate target volume even if tubing compliance or blockage changes actual delivered volume. | Logs can overstate certainty of physical delivery. | Treat pump completion logs as command completion, not physical volume proof. Validate with scale/gravimetric or visual tests. |
| AS-R011 | Logging and timestamp quality | `Operation_Event_Log.csv` contains wall-clock timestamps with milliseconds, monotonic time, and elapsed time from sample start. `dfLog` stores sequence elapsed times and second-resolution "universal" times generated from `timeStart + rel_t`. These are different timing systems. | Medium | `Dual_Send_Commands.py::log_operation_event`; `Perovskite_Recipe_SD.py::_format_universal_timestamp` | Operators may compare incompatible timestamps and misread timing offsets. | HC sensor alignment can be off if second-resolution log fields are used instead of event-log milliseconds. | Use `Operation_Event_Log.csv` as the primary cross-system alignment source and document `dfLog` as recipe-relative only. |
| AS-R012 | Logging and timestamp quality | External HC sensor CSV alignment is possible through wall-clock nearest-neighbor matching, but only if the PC clock and HC sensor clock are synchronized and stable. | Medium | `Operation_Event_Log.csv`; `antisolvent_v9/Operation_Event_Log_Guide.md` | Physical event interpretation can be wrong if clocks drift or time zones differ. | Reconstructed event-to-HC mapping can be mismatched. | Before glovebox move, run a shared clock/trigger alignment test and define an accepted tolerance, e.g. 0.5 to 1.0 s. |
| AS-R013 | Logging and timestamp quality | Some critical command responses are not logged, including raw pump responses for `DIA`, `VOL UL`, `RAT`, `DIR`, `VOL`, and `RUN`. | Medium | `Dual_Send_Commands.py::sendCMD`; `setSyringePump`; `changeFlowRate`; `dispense` | Hardware may silently reject or alter a command. | Event log may show requested commands without hardware acknowledgement evidence. | Later patch should add structured command/response logging with redaction only if needed. |
| AS-R014 | Logging and timestamp quality | `image_capture_end` is logged after `cap_Picture()` returns, even though camera failure only prints and returns. | High | `Perovskite_Recipe_SD.py::run_Perovskite_Recipe`; `Dual_Send_Camera.py::cap_Picture` | Operator may think imaging succeeded after camera failure. | Classifier may assign fallback/error film ranking or use missing image behavior while campaign continues. | Later patch should make camera capture return success/failure and log that status; optionally fail sample on missing image. |
| AS-R015 | Robustness and failure handling | `sendCMD()` returns the pump response but does not validate it or retry. Serial communication errors in main-thread pump commands can raise and enter recipe shutdown, but malformed responses can pass until later polling. | High | `Dual_Send_Commands.py::sendCMD`; pump command functions | Pump may not execute intended direction/rate/volume. | Saved parameters may not represent actual pump state. | Later patch should centralize pump command execution with expected response parsing and retry/fail policy. |
| AS-R016 | Robustness and failure handling | Spectrometer initialization catches connection failure and sets `device = None`; later `create_Dataframes()` calls `get_Wavelengths()` and will fail if no device exists. Acquisition thread exceptions are not captured and propagated. | High | `Dual_Send_OceanFlame.py` initialization; `create_Dataframes`; `run_dual_InSitu` | Run may abort before recipe or continue with incomplete in-situ data if a thread fails mid-run. | JSON can be missing spectra or use partial data, affecting utility and resume decisions. | Later patch should hard-fail preflight if `device is None` and capture in-situ thread exceptions before save/analysis. |
| AS-R017 | Robustness and failure handling | `analyze_Data()` catches all exceptions and prints a traceback but does not raise. The recipe then continues to save campaign log, which may fall back to raw JSON or film score. | High | `Analysis_SD.py::analyze_Data`; `Save_Campaign_Log.py::save_experiment_log` | Bad analysis does not stop physical campaign progression. | HOLMES may receive fallback or incomplete observations. | Later patch should return explicit analysis status and prevent adaptive learning from invalid or fallback observations unless approved. |
| AS-R018 | Robustness and failure handling | Recipe `finally` stops spinner and turns off LEDs. Campaign `finally` also stops spinner, closes LED serial, and closes spectrometer. However, antisolvent `close_Ser()` does not close `pumpSer` because the pump close is commented out. | Medium | `Perovskite_Recipe_SD.py::finally`; `run_campaign.py::finally`; `Dual_Send_Commands.py::close_Ser` | Pump serial connection may remain open after a stop or exception. | Restart behavior may be confusing if the pump serial port is still held. | Later patch should define and validate complete shutdown semantics for pump, Arduino, LED, spinner, and spectrometer. |
| AS-R019 | Robustness and failure handling | There is a pump timeout `STP` path, but no general pump abort in recipe `finally` for non-timeout exceptions or operator stop conditions. | High | `Dual_Send_Commands.py::_attempt_pump_abort_locked`; `Perovskite_Recipe_SD.py::finally` | A pump command running in a worker thread could continue after main flow has entered cleanup. | Logs may show sample exception without confirmed pump stop. | Later patch should add a safe, idempotent all-pump stop/abort routine and call it during critical shutdown paths after lab validation. |
| AS-R020 | JSON/data integrity | Raw JSON, analyzed JSON, master JSONs, and campaign logs are written directly with `open(..., 'w')` and `json.dump()`, not via temp-file plus atomic replace. | High | `Save_Data.py::save_Data`; `Analysis_SD.py::_update_json_file`; `Save_Campaign_Log.py::save_experiment_log` | None directly, but campaign may continue based on damaged state after restart. | Power loss/interruption can leave partial/truncated JSON. | Later patch should write to `*.tmp`, flush/fsync, then atomic replace. |
| AS-R021 | JSON/data integrity | If `Campaign_Experiments.json` cannot be read, `_read_campaign_dict()` returns `{}` and `save_experiment_log()` also starts from `{}`. This can mask corruption and overwrite campaign history. | High | `run_campaign.py::_read_campaign_dict`; `Save_Campaign_Log.py::save_experiment_log` | Campaign may repeat old actions or lose progression context. | HOLMES training set can be reset or corrupted silently. | Later patch should quarantine unreadable campaign logs and require human decision instead of continuing from empty state. |
| AS-R022 | JSON/data integrity | Existing output names can be overwritten if resume count is wrong, the campaign log is reset, or a run is repeated with the same `fileName`. Classifier also removes existing classified image destination before rename. | Medium | `run_campaign.py::main`; `Analysis_2/Film_Classification_2.py::classify_Film` | Physical run evidence can be disconnected from prior outputs. | Old raw/analyzed JSON or image outputs can be lost. | Later patch should refuse to run if target output files already exist unless operator explicitly selects a recovery mode. |
| AS-R023 | Operator workflow and Kathy training | Manual pause occurs every three completed runs with a generic `Press Enter to continue` prompt. It does not show a required checklist or current hardware state. | Medium | `run_campaign.py::_pause_if_needed`; `training/operator_checklist.md` | Operator may resume after an unresolved issue. | Campaign metadata does not record what was checked during the pause. | Add a training checklist that Kathy must complete verbally or in notes before pressing Enter. |
| AS-R024 | Operator workflow and Kathy training | Printed errors can be easy to miss during long runs. Camera failures and analysis exceptions may print but not stop campaign progression. | High | `Dual_Send_Camera.py::cap_Picture`; `Analysis_SD.py::analyze_Data` | Operator may leave the system running after required data capture failed. | Bad/missing image or invalid analysis can still enter campaign artifacts. | Train Kathy that any camera, analysis, spectrometer, or pump warning is a stop-and-preserve event until reviewed. |
| AS-R025 | Operator workflow and Kathy training | The distinction between requested drip time, software command time, and physical drip time is subtle. | High | `run_campaign.py`; `Perovskite_Recipe_SD.py`; `Dual_Send_Commands.py` | Operator may incorrectly evaluate whether a run was on time. | HC correlation and campaign notes can be mislabeled. | Training should include a timing reconstruction exercise using `Operation_Event_Log.csv` and HC sensor CSV. |

## Timing Trace For Antisolvent Drip

Requested drip time is defined in:

- LHS seed arrays and HOLMES suggestions in `antisolvent_v9/run_campaign.py`.
- `constrain_parameters()` clips the requested time/rate/volume.
- `run_experiment()` assigns `dripTime, dripRate, dripVol` and configures the event logger.

Compensated drip time is calculated in:

- `antisolvent_v9/Perovskite_Recipe_SD.py`
- constant: `antisolventDripEdgeCompensationS = 2.1`
- expression: `pre_drip_wait_s = max(0, dripTime - antisolventDripEdgeCompensationS)`

Actual pump command is issued in:

- `Perovskite_Recipe_SD.py`, where `tAntiDispense` starts `DSC.dispense(antiPump, dripVol, timeStart, 1)`.
- `Dual_Send_Commands.py::dispense()`, where the code sends direction, volume unit, volume, and `RUN`.

Logged events include:

- `requested_antisolvent_drip_time`
- `antisolvent_pre_drip_wait_start`
- `antisolvent_pre_drip_wait_end`
- `antisolvent_dispense_thread_scheduled`
- `antisolvent_dispense_command_sent`
- `antisolvent_dispense_wait_start`
- `antisolvent_dispense_wait_end`

Important limitation: these are software events. They do not directly measure fluid leaving the nozzle, droplet impact on the substrate, or the exact physical end of the drip.

Software delay can shift the physical event through:

- late completion of antisolvent prep before the pre-drip sleep starts
- Python thread scheduling latency after `tAntiDispense.start()`
- pump serial command round trips
- pump command lock contention
- servo movement before the `RUN` command path
- tubing compliance, air bubbles, or meniscus state
- pump response behavior at low rates or high volumes

## Dispense-Volume Audit Notes

Drip volume, rate, syringe diameter, and pump commands are set as follows:

- `run_campaign.py` supplies `dripVol` and `dripRate`.
- `Perovskite_Recipe_SD.py` calls `DSC.changeFlowRate(antiPump, dripRate, 'MM')`.
- `Dual_Send_Commands.py` sets pump diameters during module initialization with `setSyringePump()`.
- `Dual_Send_Commands.py::dispense()` sends `DIR INF`, `VOL`, and `RUN`.
- `checkVolUnit()` switches between `UL` and `ML` for command formatting.

Current logging records:

- requested rate in `antisolvent_pump_rate_set`
- requested volume and `RUN` command in `antisolvent_dispense_command_sent`
- wait start/end and parsed final pump response in `antisolvent_dispense_wait_end`

Current logging does not fully record:

- raw responses for all setup commands
- per-sample syringe diameter confirmation
- full sequence of `DIR`, `VOL UL`/`VOL ML`, `VOL`, and `RUN` acknowledgements
- physical delivered volume independent of pump counters

Pump polling should not block indefinitely under normal conditions because `_wait_until_pump_stops_locked()` has `pumpWaitTimeoutS`, defaulting to 120 s, and attempts `STP` on timeout. The remaining risk is that worker-thread failures may not propagate and that `STP` behavior still needs hardware validation.

## Logging And Timestamp Quality

Three timestamp families exist:

- Wall-clock timestamps in `Operation_Event_Log.csv`: useful for alignment with external HC sensor CSVs when clocks are synchronized.
- Monotonic elapsed timestamps in `Operation_Event_Log.csv`: preferred for within-sample timing calculations.
- Recipe-relative `sequenceTime` values in raw JSON `Log`: useful for internal sequence reconstruction, but lower-confidence for cross-system alignment.

`Action Universal Times` in the raw JSON are generated from `timeStart + sequenceTime` and formatted only to seconds. They should not be used for sub-second HC alignment.

Missing or weak event logs for reconstruction:

- raw pump command responses for setup and action commands
- explicit antisolvent prep completion versus target drip time
- camera capture success/failure status
- in-situ thread success/failure status
- spectrometer acquisition start/end per mode with exception state
- all-pump stopped/aborted confirmation during shutdown
- operator pause checklist completion and operator initials

## Robustness And Failure Handling

Pump serial command failure:

- Import-time serial open failure would likely prevent campaign startup.
- Runtime serial exceptions in main-thread commands should raise into recipe exception handling.
- Malformed but non-exception responses are not consistently validated.
- Timeout during pump polling raises `PumpTimeoutError` after attempting `STP`.
- Exceptions inside `tAntiDispense` are not propagated to the main recipe.

Pump polling never returns:

- The polling loop has a default 120 s timeout and uses serial timeout behavior.
- On timeout, it logs a timeout event and attempts pump stop with `STP`.
- The abort behavior still needs hardware validation, especially inside worker threads.

Spectrometer failure:

- Initial connection failure sets `device = None`.
- Later setup can fail when wavelengths/intensities are requested.
- In-situ acquisition thread failures are not explicitly captured by the main recipe.

Camera failure:

- `cap_Picture()` retries once, prints an error, and returns if no frame is captured.
- The recipe still logs `image_capture_end` after return.
- Classification may then handle missing image as an error/fallback rather than stopping the sample.

Recipe exceptions:

- `run_Perovskite_Recipe()` logs `sample_exception`, prints traceback, and re-raises.
- Recipe `finally` attempts spinner stop and turns off reflection and PL LEDs.
- Campaign `finally` attempts spinner stop, LED serial close, and spectrometer close.
- Pump serial close is not active in `close_Ser()`.
- No general all-pump stop is called from recipe `finally`.

## JSON And Data Integrity

JSON writes are not atomic:

- raw JSON in `Save_Data.py`
- analyzed JSON and master JSONs in `Analysis_SD.py`
- `Campaign_Experiments.json` in `Save_Campaign_Log.py`

Campaign log corruption risks:

- read failures are treated as empty dictionaries in multiple places
- a corrupted campaign log can make resume count appear as zero
- writing after a read failure can overwrite prior campaign history

Resume risks:

- resume count is based on `len(Campaign_Experiments.json)`
- missing or corrupt entries can cause repeated file names
- repeated file names can overwrite raw/analyzed outputs

Old output overwrite risks:

- raw/analyzed JSON use direct target file names
- master JSON entries are replaced by key
- classified image destination is removed if it already exists

## First Safe Patches To Consider Later

Do not implement these in this audit branch without explicit approval:

1. Add thread result wrappers for `tAntiDispense`, `tInsitu`, and other worker threads so exceptions propagate to the recipe.
2. Add an explicit antisolvent dispense join before save/analysis and before declaring `sample_end`.
3. Make camera capture return a boolean or raise on failure, then log `image_capture_success=false` and mark the sample invalid.
4. Add atomic JSON write helpers using temp files and `os.replace()`.
5. Change campaign-log read failure from "empty campaign" to "quarantine and stop for human decision."
6. Add structured pump command/response logging for `DIA`, `RAT`, `DIR`, `VOL`, `RUN`, `DIS`, and `STP`.
7. Add a per-sample hardware configuration snapshot after logger setup.
8. Add an all-pump stop/abort routine for shutdown paths, only after validating commands on hardware.
9. Add target-window enforcement for antisolvent prep: if prep completes too late, stop or mark sample invalid before drip.
10. Add output-file collision checks before running a sample.

## Validation Tests Required Before Glovebox Move

1. Dry-run event log validation: run without chemistry and confirm all expected `Operation_Event_Log.csv` rows appear in order.
2. Antisolvent timing validation: compare requested drip time, dispense command time, pump wait start/end, and HC sensor response across low, medium, and high rates.
3. Thread failure validation: simulate pump timeout and in-situ acquisition failure and verify the main recipe stops or marks invalid after future patches.
4. Pump command validation: confirm `RAT`, `VOL`, `RUN`, `DIS`, and `STP` responses on each pump with harmless fluid or dry-safe setup.
5. Volume validation: measure dispensed antisolvent volume across the full HOLMES volume/rate range, including 50 uL at 15 mL/min and 500 uL at 0.8 mL/min.
6. Prep protocol validation: confirm the 50 uL antisolvent prep does not create an unintended droplet or shift the physical drip edge.
7. Camera failure validation: unplug/block camera and confirm the operator-visible stop procedure catches failure.
8. Spectrometer failure validation: disconnect spectrometer and confirm startup/preflight stops before chemistry.
9. JSON interruption validation: interrupt during raw JSON, analyzed JSON, and campaign-log writes in a copy of campaign data and verify recovery plan.
10. Resume validation: start, stop, and resume a mock campaign with existing outputs and verify no file is overwritten.
11. HC alignment validation: synchronize clocks, generate a known event, and verify nearest-neighbor matching tolerance.
12. Operator pause validation: rehearse every-three-run pause with checklist completion and explicit continue/stop decision.

## Kathy Training Implications

Kathy should be trained to distinguish:

- requested drip time: the action chosen by LHS/HOLMES
- software command time: when the pump `RUN` command was issued
- physical drip time: when fluid actually leaves the nozzle and interacts with the film

Kathy should not treat these as equivalent until validation data prove the offset is stable.

Training should emphasize:

- Do not press Enter at the pause prompt until the checklist is complete.
- Any pump timeout, camera error, spectrometer error, analysis traceback, or missing event-log row is a stop condition.
- `image_capture_end` in the current code does not guarantee a valid image.
- A printed Python thread exception can matter even if the main campaign keeps running.
- `Campaign_Experiments.json` should not be hand-edited during a campaign.
- Preserve the entire campaign folder, `Operation_Event_Log.csv`, raw/analyzed JSON, images, and operator notes after any stop.
- Use `Operation_Event_Log.csv` for timing reconstruction, not the lower-resolution `Action Universal Times`.
- If a run is stopped or uncertain, do not restart by reusing the same output folder without a recovery decision.

Recommended training exercise:

1. Take one completed dry-run sample.
2. Locate `sample_start`, `antisolvent_dispense_thread_scheduled`, `antisolvent_dispense_command_sent`, `antisolvent_dispense_wait_start`, and `antisolvent_dispense_wait_end`.
3. Compute command delay and pump duration.
4. Match the command event to the nearest HC sensor timestamp.
5. Decide whether the sample is valid, invalid, or requires review.

## Audit Confirmation

This audit created documentation only. No operational Python code, imports, paths, hardware commands, or workflow behavior were edited.
