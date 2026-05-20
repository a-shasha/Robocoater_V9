# Robocoater V9 First Safe Patch Backlog

This backlog translates the architecture maps and risk audits into a conservative first implementation plan for Robocoater V9 stabilization.

## Executive Summary

- Antisolvent V9 is the stronger current operational baseline. It already has a more mature `Operation_Event_Log.csv`, pump polling timeout behavior, and clearer event reconstruction path.
- Gas Quench V9 must be stabilized separately. Its relay/gas path, pump polling, gas-event logging, and glovebox-readiness risks should not be treated as solved by antisolvent fixes.
- First patches should improve observability and failure containment, not change chemistry or recipe behavior.
- Start with antisolvent V9, not gas quench. Antisolvent is the safer proving ground for logging, status propagation, and data-integrity patches.
- Do not change drip compensation, gas pretrigger compensation, pump recipe, spin profile, HOLMES policy, classifier/model behavior, or recipe timing in first patches.

Priority definitions:

- P0: must validate or document before any physical move or operator handoff.
- P1: first safe code patches.
- P2: important, but after P1 behavior is validated.
- P3: later redesign or V10 work.

Recommended first implementation order:

1. Complete P0 validation-only and documentation work for timebase alignment, stop conditions, and bench-test procedures.
2. Implement antisolvent-first P1 logging and failure-propagation patches.
3. Validate those patterns with dry runs, simulated failures, and benign bench tests.
4. Port the proven observability and failure-containment patterns to gas quench.
5. Defer timing compensation, recipe, model, HOLMES, and UI redesign work until V9 behavior is measured and stable.

## A. Cross-Workflow Safety Patches

| Patch ID | Priority | Workflow | Title | Risk addressed | Severity | Files likely affected | Why this is safe or not safe | What must not change | Required validation before/after | Recommended branch name | Recommended commit message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V9-P0-X01 | P0 | cross-workflow | Write validation matrix for timebase and event reconstruction | AS-R011, AS-R012, AS-R025, GQ-R015, GQ-R016, GQ-R018 | High | `docs/`, `validation/` | Safe because it is documentation-only and defines how evidence will be judged before code changes. | No code, recipe timing, compensation values, HOLMES behavior, or model behavior. | Before: review both risk audits. After: each high-risk timing issue maps to a dry-run or bench validation method. | `stabilize/v9-validation-matrix` | `docs: define V9 validation matrix` |
| V9-P0-X02 | P0 | cross-workflow | Define operator stop-and-preserve checklist | AS-R023, AS-R024, GQ-R029, GQ-R030, GQ-R031 | High | `training/operator_checklist.md`, `training/stop_conditions.md`, `docs/` | Safe because it clarifies operator response without changing automation behavior. | No hardware commands, prompts in code, recipe order, or campaign policy. | Before: review known failure modes. After: checklist covers pump timeout, camera failure, spectrometer failure, analysis traceback, relay warning, and missing close confirmation. | `stabilize/operator-stop-checklist` | `docs: define V9 stop-and-preserve checklist` |
| V9-P1-X01 | P1 | cross-workflow | Add append-only event logging for command status and timebase alignment | AS-R011, AS-R013, AS-R014, GQ-R015, GQ-R017, GQ-R018 | High | `antisolvent_v9/Dual_Send_Commands.py`, `antisolvent_v9/Perovskite_Recipe_SD.py`, `gas_quench_v9/Dual_Send_Commands.py`, `gas_quench_v9/Perovskite_Recipe_SD.py`, possibly shared docs | Safe if it only adds append-only log rows and does not gate or reorder recipe actions. Not safe if it changes sleeps, command order, or command parameters. | Drip compensation, gas pretrigger, recipe timing, pump volumes/rates, spin profile, HOLMES policy, model logic. | Before: dry-run current log sequence. After: dry-run confirms new rows appear with wall-clock and monotonic elapsed times while old behavior is unchanged. | `stabilize/v9-event-logging` | `stabilize: add V9 event trace logging` |
| V9-P1-X02 | P1 | cross-workflow | Propagate worker-thread failures to sample status | AS-R004, AS-R016, AS-R017, GQ-R011, GQ-R013, GQ-R021, GQ-R024 | Critical | `antisolvent_v9/Perovskite_Recipe_SD.py`, `gas_quench_v9/Perovskite_Recipe_SD.py`, possibly analysis status handling docs | Safe if it only marks failed samples invalid or stops after known failure without changing successful-path recipe actions. Not safe if it changes timing windows or suppresses exceptions. | Recipe timing, pump commands, gas commands, classifier scoring, HOLMES bounds. | Before: identify current worker threads and failure paths. After: simulated thread exceptions stop or invalidate the sample and are visible in logs. | `stabilize/v9-thread-failure-propagation` | `stabilize: propagate V9 worker thread failures` |
| V9-P1-X03 | P1 | cross-workflow | Add camera and analysis success/failure status to saved artifacts | AS-R014, AS-R017, AS-R024, GQ-R022, GQ-R024 | High | `antisolvent_v9/Dual_Send_Camera.py`, `gas_quench_v9/Dual_Send_Camera.py`, `Analysis_SD.py`, save/log docs | Safe if it records explicit status and prevents invalid observations from being treated as valid. Not safe if it changes classifier/model logic or image processing thresholds. | Classifier/model logic, utility formula, HOLMES policy, camera settings unless explicitly validated. | Before: dry-run with normal camera and analysis. After: blocked/missing camera and induced analysis error produce visible invalid status and no silent successful observation. | `stabilize/v9-capture-analysis-status` | `stabilize: record capture and analysis status` |
| V9-P2-X01 | P2 | cross-workflow | Add atomic JSON writes and corruption quarantine | AS-R020, AS-R021, AS-R022, GQ-R025, GQ-R026, GQ-R027, GQ-R028 | High | `Save_Data.py`, `Analysis_SD.py`, `Analysis_2/Save_Campaign_Log.py`, campaign resume helpers in both workflows | Safe after P1 logging because it changes persistence mechanics without changing recipe commands. Higher risk than P1 because resume behavior and file replacement semantics affect campaign continuity. | JSON schema meaning, HOLMES observation content, file naming policy unless a recovery mode is explicitly approved. | Before: capture current output file set and resume behavior. After: interruption/corrupt-file tests quarantine damage and preserve existing outputs. | `stabilize/v9-atomic-json-writes` | `stabilize: make V9 JSON writes recoverable` |
| V9-P2-X02 | P2 | cross-workflow | Add hardware preflight snapshot to run metadata | AS-R006, AS-R012, AS-R018, GQ-R006, GQ-R007, GQ-R010, GQ-R023 | High | `run_campaign.py`, `Dual_Send_Commands.py`, saved metadata docs in both workflows | Safe if it only records resolved hardware identity and preflight status. Not safe if it changes port discovery, fallback policy, or hardware command behavior. | Device identifiers, relay backend preference, serial ports, ODrive command path, pump setup commands. | Before: manual hardware manifest exists. After: dry run records pump, relay, ODrive, spectrometer, camera, LED, and endpoint identity/status. | `stabilize/v9-preflight-snapshot` | `stabilize: record V9 hardware preflight state` |

## B. Antisolvent-First Patches

| Patch ID | Priority | Workflow | Title | Risk addressed | Severity | Files likely affected | Why this is safe or not safe | What must not change | Required validation before/after | Recommended branch name | Recommended commit message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V9-P1-AS01 | P1 | antisolvent | Expand antisolvent event log around prep, dispense command, and completion | AS-R001, AS-R002, AS-R003, AS-R004, AS-R011, AS-R013 | High | `antisolvent_v9/Perovskite_Recipe_SD.py`, `antisolvent_v9/Dual_Send_Commands.py`, `antisolvent_v9/Operation_Event_Log_Guide.md` | Safe because antisolvent already has an event logger; the first patch can add evidence without changing the physical recipe. Not safe if it changes compensation or wait logic. | `antisolventDripEdgeCompensationS`, drip time/rate/volume, pump command sequence, spin profile, HOLMES inputs. | Before: dry run records existing event sequence. After: dry run shows requested drip time, compensated wait, prep completion, command sent/returned, and completion/error rows. | `stabilize/antisolvent-event-trace` | `stabilize(antisolvent): expand event trace logging` |
| V9-P1-AS02 | P1 | antisolvent | Join and check antisolvent dispense thread before successful save/analysis | AS-R004, AS-R009, AS-R019 | Critical | `antisolvent_v9/Perovskite_Recipe_SD.py`, possibly thread helper docs | Safe if successful runs follow the same timing and only failed worker threads alter sample status. Not safe if the join changes active timing before the dispense event or changes the recipe wait schedule. | Drip scheduling, pump command parameters, analysis algorithm, HOLMES policy. | Before: simulate worker-thread exception in a no-chemistry run. After: recipe does not mark the sample complete without a resolved dispense status. | `stabilize/antisolvent-thread-status` | `stabilize(antisolvent): check dispense thread status` |
| V9-P1-AS03 | P1 | antisolvent | Log pump command acknowledgements for antisolvent critical commands | AS-R005, AS-R006, AS-R013, AS-R015 | High | `antisolvent_v9/Dual_Send_Commands.py`, `antisolvent_v9/Operation_Event_Log_Guide.md` | Safe if it records raw responses and expected status without changing command values or retry policy. Not safe if it introduces new retries before bench validation. | Pump volume/rate/direction/unit commands, serial port, syringe diameter values, pre-prime/post-withdraw protocol. | Before: bench harmless pump command transcript. After: log contains `DIA`, `VOL UL`, `RAT`, `DIR`, `VOL`, `RUN`, `DIS`, and `STP` responses where applicable. | `stabilize/antisolvent-pump-ack-logging` | `stabilize(antisolvent): log pump command acknowledgements` |
| V9-P2-AS01 | P2 | antisolvent | Add all-pump stop confirmation to shutdown paths | AS-R018, AS-R019 | High | `antisolvent_v9/Dual_Send_Commands.py`, `antisolvent_v9/Perovskite_Recipe_SD.py`, `antisolvent_v9/run_campaign.py` | Not first-safe until `STP` and pump-state behavior are validated on hardware. Safe after validation if stop is idempotent, logged, and only runs during shutdown or failure. | Normal recipe pump commands, flow rates, volumes, timing, serial setup. | Before: bench-test `STP` with harmless setup. After: forced exception confirms stop attempt and result are logged for each relevant pump. | `stabilize/antisolvent-pump-shutdown` | `stabilize(antisolvent): confirm pump shutdown state` |
| V9-P2-AS02 | P2 | antisolvent | Refuse silent campaign-log reset on unreadable JSON | AS-R020, AS-R021, AS-R022 | High | `antisolvent_v9/run_campaign.py`, `antisolvent_v9/Analysis_2/Save_Campaign_Log.py` | Safe after output-handling tests, because it prevents dangerous silent recovery. Not first-safe if it blocks existing recovery patterns without an operator procedure. | Existing successful campaign schema, HOLMES observation fields, file naming for valid runs. | Before: create controlled corrupt copy of campaign log. After: code quarantines or stops with a clear recovery note and preserves old outputs. | `stabilize/antisolvent-campaign-log-guard` | `stabilize(antisolvent): guard campaign log recovery` |

## C. Gas-Quench-Specific Patches

Gas quench should not be the first code patch target. Apply gas-quench code changes only after the equivalent antisolvent logging and failure-propagation patterns are reviewed and validated.

| Patch ID | Priority | Workflow | Title | Risk addressed | Severity | Files likely affected | Why this is safe or not safe | What must not change | Required validation before/after | Recommended branch name | Recommended commit message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V9-P0-GQ01 | P0 | gas-quench | Complete relay, servo, gas-off, and pump-timeout bench plan | GQ-R006, GQ-R009, GQ-R010, GQ-R019, GQ-R030, GQ-R031 | Critical | `docs/`, `validation/`, `training/stop_conditions.md` | Safe because it is validation-only. It is required because gas failures can leave ambiguous valve or pump states. | No relay commands, servo angle, gas pretrigger, pump polling, or recipe code. | Before: review current relay and pump functions. After: plan defines relay identity test, failsafe close test, manual gas shutoff verification, and pump timeout simulation. | `stabilize/gq-bench-validation-plan` | `docs(gas-quench): define bench validation plan` |
| V9-P1-GQ01 | P1 | gas-quench | Add GQ operation event log with wall-clock and monotonic rows | GQ-R015, GQ-R016, GQ-R017, GQ-R018 | High | `gas_quench_v9/Dual_Send_Commands.py`, `gas_quench_v9/Perovskite_Recipe_SD.py`, `gas_quench_v9/Save_Data.py` | Safe if it mirrors the antisolvent append-only event log and records only observations. Not safe if it alters relay scheduling or gas duration. | `GAS_QUENCH_PRETRIGGER_S`, relay connect order, servo angle, relay channel, gas duration, spin profile. | Before: dry run current GQ sequence. After: log includes relay target, connect start/end, servo command, relay open/close sent/returned, failsafe close, disconnect, and exception status. | `stabilize/gq-event-logging` | `stabilize(gas-quench): add operation event logging` |
| V9-P1-GQ02 | P1 | gas-quench | Analyze and then port pump timeout/abort behavior from antisolvent | GQ-R019, GQ-R020, GQ-R011 | Critical | `gas_quench_v9/Dual_Send_Commands.py`, `gas_quench_v9/Perovskite_Recipe_SD.py`, validation docs | Not safe until bench validation confirms timeout and `STP` behavior. Safe after validation if the first implementation only bounds indefinite waits and logs abort results. | Pump volumes/rates, pre-prime/post-withdraw sequence, serial port, recipe timing, gas timing. | Before: harmless bench setup simulates non-stopping pump status. After: no GQ pump wait can block indefinitely, and timeout results are logged and propagated. | `stabilize/gq-pump-timeout` | `stabilize(gas-quench): bound pump polling waits` |
| V9-P1-GQ03 | P1 | gas-quench | Propagate perovskite dispense and withdraw thread failures before gas event | GQ-R011, GQ-R013, GQ-R023 | High | `gas_quench_v9/Perovskite_Recipe_SD.py` | Safe if it prevents gas/quench continuation after known dispense failure. Not safe if it changes normal dispense timing or starts gas later in successful runs. | Perovskite volume/rate, pre-prime/post-withdraw behavior, spin ramp, gas pretrigger, relay commands. | Before: simulate pump-thread exception before gas event. After: recipe stops or marks invalid before gas actuation and logs the reason. | `stabilize/gq-dispense-thread-status` | `stabilize(gas-quench): propagate dispense thread failures` |
| V9-P2-GQ01 | P2 | gas-quench | Log relay identity and close confirmation into saved metadata | GQ-R006, GQ-R007, GQ-R008, GQ-R009, GQ-R017, GQ-R030 | High | `gas_quench_v9/Dual_Send_Commands.py`, `gas_quench_v9/Save_Data.py`, `gas_quench_v9/run_campaign.py` | Safe after P1 event logging because metadata can summarize already-collected command evidence. Not safe if it changes relay target resolution or backend preference. | Preferred serial `QAAMZ`, CLI/DLL/HID selection policy, relay channel, gas-off manual procedure. | Before: relay resolution test. After: saved JSON names backend, serial, command path, open/close result, failsafe close result, and disconnect result. | `stabilize/gq-relay-metadata` | `stabilize(gas-quench): record relay event metadata` |
| V9-P2-GQ02 | P2 | gas-quench | Add camera, spectrometer, and analysis invalid-sample gates | GQ-R021, GQ-R022, GQ-R024 | High | `gas_quench_v9/Dual_Send_OceanFlame.py`, `gas_quench_v9/Dual_Send_Camera.py`, `gas_quench_v9/Analysis_SD.py`, `gas_quench_v9/Analysis_2/Save_Campaign_Log.py` | Safe after antisolvent status pattern is validated. Not safe if it changes analysis math, classification logic, or HOLMES observations without review. | Model path behavior, utility calculation, HOLMES policy, acquisition settings. | Before: induce missing spectrometer/camera/analysis failures. After: invalid sample status prevents silent successful campaign observation. | `stabilize/gq-data-quality-gates` | `stabilize(gas-quench): gate invalid run observations` |

## D. Validation-Only Work Before Code Patches

| Patch ID | Priority | Workflow | Title | Risk addressed | Severity | Files likely affected | Why this is safe or not safe | What must not change | Required validation before/after | Recommended branch name | Recommended commit message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V9-P0-VAL01 | P0 | cross-workflow | Build dry-run script checklist from existing operator steps | AS-R023, AS-R024, GQ-R029, GQ-R030 | High | `validation/`, `training/operator_checklist.md` | Safe because it documents the dry-run steps and expected artifacts before any code change. | No automation logic, prompts, device commands, or recipe timing. | Before: inventory current dry-run artifacts. After: checklist names expected logs, JSON files, images, and stop conditions. | `stabilize/v9-dry-run-checklist` | `docs: add V9 dry-run validation checklist` |
| V9-P0-VAL02 | P0 | antisolvent | Validate antisolvent event log against external HC timestamps | AS-R001, AS-R003, AS-R011, AS-R012, AS-R025 | High | `validation/antisolvent/`, `docs/` | Safe because it measures current behavior without modifying code. | Compensation, pump timing, camera/spectrometer behavior, HC data format. | Before: synchronize PC and HC sensor clocks. After: accepted alignment tolerance and observed command-to-physical offset are documented. | `stabilize/antisolvent-hc-alignment` | `validation(antisolvent): document HC alignment test` |
| V9-P0-VAL03 | P0 | gas-quench | Validate gas relay timing and close behavior without chemistry | GQ-R001, GQ-R002, GQ-R004, GQ-R005, GQ-R009, GQ-R018 | Critical | `validation/gas_quench/`, `docs/` | Safe only if performed without chemistry and with manual gas shutoff available. It is not safe as a physical campaign. | Gas pretrigger, relay command code, servo angle, gas duration, recipe timing. | Before: gas path reviewed and manual shutoff ready. After: relay connect, servo move, open command, close command, and physical gas response are measured or blocked as unresolved. | `stabilize/gq-relay-timing-validation` | `validation(gas-quench): document relay timing test` |
| V9-P0-VAL04 | P0 | cross-workflow | Define output preservation and rollback procedure | AS-R020, AS-R021, AS-R022, GQ-R025, GQ-R026, GQ-R027, GQ-R028 | High | `validation/`, `docs/known_issues.md`, `training/stop_conditions.md` | Safe because it defines how to preserve evidence and revert a patch before file-handling changes. | Existing outputs, Git history, campaign JSONs, analysis results. | Before: identify run artifact locations. After: operator can preserve campaign folder and revert to prior commit without deleting evidence. | `stabilize/v9-output-preservation` | `docs: define V9 output preservation procedure` |

## E. Later V10 Or Design Items Out Of Scope For V9 First Patches

| Patch ID | Priority | Workflow | Title | Risk addressed | Severity | Files likely affected | Why this is safe or not safe | What must not change | Required validation before/after | Recommended branch name | Recommended commit message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V9-P3-D01 | P3 | cross-workflow | Replace hard-coded paths and ports with a configuration system | AS-R012, AS-R018, GQ-R006, GQ-R021, dependency-map hard-coded paths | High | `run_campaign.py`, `Dual_Send_Commands.py`, `Analysis_2/Film_Classification_2.py`, config files in both workflows | Not safe as a first V9 patch because configuration migration can change hardware identity and file/model resolution. | Existing lab-machine paths, serial ports, model loading behavior, remote endpoint behavior until tested. | Before: hardware manifest and config schema review. After: lab-machine and clean-machine dry runs resolve identical devices and models. | `design/v10-config-system` | `design: propose Robocoater configuration system` |
| V9-P3-D02 | P3 | cross-workflow | Unify antisolvent and gas-quench command layers | AS-R015, AS-R018, GQ-R019, GQ-R020, GQ-R023 | Critical | `antisolvent_v9/Dual_Send_Commands.py`, `gas_quench_v9/Dual_Send_Commands.py`, possible shared module | Not safe for first stabilization because it can change hardware behavior across both workflows at once. | Pump, relay, spinner, servo, LED, spectroscopy, and shutdown command behavior. | Before: full regression bench suite exists. After: both workflows pass no-chemistry and bench hardware tests. | `design/v10-command-layer` | `design: outline shared command layer` |
| V9-P3-D03 | P3 | cross-workflow | Redesign HOLMES policy, bounds, or adaptive objective | AS-R017, AS-R021, GQ-R024, GQ-R026 | High | `run_campaign.py`, analysis modules, HOLMES client integration | Not safe until data quality and invalid-observation handling are stable. | Existing bounds, normalization, objective/utility, suggest endpoint, campaign log schema. | Before: curated historical dataset and objective review. After: offline replay proves equivalent or intentionally changed behavior. | `design/v10-holmes-policy` | `design: evaluate HOLMES policy updates` |
| V9-P3-D04 | P3 | cross-workflow | Replace classifier/model logic or retrain models | AS-R014, AS-R017, GQ-R022, GQ-R024 | High | `Analysis_2/Film_Classification_2.py`, model files, analysis docs | Not safe as a first patch because it changes utility labels and historical comparability. | Model weights, feature extraction, classification labels, utility calculation. | Before: frozen validation set and expected labels. After: offline model comparison and documented acceptance criteria. | `design/v10-model-validation` | `design: plan model validation update` |
| V9-P3-D05 | P3 | cross-workflow | Build dashboard or operator UI | AS-R023, AS-R024, GQ-R029, GQ-R030 | Medium | New UI files, docs, possible data adapters | Not safe as first stabilization because it can distract from core event logging and failure containment. | Operational code, command behavior, campaign outputs, manual stop procedure. | Before: event logs and status fields exist. After: UI displays existing evidence without becoming the safety authority. | `design/v10-operator-dashboard` | `design: outline operator dashboard requirements` |

## Do Not Patch Yet

The following changes are too risky for first stabilization and should remain out of scope until V9 behavior is measured and reviewed:

- Changing the antisolvent drip compensation value.
- Changing the gas pretrigger value.
- Changing recipe timing.
- Changing pump volumes or pump rates.
- Changing HOLMES bounds, normalization, objective, or policy.
- Changing classifier or model logic.
- Major configuration-system refactor.
- Dashboard or UI work.

## Definition Of Ready For A Code Patch

A V9 code patch is ready only if:

- The risk ID is mapped to the patch.
- The expected behavior is written before implementation.
- Forbidden behavior changes are listed explicitly.
- Dry-run, bench, or no-chemistry validation is defined.
- The rollback plan is obvious from Git branch, commit scope, and preserved artifacts.

## Definition Of Done

A V9 patch is done only if:

- The diff is reviewed.
- No unrelated files changed.
- A minimal test, dry run, or bench validation passes.
- A validation note is added to the relevant documentation or `validation/` record.
- The commit message is specific.
- The pushed branch is reviewed before merge.

## Current Recommendation

The next code branch should be antisolvent-first and narrowly scoped to event traceability or failure propagation. The best first code candidates are:

1. `V9-P1-AS01`: expand antisolvent event trace logging.
2. `V9-P1-AS02`: join and check antisolvent dispense thread status before successful save/analysis.
3. `V9-P1-AS03`: log pump command acknowledgements without changing pump behavior.

Gas-quench code patches should wait until `V9-P0-GQ01` and the relevant validation-only items are complete. Its first implementation should add event logging and pump timeout analysis before any physical campaign.

## Source Documents

- `docs/antisolvent_v9_risk_audit.md`
- `docs/gas_quench_v9_risk_audit.md`
- `docs/antisolvent_v9_architecture.md`
- `docs/gas_quench_v9_architecture.md`
- `docs/repo_architecture_map.md`
- `docs/dependency_map.md`
