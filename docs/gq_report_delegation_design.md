# GQ Production Report Delegation Design

This is a documentation-only implementation design. It describes how to make Gas Quench V9 production report generation follow the same delegation pattern currently used by Antisolvent V9, without changing code in this branch.

## Executive Summary

Antisolvent V9 is the current target standard for production reports. `antisolvent_v9/Analysis_SD.py` does not render the production report inline. Instead, it loads `antisolvent_v9/New_Visual_test.py`, builds the campaign-history context, and delegates final report rendering to `NVT._generate_plots_new(...)`.

Gas Quench V9 should follow the same production pattern using `gas_quench_v9/New_Visual_test.py`. The GQ visual module already exposes the functions and constants needed by the AD handoff pattern. The smallest safe later code patch is therefore limited to `gas_quench_v9/Analysis_SD.py`: add the AD-style `_load_new_visual_module()` helper and replace the current inline `_generate_plots(...)` body with a GQ-adapted delegation body.

The patch must preserve GQ-specific parameter names and annotations: `Gas Quench Start Time`, `Gas Quench Duration`, `Gas Quench Time`, `gqTime`, `gqDuration`, GQ time/duration BO ranges, and gas-quench start/duration labels in report titles. It must not change utility calculation, JSON schema, HOLMES behavior, classifier/model logic, or raw/analyzed output names.

## AD Production Report Handoff Pattern

`antisolvent_v9/Analysis_SD.py` uses two pieces:

1. `_load_new_visual_module()`
   - First tries `from . import New_Visual_test as NVT`.
   - Then tries `import New_Visual_test as NVT`.
   - Then loads sibling `New_Visual_test.py` by file path with `importlib.util.spec_from_file_location(...)`.
   - Raises an `ImportError` containing all attempted import failures if all paths fail.

2. `_generate_plots(master_dict, results, file_folder, file_name)`
   - Returns immediately if `results` is missing or does not contain `utility_value`.
   - Loads `New_Visual_test.py` as `NVT`.
   - Builds `all_points` from `Campaign_Experiments.json` when `NVT.BO_USE_CAMPAIGN_EXPERIMENTS` is true.
   - Falls back to campaign JSON files via `NVT._resolve_inputs(...)`, `NVT._get_file_name_base(...)`, `NVT._prepare_master_dict(...)`, and `NVT._extract_campaign_point(...)`.
   - Extracts the current sample point from the current `master_dict` and inserts or replaces it in `all_points` before `Campaign_Experiments.json` is updated.
   - Sorts points with `NVT._sample_sort_key(...)`.
   - Computes:
     - `total_steps = len(all_points)`
     - `objective_limits = NVT._objective_limits_from_points(all_points, objective_mode=NVT.BO_OBJECTIVE_MODE)`
     - `history_points` up to and including the current `file_name`
     - `step_idx = len(history_points)`
     - `bo_state = {"kernel_cache": {}, "prev_surface": None}`
   - Calls `NVT._generate_plots_new(...)`.

AD passes these exact inputs to `NVT._generate_plots_new(...)`:

- `master_dict=master_dict`
- `results=results`
- `output_folder=file_folder`
- `source_folder=file_folder`
- `file_name=file_name`
- `history_points=history_points`
- `all_points=all_points`
- `step_idx=step_idx`
- `total_steps=total_steps`
- `objective_limits=objective_limits`
- `bo_strategy=NVT.BO_SURROGATE_STRATEGY`
- `objective_mode=NVT.BO_OBJECTIVE_MODE`
- `bo_state=bo_state`

This makes the active production report match the manual `New_Visual_test.py` renderer and keeps the campaign-evolution panel in the normal campaign output.

## Current GQ Inline Production Report Pattern

`gas_quench_v9/Analysis_SD.py` currently renders its production report inline inside `_generate_plots(...)`.

Current behavior:

- Creates a `12 x 6` inch, `4 x 4` grid report directly in `Analysis_SD.py`.
- Builds local helper functions for nearest targets, event-anchored targets, finite arrays, and smoothing.
- Uses `gqTime` and `gqDuration` from `results` or `Tags`.
- Generates PL selected-time lines, PL contour, peak energy, peak area, reflection selected-time lines, reflection contour, PLQY/reflection-style middle panels, film image, and report title.
- Writes `<file_name>_Analyzed.jpeg` directly in the campaign folder.
- Leaves plot 7 off/blank with a comment that utility-over-time was removed.

Current risk:

- GQ production report does not use `gas_quench_v9/New_Visual_test.py`.
- GQ manual report and GQ production report can diverge.
- GQ production report does not include the campaign-evolution map even though the GQ visual module already has `_plot_campaign_evolution(...)` and `_generate_plots_new(...)`.
- Some GQ visual module internals still use legacy generic names like `drip_time` and `drip_duration` to represent GQ time and duration, but the external title/labels are already GQ-specific.

## Required GQ Target Pattern

The target pattern is AD-compatible delegation with GQ-specific module and labels:

1. Add a GQ version of `_load_new_visual_module()` to `gas_quench_v9/Analysis_SD.py`.
2. Import `importlib.util` in `gas_quench_v9/Analysis_SD.py` if needed for the file-path fallback.
3. Replace the inline body of `gas_quench_v9/Analysis_SD.py::_generate_plots(...)` with the same orchestration used by AD, but loading `gas_quench_v9/New_Visual_test.py`.
4. Keep output arguments:
   - `output_folder=file_folder`
   - `source_folder=file_folder`
   - `file_name=file_name`
5. Use GQ module constants:
   - `NVT.BO_USE_CAMPAIGN_EXPERIMENTS`
   - `NVT.BO_OBJECTIVE_MODE`
   - `NVT.BO_SURROGATE_STRATEGY`
6. Use GQ module helpers:
   - `NVT._load_points_from_campaign_experiments(...)`
   - `NVT._resolve_inputs(...)`
   - `NVT._get_file_name_base(...)`
   - `NVT._prepare_master_dict(...)`
   - `NVT._extract_campaign_point(...)`
   - `NVT._sample_sort_key(...)`
   - `NVT._objective_limits_from_points(...)`
   - `NVT._generate_plots_new(...)`
7. Preserve the current production output file name by allowing `New_Visual_test.py` to write `<file_name>_Analyzed.jpeg` into `file_folder`.

## Compatibility Checklist

GQ `New_Visual_test.py` already exposes the main functions AD requires:

| Required by AD handoff | Present in GQ `New_Visual_test.py` | Notes |
| --- | --- | --- |
| `BO_USE_CAMPAIGN_EXPERIMENTS` | Yes | Used to prefer campaign log points. |
| `BO_OBJECTIVE_MODE` | Yes | Defaults to `observation`. |
| `BO_SURROGATE_STRATEGY` | Yes | Defaults to `auto`. |
| `_load_points_from_campaign_experiments(campaign_folder)` | Yes | Reads 2D `Actions` as GQ time/duration. |
| `_resolve_inputs(campaign_folder, inputs)` | Yes | Resolves raw/analyzed JSON files. |
| `_get_file_name_base(json_path)` | Yes | Removes `_analyzed` suffix. |
| `_prepare_master_dict(json_path)` | Yes | Loads JSON. |
| `_extract_campaign_point(master_dict, file_name)` | Yes | Extracts GQ time/duration from tags/params. |
| `_sample_sort_key(name)` | Yes | Orders campaign samples. |
| `_objective_limits_from_points(points, objective_mode)` | Yes | Computes BO color/value limits. |
| `_generate_plots_new(...)` | Yes | Accepts the same signature as AD. |
| `_plot_campaign_evolution(...)` | Yes | Used by `_generate_plots_new` for plot 7. |

Known compatibility issues to account for:

- `gas_quench_v9/Analysis_SD.py` currently does not import `importlib.util`; the AD-style loader requires it.
- `gas_quench_v9/Analysis_SD.py` currently has no `_load_new_visual_module()` helper.
- GQ `New_Visual_test.py` uses legacy internal point keys `drip_time` and `drip_duration` for GQ BO x/y values. This is compatible with its own plotting helpers but should be documented and not renamed in the first patch.
- GQ `New_Visual_test.py::_generate_plots_new(...)` uses `gq_time` and `gq_duration` for report title and event lines, preserving GQ-facing labels.
- GQ `New_Visual_test.py::_generate_plots_new(...)` currently labels selected-time legends as `Times` rather than relative gas-time labels. That is acceptable for the smallest delegation patch, but report visual equivalence should be checked.

## GQ-Specific Names To Preserve

Do not rename or reinterpret these in the first patch:

- `Gas Quench Start Time`
- `Gas Quench Duration`
- `Gas Quench Time`
- `gqTime`
- `gqDuration`
- `GQ Time`
- `GQ Duration`
- `BO_X_RANGE = (7.0, 70.0)` for gas-quench start time
- `BO_Y_RANGE = (1.0, 14.0)` for gas-quench duration
- GQ campaign prefix `Campaign_V9_GQ_`
- GQ campaign folder `Holmes_Campaign_V9_GQ`

Also preserve GQ semantic annotations:

- Gas-quench start line on PL/reflection contour panels.
- Gas-quench duration in the report title.
- GQ campaign-evolution map axes as gas-quench time versus gas-quench duration, even if internal helper keys are still named `drip_time` and `drip_duration`.

## AD Layout Elements To Mirror In GQ

The GQ target should mirror the AD production layout pattern, not AD chemistry semantics:

- Same `4 x 4` report grid.
- Same top title/header pattern with file name, process parameters, film rank, and utility.
- Plot 1: PL at selected event-anchored times.
- Plot 2: PL contour with process-event marker.
- Plot 3a: peak energy trace.
- Plot 3b: PL peak area trace.
- Plot 4: reflection at selected event-anchored times.
- Plot 5: reflection contour with process-event marker.
- Middle-lower stack: reflection-vs-time traces at configured wavelengths.
- Plot 7: campaign evolution map using BO surrogate/observations.
- Plot 8: classified film image.
- Output filename: `<file_name>_Analyzed.jpeg`.

GQ should mirror layout mechanics, campaign-evolution behavior, and visual report ownership. It should not copy AD labels such as `Drip Time`, `Time from Drip`, or antisolvent duration wording.

## Plot 7 And Campaign-Evolution Logic

GQ should use its existing `gas_quench_v9/New_Visual_test.py::_plot_campaign_evolution(...)` through `_generate_plots_new(...)`.

Point source order should match AD:

1. Load `Campaign_Experiments.json` when `BO_USE_CAMPAIGN_EXPERIMENTS` is true.
2. If that fails or returns no points, derive points from campaign JSON files.
3. Insert or replace the current experiment point from the in-memory `master_dict`, because `Campaign_Experiments.json` is updated after plotting.
4. Sort all points with `_sample_sort_key`.
5. Set `history_points` to points with sort key up to current `file_name`.
6. Set `step_idx = len(history_points)`.
7. Set `total_steps = len(all_points)`.
8. Compute `objective_limits` from all points.
9. Pass `bo_state = {"kernel_cache": {}, "prev_surface": None}` into `_generate_plots_new(...)`.

The GQ campaign-evolution map should represent:

- x-axis: gas-quench start time
- y-axis: gas-quench duration
- color/objective: `Observation` by default, matching `BO_OBJECTIVE_MODE = "observation"`
- marker/rank behavior: current `New_Visual_test.py` rank pin logic

## Smallest Safe Implementation Patch

Smallest safe patch after this design:

1. Edit only `gas_quench_v9/Analysis_SD.py`.
2. Add `import importlib.util`.
3. Add AD-style `_load_new_visual_module()` adapted only in fallback module name, for example `_self_driving_v9_gq_new_visual_test`.
4. Replace only `_generate_plots(...)` with the AD-style delegation body.
5. Keep `analyze_Data(...)`, `_calculate_utility_metrics(...)`, `_save_master_files(...)`, and all JSON/utility/campaign logic unchanged.
6. Do not edit `gas_quench_v9/New_Visual_test.py` in the first implementation patch unless validation shows a blocking incompatibility.

Likely changed files:

- `gas_quench_v9/Analysis_SD.py`
- Optional validation note under `validation/gas_quench/`
- Optional documentation update under `docs/`

Files that should not change in the first implementation patch:

- `gas_quench_v9/New_Visual_test.py`
- `gas_quench_v9/Save_Data.py`
- `gas_quench_v9/Analysis_2/Save_Campaign_Log.py`
- `gas_quench_v9/Analysis_2/Film_Classification_2.py`
- `gas_quench_v9/run_campaign.py`
- Any `antisolvent_v9/` file
- Any HOLMES client or campaign policy logic

## Validation Checklist

Use existing GQ sample outputs if available. If no safe existing output folder is available, copy a small representative GQ campaign folder to a disposable validation location before running report generation.

Pre-patch baseline:

- Identify at least one GQ sample with:
  - `<fileName>.json`
  - `<fileName>_analyzed.json`
  - `images/<classified image>`
  - `Campaign_Experiments.json` if available
- Preserve the current `<fileName>_Analyzed.jpeg` as a baseline image.
- Record the current file list and modified times.

After implementation:

- Run the GQ analysis/report path on copied existing GQ outputs, not live campaign data.
- Confirm `<fileName>_Analyzed.jpeg` is generated in the same campaign folder.
- Confirm no JSON files changed except any expected report-generation side effects. The target patch should not alter JSON.
- Confirm plot 7 is populated with the GQ campaign-evolution map when enough campaign points exist.
- Confirm title uses `GQ Time` and `GQ Duration`.
- Confirm report event markers use gas-quench time, not antisolvent drip labels.
- Confirm classified film image still resolves from `images/<Image Name>`.
- Compare dimensions and readability against AD target report style.
- Confirm `git diff --check` passes.
- Confirm no `antisolvent_v9/` files changed.

Optional visual comparison:

- Run `gas_quench_v9/New_Visual_test.py` manually on the same copied sample.
- Compare manual output and production output for equivalent panels, labels, and plot 7 behavior.

## Explicit Non-Goals

This design does not approve:

- Changing utility calculation.
- Changing JSON schema.
- Changing `Campaign_Experiments.json` structure.
- Changing HOLMES actions, observations, bounds, or policy.
- Changing classifier/model logic.
- Changing report data selection windows.
- Changing gas-quench timing, relay control, pump commands, spin profile, or recipe behavior.
- Renaming GQ `New_Visual_test.py` internal `drip_time` and `drip_duration` point keys.
- Refactoring shared AD/GQ report code.
- Updating dashboard/UI behavior.
- Merging the open AD event-trace PR or report-output audit branch.

## Confirmation

No code was changed for this design. This branch contains documentation only.
