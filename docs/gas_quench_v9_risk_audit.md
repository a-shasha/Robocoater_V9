# Gas Quench V9 Risk Audit

Audit date: 2026-05-18

Scope: documentation-only review of `gas_quench_v9/`. No operational code was edited. Findings below describe current baseline behavior and candidate future work only.

## Executive Summary

Top 5 risks:

1. Gas-quench timing is based on a fixed 3 s pretrigger estimate, not a measured valve/nozzle event.
2. Gas valve open/close are logged only as recipe-relative sequence events; there is no wall-clock or monotonic event log equivalent to the antisolvent workflow.
3. Pump dispense and withdraw polling in the gas-quench workflow has no explicit timeout or pump abort path, so a pump status loop can block the campaign.
4. Relay hardware identity is hard-coded to a specific HID serial, and relay/servo state is not independently confirmed.
5. JSON writes and campaign-log updates are non-atomic, so interruption or corruption can erase or partially overwrite campaign state.

## Risk Table

| Risk ID | Category | Description | Severity | File/function | Physical consequence | Data consequence | Recommended next step |
|---|---|---|---|---|---|---|---|
| GQ-R001 | Gas-quench timing mismatch | Requested gas-quench start time and duration are defined by LHS/HOLMES parameters, clipped by `constrain_parameters()`, and passed as `gqTime` and `gqDuration` into the recipe. | High | `gas_quench_v9/run_campaign.py::constrain_parameters`; `run_experiment`; `Perovskite_Recipe_SD.py::run_Perovskite_Recipe` | Gas may be delivered at a different film-growth state than the requested action implies. | HOLMES can learn from labels that do not match the physical gas event. | Validate requested time versus software valve-command time and external HC/gas response before changing behavior. |
| GQ-R002 | Gas-quench timing mismatch | Pretrigger compensation is `GAS_QUENCH_PRETRIGGER_S = RELAY_CONNECT_SETTLE_S + GAS_QUENCH_SERVO_SETTLE_S`, currently 3.0 s. This assumes relay connect and servo settle are stable. | High | `Dual_Send_Commands.py` relay constants; `Perovskite_Recipe_SD.py::run_Perovskite_Recipe` | Variable relay connect, vendor CLI, USB, or servo latency can shift valve opening early or late. | Saved `Gas Quench Start Time` remains requested, not measured. | Add validation-only timing measurement of relay connect, servo move, relay open, and gas response across repeated trials. |
| GQ-R003 | Gas-quench timing mismatch | The recipe sleeps `max(0, gqTime - gas_pretrigger_s)` after spin/in-situ startup, then starts a gas-quench thread. Python scheduling and thread startup add unmeasured delay. | Medium | `Perovskite_Recipe_SD.py::run_Perovskite_Recipe` | Valve open may occur late during CPU, I/O, or thread contention. | Sequence log can understate timing uncertainty. | Later patch should log thread scheduled/start times and command latency, or avoid thread scheduling at the critical edge. |
| GQ-R004 | Gas-quench timing mismatch | Actual relay open/close commands occur in `doQuench()`, but physical gas arrival at the nozzle/substrate is not measured. | High | `Dual_Send_Commands.py::doQuench` | Gas pressure propagation and valve/nozzle dynamics can shift the physical quench relative to relay command. | Reported event timing is command-based, not physical-event-based. | Use HC sensor, pressure sensor, or synchronized video to estimate relay-command-to-gas-arrival offset. |
| GQ-R005 | Gas-quench timing mismatch | Valve open duration is implemented as `time.sleep(max(0.0, float(duration)))` between `relay_on(1)` and `relay_off(1)`. The duration excludes possible relay command execution time and physical valve lag. | Medium | `Dual_Send_Commands.py::doQuench` | Actual gas exposure duration may differ from requested duration. | Saved `Gas Quench Duration` may not equal physical exposure time. | Validate valve-open pulse width with relay command logs plus independent gas/pressure measurement. |
| GQ-R006 | Gas hardware/control risk | Relay target resolution prefers vendor CLI/DLL/HID paths and uses a hard-coded preferred serial `QAAMZ` with COM fallback disabled. This pins the lab relay but reduces portability. | High | `Dual_Send_Commands.py::resolve_usb_relay_target`; module constants | Wrong relay, missing relay, or changed relay serial can block or misroute gas control. | Campaign may fail before wet chemistry or run with unverified relay identity if settings are stale. | Document relay serial in a lab hardware manifest and add a preflight report that prints and records resolved relay identity. |
| GQ-R007 | Gas hardware/control risk | Relay resolution is called before wet chemistry and again inside `doQuench()`. A preflight success does not guarantee the later connect/open call will succeed under load. | Medium | `run_campaign.py::run_experiment`; `Perovskite_Recipe_SD.py::run_Perovskite_Recipe`; `Dual_Send_Commands.py::doQuench` | Relay may fail at the actual gas event after deposition has started. | Sample may be saved/analyzed as a GQ run if failure handling does not mark it clearly in outputs. | Later patch should record relay preflight identity and actual event backend/command status in the saved JSON. |
| GQ-R008 | Gas hardware/control risk | Relay connection failure generally raises and stops the recipe before or during gas event, but failures before `relay_1_open = True` have no channel-close attempt because the channel was never marked open. | Medium | `Dual_Send_Commands.py::doQuench`; `Perovskite_Recipe_SD.py::_run_gas_quench` | If actual hardware state differs from the flag state, gas state may be ambiguous after an exception. | Logs may lack a definitive closed-state confirmation. | Later patch should add a best-effort relay close attempt in more failure paths and log close verification status. |
| GQ-R009 | Gas hardware/control risk | If relay channel 1 is open, `doQuench()` attempts a failsafe close in `finally`, but any close exception is swallowed. | High | `Dual_Send_Commands.py::doQuench` | Gas valve may remain open if close command fails and the exception is suppressed. | Sequence log may not indicate failed close. | Later patch should record close failure visibly and trigger an operator stop condition; validate manual gas shutoff procedure. |
| GQ-R010 | Gas hardware/control risk | Gas servo position is commanded by `pumpArm.write(angle[sn])` with `gasQuenchSlot = 4` and `angle[4] = 78`, but no position feedback confirms the nozzle reached the intended state. | High | `Perovskite_Recipe_SD.py`; `Dual_Send_Commands.py::doQuench`; module `angle` constants | Gas may miss the substrate or partially block/shift the quench. | Run metadata records intended GQ parameters but not actual nozzle position. | Before glovebox move, validate servo angle and add operator-visible position check or sensor feedback plan. |
| GQ-R011 | Perovskite dispense and spin coordination | Perovskite pre-prime, dispense, and post-withdraw occur before spread and spin. Dispense runs in a thread, and post-withdraw runs in another thread that joins the dispense thread. Exceptions in those threads are not captured by the main recipe. | High | `Perovskite_Recipe_SD.py::run_Perovskite_Recipe`; `Dual_Send_Commands.py::dispense`; `withdraw_Only` | Failed perovskite delivery may not stop spin/gas/spectroscopy sequence. | A sample can be analyzed as if deposition occurred normally. | Later patch should wrap worker threads and propagate dispense/withdraw failures before gas quench. |
| GQ-R012 | Perovskite dispense and spin coordination | Spin ramp starts in a thread immediately before in-situ acquisition and gas scheduling. The recipe does not join or verify `tSpin` before the gas-quench timing window. | Medium | `Perovskite_Recipe_SD.py::multi_spin`; `run_Perovskite_Recipe` | Gas event may occur while the spinner is not at expected RPM if ODrive command is delayed or fails. | Saved run parameters may imply target RPM without confirmation. | Add spinner command acknowledgement/status logging and validate RPM ramp timing before relying on GQ event alignment. |
| GQ-R013 | Perovskite dispense and spin coordination | Gas-quench thread exceptions are captured in `gas_quench_errors` and checked during the wait loop and after join. This is stronger than other worker threads but still relies on polling every 0.2 s. | Medium | `Perovskite_Recipe_SD.py::_run_gas_quench`; wait loop | A failed gas command may be detected after a short delay while the sample keeps spinning. | The sample can fail after partial run data have been collected. | Keep this pattern and extend it to pump, spin, and in-situ threads; mark failed GQ samples invalid in outputs. |
| GQ-R014 | Perovskite dispense and spin coordination | `remainingSpinTime = gqTime` after gas thread starts, so runtime wait assumes the gas start occurred at the requested time rather than the actual valve-open time. | Medium | `Perovskite_Recipe_SD.py::run_Perovskite_Recipe` | Total post-quench collection window can be shorter or longer than intended if gas starts late/early. | Spectroscopy time windows may be misaligned with physical gas exposure. | Later patch should base post-event runtime on measured/logged valve-open time when available. |
| GQ-R015 | Logging and timestamp quality | Gas valve events are logged in `sequenceName`/`sequenceTime` only. There is no active `Operation_Event_Log.csv`, no wall-clock timestamp column, and no monotonic sample-start elapsed log for gas-quench events. | High | `Dual_Send_Commands.py::doQuench`; `Perovskite_Recipe_SD.py` `dfLog` creation | Operators cannot reliably align gas events with external HC sensor CSV timestamps from saved JSON alone. | Campaign reconstruction lacks sub-second cross-system timing evidence. | Add a GQ event log equivalent to the antisolvent event logger before glovebox validation. |
| GQ-R016 | Logging and timestamp quality | `sequenceTime` values are based on `time.time() - timeStart`; spectroscopy columns are relative to collection start; file timestamps are OS-level only. These are different time bases. | Medium | `Dual_Send_Commands.py`; `Dual_Send_OceanFlame.py`; `Save_Data.py` | Operators may compare incompatible event times. | Misaligned analysis can misidentify pre/post-GQ spectral regions. | Document timing semantics in operator workflow and add synchronized wall-clock event rows for gas events. |
| GQ-R017 | Logging and timestamp quality | Missing event logs include relay target selected, relay connect start/end, servo command start/end, relay open command sent/returned, relay close command sent/returned, disconnect status, and failsafe close failures. | High | `Dual_Send_Commands.py::resolve_usb_relay_target`; `doQuench` | Ambiguous gas state after a failure or odd run. | Cannot reconstruct whether gas valve actually opened/closed as intended. | Later patch should add structured gas-event logging with backend, serial, command status, and exception state. |
| GQ-R018 | Logging and timestamp quality | External HC sensor alignment is not robust from current GQ raw JSON because no wall-clock event timestamps are saved for GQ valve events. | High | `Save_Data.py`; `Perovskite_Recipe_SD.py` | Physical gas event correlation may be guesswork. | HC/GQ comparison can be off by seconds. | Before glovebox move, run a dedicated clock/trigger alignment test and add wall-clock GQ event logging. |
| GQ-R019 | Robustness and failure handling | Pump `DIS` polling loops in `dispense()`, `dispense_Only()`, `withdraw_Only()`, and related functions have no explicit timeout or `STP` abort path. | Critical | `Dual_Send_Commands.py::dispense`; `dispense_Only`; `withdraw_Only`; `dispense_n_withdraw`; `prime` | Pump or recipe can hang indefinitely with fluid or hardware in an unsafe intermediate state. | Sample and campaign logs may never be written, and resume state may be ambiguous. | Port the validated antisolvent pump timeout/abort pattern into GQ only after bench validation. |
| GQ-R020 | Robustness and failure handling | Pump serial command responses are returned but not validated or logged. Malformed or rejected commands can pass until later behavior fails or hangs. | High | `Dual_Send_Commands.py::sendCMD`; pump command functions | Wrong volume, direction, rate, or no dispense can occur unnoticed. | Saved parameters can represent requested settings rather than confirmed hardware state. | Add structured pump command/response parsing and stop on invalid acknowledgements. |
| GQ-R021 | Robustness and failure handling | Spectrometer connection failure sets `device = None`, but later `create_Dataframes()` calls `get_Wavelengths()` and can fail. In-situ acquisition thread exceptions are not captured by the recipe. | High | `Dual_Send_OceanFlame.py` initialization; `create_Dataframes`; `run_dual_InSitu` | Run may abort before chemistry or continue with incomplete spectra if a thread fails mid-run. | JSON can be missing spectra or use partial data for utility. | Add preflight hard fail for missing spectrometer and capture in-situ thread exceptions before save/analysis. |
| GQ-R022 | Robustness and failure handling | Camera capture retries once, prints an error, and returns without raising. The recipe then continues to save and analyze. | High | `Dual_Send_Camera.py::cap_Picture`; `Perovskite_Recipe_SD.py::run_Perovskite_Recipe` | Failed final image can go unnoticed during an autonomous run. | Classification may use error fallback or missing image behavior, corrupting utility. | Make camera capture return explicit success/failure and mark sample invalid on failure. |
| GQ-R023 | Robustness and failure handling | Recipe `finally` stops spinner and turns off LEDs. Campaign `finally` stops spinner, closes LED/pump/Arduino serials, and closes spectrometer. Gas valve close is only attempted inside `doQuench()` if that function reached its relay-open tracking. | High | `Perovskite_Recipe_SD.py::finally`; `run_campaign.py::finally`; `Dual_Send_Commands.py::doQuench`; `close_Ser` | Spinner/LED shutdown is covered, but gas state may remain ambiguous after certain relay failures. | Final logs may not prove gas closed. | Add operator stop procedure for gas shutoff and future all-hardware shutdown confirmation logging. |
| GQ-R024 | Robustness and failure handling | `analyze_Data()` catches exceptions and prints traceback without raising. `save_experiment_log()` expects analyzed JSON with utility and parameters and may fail afterward. | Medium | `Analysis_SD.py::analyze_Data`; `Analysis_2/Save_Campaign_Log.py::save_experiment_log` | Physical run is complete, but campaign progression can stop after analysis failure. | Observation may be missing; resume count can be inconsistent with raw outputs. | Return explicit analysis status and prevent campaign log append from silently using invalid data. |
| GQ-R025 | JSON/data integrity | Raw JSON, analyzed JSON, master JSONs, and `Campaign_Experiments.json` are written directly with `open(..., 'w')` and `json.dump()`, not atomically. | High | `Save_Data.py::save_Data`; `Analysis_SD.py::_update_json_file`; `Save_Campaign_Log.py::save_experiment_log` | None directly, but recovery decisions can affect future physical runs. | Power loss/interruption can leave partial/truncated JSON. | Later patch should write to temp files, flush/fsync, and `os.replace()`. |
| GQ-R026 | JSON/data integrity | If `Campaign_Experiments.json` cannot be read, the campaign reader returns `{}` and campaign-log writer starts from `{}`. This can mask corruption and overwrite history. | High | `run_campaign.py::_read_campaign_dict`; `Save_Campaign_Log.py::save_experiment_log` | Campaign can repeat or skip actions after corrupted state. | HOLMES training history can be lost or reset. | Quarantine unreadable campaign logs and require human decision before continuing. |
| GQ-R027 | JSON/data integrity | Resume count is based on `len(Campaign_Experiments.json)`, while raw/analyzed JSON files may exist for runs not in that log. | Medium | `run_campaign.py::main`; `Save_Campaign_Log.py` | Existing run outputs can be overwritten if campaign log is incomplete. | Raw data, images, and analyzed outputs can be disconnected from campaign state. | Add output-collision checks and compare campaign log against files before resume. |
| GQ-R028 | JSON/data integrity | Classified image output removes an existing destination before rename/copy. Repeated file names can replace image evidence. | Medium | `Analysis_2/Film_Classification_2.py::classify_Film` | Prior sample image can be lost. | Film ranking traceability can be compromised. | Refuse overwrites or archive prior outputs during recovery mode. |
| GQ-R029 | Operator workflow and handoff readiness | Manual pause occurs every three completed runs with a generic `Press Enter to continue` prompt. It does not show gas-specific checklist items. | Medium | `run_campaign.py::_pause_if_needed`; `training/operator_checklist.md` | Operator may resume with unresolved gas/relay/nozzle state. | Pause decisions are not captured in campaign artifacts. | Add a gas-quench pause checklist with relay identity, gas off confirmation, nozzle state, and output preservation checks. |
| GQ-R030 | Operator workflow and handoff readiness | Ambiguous gas states are possible after relay errors, swallowed close exceptions, or missing event logs. | High | `Dual_Send_Commands.py::doQuench`; training docs | Operator may assume gas is off when the software cannot prove it. | Run validity and safety notes may be incomplete. | Make any relay error or missing close confirmation a stop condition with manual gas shutoff verification. |
| GQ-R031 | Operator workflow and handoff readiness | Glovebox move increases consequences of gas/nozzle/line ambiguity because access, visibility, and manual intervention may be constrained. | High | Workflow-level operating procedure | Harder recovery from gas, servo, or fluid problems inside glovebox. | Failed runs may be harder to diagnose after relocation. | Complete relay, gas, servo, pump timeout, and logging validation before moving. |

## Timing Trace For Gas Quench

Requested gas-quench start time and duration are defined in:

- LHS seed arrays and HOLMES suggestions in `gas_quench_v9/run_campaign.py`.
- `constrain_parameters()`, which clips the requested time/duration to `HOLMES_BOUNDS`.
- `run_experiment()`, which assigns `gqTime, gqDuration` and passes both into `run_Perovskite_Recipe()`.

Pretrigger compensation is calculated in:

- `gas_quench_v9/Dual_Send_Commands.py`
- `RELAY_CONNECT_SETTLE_S = 2.0`
- `GAS_QUENCH_SERVO_SETTLE_S = 1.0`
- `GAS_QUENCH_PRETRIGGER_S = RELAY_CONNECT_SETTLE_S + GAS_QUENCH_SERVO_SETTLE_S`

Gas scheduling occurs in:

- `gas_quench_v9/Perovskite_Recipe_SD.py`
- the recipe sleeps `max(0, gqTime - gas_pretrigger_s)`
- then starts `GasQuenchThread`, which calls `DSC.doQuench(gasQuenchSlot, timeStart, gqDuration)`

Relay and servo actions occur in `Dual_Send_Commands.py::doQuench()`:

1. Resolve relay target.
2. Instantiate selected backend.
3. `relay.connect()`.
4. Log "Servo move over substrate for gas quenching" and command `pumpArm.write(angle[sn])`.
5. Sleep 1 s for servo settle.
6. `relay.relay_on(1)` and log "Gas Valve Opened".
7. Sleep for requested duration.
8. `relay.relay_off(1)` and log "Gas Valve Closed".
9. In `finally`, attempt failsafe close if `relay_1_open` is still true.
10. Return the servo arm home.
11. Disconnect relay.

Important limitation: "Gas Valve Opened" and "Gas Valve Closed" are software command events in `sequenceName`/`sequenceTime`. They do not directly measure valve electrical state, gas pressure, gas arrival at the nozzle, or gas impact at the substrate.

## Logging And Timestamp Quality

The gas-quench workflow has these timing records:

- Recipe-relative `sequenceTime` values in raw JSON `Log`, calculated with `time.time() - timeStart`.
- Spectroscopy dictionary keys, calculated relative to each in-situ acquisition start.
- File-system timestamps for generated files, available outside JSON but not structured into campaign data.

The gas-quench workflow does not currently have:

- a structured wall-clock event log for relay or pump events
- monotonic elapsed event rows from sample start
- millisecond wall-clock rows suitable for direct HC sensor CSV alignment
- explicit event rows for relay command sent/returned status

Because of that, external HC sensor CSV alignment is weaker than in the antisolvent workflow. For now, alignment should be treated as approximate unless a separate synchronized event marker is created.

## Gas Hardware And Control Notes

NOYITO relay target resolution:

- searches repo-relative NOYITO support folders
- prefers vendor CLI when command app and relay serial are usable
- can use the vendor DLL backend
- can use the lab Python `usbrelay` module only if configured
- serial fallback is disabled in the active HID configuration
- active preferred relay serial is `QAAMZ`

Relay connection failure:

- preflight relay resolution in `run_campaign.py` should fail before wet chemistry if the target cannot be resolved
- `run_Perovskite_Recipe()` repeats relay resolution before deposition
- `doQuench()` can still fail later during connect/open/close

Relay channel close:

- normal close occurs after the requested duration
- failsafe close is attempted if `relay_1_open` remains true
- close exceptions during failsafe are swallowed
- there is no independent verification that gas flow actually stopped

Servo state:

- gas nozzle servo uses `gasQuenchSlot = 4`
- the active angle array sets slot 4 to 78 degrees
- there is no servo position feedback
- the recipe assumes 1 s settle time is enough

## Robustness And Failure Handling

Relay command failure:

- open/close command failures raise through `doQuench()`
- the gas-quench thread captures exceptions and the main recipe checks `gas_quench_errors`
- a close failure during the failsafe close path is suppressed

Pump serial command failure:

- import-time serial open failure should prevent campaign startup
- runtime serial errors can raise from pump functions
- malformed pump responses are not parsed or validated consistently

Pump polling timeout:

- no explicit pump polling timeout exists in the GQ command layer
- loops wait for status `S`
- no GQ pump `STP` abort path is present

Spectrometer failure:

- connection failure sets `device = None`
- later `create_Dataframes()` or acquisition calls can fail
- in-situ acquisition thread exceptions are not captured by the main recipe

Camera failure:

- camera capture prints and returns after one retry
- the recipe continues to save and analyze

Shutdown:

- recipe `finally` attempts spinner stop and turns off reflection/PL LEDs
- campaign `finally` stops spinner, closes serial/Arduino handles, and closes spectrometer
- gas valve cleanup depends on `doQuench()` reaching its internal `finally`
- there is no final hardware state report proving gas closed, pumps stopped, spinner stopped, LEDs off, and spectrometer closed

## JSON And Data Integrity

JSON writes are not atomic:

- raw JSON in `Save_Data.py`
- analyzed JSON and master JSONs in `Analysis_SD.py`
- `Campaign_Experiments.json` in `Save_Campaign_Log.py`

Campaign log corruption risks:

- campaign read failures become `{}` in the runner
- campaign-log write read failures also become `{}`
- a corrupt log can be overwritten and campaign history lost

Resume risks:

- resume uses `len(Campaign_Experiments.json)`
- raw/analyzed files can exist without campaign entries
- repeated names can overwrite prior outputs

Old output overwrite risks:

- raw/analyzed JSON write directly to fixed names
- master JSON entries are replaced by key
- classifier can remove existing destination image before rename/copy

## First Safe Patches To Consider Later

Do not implement these in this audit branch without explicit approval:

1. Add a GQ operation event logger with wall-clock timestamps, monotonic sample elapsed time, and gas-specific events.
2. Log relay target identity, backend, serial, command app/DLL path, and relay resolution result into saved run metadata.
3. Log relay connect start/end, servo move command, relay open command sent/returned, relay close command sent/returned, failsafe close result, and disconnect status.
4. Make failsafe close failures visible and sample-invalidating instead of swallowed.
5. Add a safe gas-off verification checklist and later hardware signal if available.
6. Port the antisolvent pump timeout/abort pattern into the gas-quench workflow after bench validation.
7. Wrap perovskite dispense, post-withdraw, spin, and in-situ threads so exceptions propagate to the recipe.
8. Make camera capture return explicit success/failure and mark sample invalid on failure.
9. Add atomic JSON write helpers using temp files and `os.replace()`.
10. Quarantine unreadable campaign logs instead of continuing from `{}`.
11. Add output-file collision checks before running a sample.
12. Add spinner status/RPM confirmation to the saved log before gas-quench timing validation.

## Validation Tests Required Before Glovebox Move

1. Relay resolution test: confirm the resolved backend and relay serial match the intended relay on the lab PC.
2. Relay open/close bench test: repeat open/close pulses and verify channel state with independent observation.
3. Gas-off failsafe test: force an exception after open and confirm gas closes and the failure is visible.
4. Servo angle test: verify slot 4 at 78 degrees centers the gas nozzle and does not collide with other hardware.
5. Pretrigger timing test: measure relay connect time, servo move time, relay open command return, and physical gas response.
6. Pulse-duration test: compare requested duration to measured gas-flow duration across 1, 2.5, 8, and 14 s pulses.
7. Spin coordination test: verify spinner reaches the expected RPM before the earliest GQ event.
8. Pump timeout test: simulate non-stopping pump status in a safe setup and define GQ abort behavior.
9. Spectrometer failure test: disconnect spectrometer and confirm campaign does not proceed into wet chemistry.
10. Camera failure test: block or disconnect camera and confirm operator stop procedure catches failure.
11. JSON interruption test: interrupt raw/analyzed/campaign JSON writes in a copy of data and verify recovery plan.
12. Resume test: resume with existing raw/analyzed files and incomplete campaign log; verify no overwrite.
13. HC alignment test: generate a synchronized gas event and confirm acceptable timestamp matching tolerance.
14. Glovebox dry-run: perform a no-chemistry gas/nozzle/spinner/camera/spectrometer sequence in the glovebox-equivalent layout.

## Operator Handoff Implications

The operator should be trained to distinguish:

- requested GQ time: the action selected by LHS/HOLMES
- software gas command time: when relay open/close commands are issued
- physical gas event time: when gas reaches and affects the substrate
- analysis event time: where plots and utility treat the GQ point

The operator should not treat those as equivalent until validation establishes a stable offset.

Training should emphasize:

- Do not press Enter at the pause prompt until the gas-quench checklist is complete.
- Confirm relay identity and gas-off state before each campaign segment.
- Treat any relay warning, missing close confirmation, pump hang, camera error, spectrometer error, or analysis traceback as a stop condition.
- Preserve the entire campaign folder, raw/analyzed JSON, images, and operator notes after any stop.
- Do not hand-edit or overwrite `Campaign_Experiments.json` during a campaign.
- If gas state is ambiguous, stop and verify manually before any software restart.
- If a run is stopped or uncertain, do not reuse the same output folder without a recovery decision.

Recommended handoff exercise:

1. Run one dry GQ sample with no chemistry.
2. Identify requested GQ time/duration in raw JSON tags.
3. Locate "Servo move over substrate for gas quenching", "Gas Valve Opened", "Gas Valve Closed", and "Servo moved home" in the raw JSON log.
4. Compute software valve-open offset from requested GQ time.
5. Compare the software event to an external gas/HC/timestamp record if available.
6. Decide whether the sample is valid, invalid, or requires review.

## Audit Confirmation

This audit created documentation only. No operational Python code, imports, paths, hardware commands, or workflow behavior were edited.
