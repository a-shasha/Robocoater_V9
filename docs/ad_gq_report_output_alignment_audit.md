# AD/GQ Report And Output Alignment Audit

This is a documentation-only audit comparing antisolvent V9 (AD) and gas-quench V9 (GQ) report, JSON, image, campaign-log, and master-utility output logic. No operational code was changed.

Files reviewed:

- `antisolvent_v9/Analysis_SD.py`
- `gas_quench_v9/Analysis_SD.py`
- `antisolvent_v9/New_Visual_test.py`
- `gas_quench_v9/New_Visual_test.py`
- `antisolvent_v9/Save_Data.py`
- `gas_quench_v9/Save_Data.py`
- `antisolvent_v9/Analysis_2/Save_Campaign_Log.py`
- `gas_quench_v9/Analysis_2/Save_Campaign_Log.py`
- `Analysis_2/Film_Classification_2.py` and `Analysis_2/start_up_folders_2.py` in both workflows for image and folder side effects.
- Campaign entry/recipe files only to identify tags, file names, and active call order.

## Executive Summary

AD and GQ share the same broad output model: each sample writes raw JSON, an analyzed JSON copy, a classified film image under `images/`, a summary JPEG report, campaign-level master utility JSON files, and `Campaign_Experiments.json` for HOLMES observations.

The raw spectroscopy payload shape is mostly aligned. Both workflows save `Log`, `Tags`, `Parameters`, wavelengths/energies, reflection products, PL products, and baseline/raw-count products when available.

The main structural differences are workflow parameters: AD is a 3D action space (`Drip Time`, `Drip Rate`, `Drip Volume`), while GQ is a 2D action space (`Gas Quench Time`, `Gas Quench Duration`). Those are legitimate differences.

The main accidental differences are in reporting and campaign-log robustness. AD production plotting delegates to `New_Visual_test.py` and includes the campaign-evolution panel. GQ production plotting still uses an inline report generator in `Analysis_SD.py`, leaves plot 7 blank, and does not use the GQ `New_Visual_test.py` report path during normal campaign analysis. AD campaign logging can fall back to raw JSON and film score; GQ requires analyzed JSON and `Utility['Last Utility Value']`.

Neither workflow has a fully explicit common reporting contract, atomic JSON writes, or structured error/status fields for analysis/report generation. Both write JSON in place and use `Valid` as a boolean without a reason code.

## AD Output Structure

Active campaign folder:

- Root folder: `C:\Users\Admin\Desktop\Holmes_Campaign_V9`.
- Created subfolders from `Analysis_2/start_up_folders_2.py`:
  - `images/`
  - `Snapshots/`
  - `PL Analysis/`
  - `PL Analysis/FWHM Video/`
  - `PL Analysis/Difference Video/`
  - `UVvis Analysis/`
  - `UVvis Analysis/Video/`

Per-sample active outputs:

- `<fileName>.jpg`: raw camera capture, initially written in the campaign root.
- `images/<fileName>_film_*.jpg` or `images/<fileName>_error.jpg`: classified/moved film image.
- `<fileName>.json`: raw experiment JSON from `Save_Data.py`.
- `<fileName>_analyzed.json`: analyzed JSON copy with film ranking, utility, validity, and normalized/actual parameters.
- `<fileName>_Analyzed.jpeg`: active production visual report generated through `Analysis_SD.py` delegating to `New_Visual_test.py`.

Campaign-level active outputs:

- `Campaign_Experiments.json`
- `MasterUtility.json`
- `TimePoints_MasterUtility.json`
- `NormParameters_MasterUtility.json`
- `Observations_MasterUtility.json`
- `Valid_MasterUtility.json`
- `Operation_Event_Log.csv` exists in AD command/event logging and is not currently mirrored in GQ.

Manual or legacy report outputs:

- Manual `New_Visual_test.py` defaults to `New_Visual_test_output/` or an absolute manual output folder when run directly.
- Manual `New_Visual_test.py` can write `campaign_surface_step_XX.png` frames.
- Legacy `Analysis_2/Plot_Data_2.py` writes to `Snapshots/<fileName>_Analyzed.jpeg`, but this is not the active `Analysis_SD.py` production path.

AD raw JSON fields from `Save_Data.py`:

- `Log`
- `Tags`
- `Parameters`
  - `Drip Time`
  - `Drip Rate`
  - `Drip Volume`
- `Wavelengths`
- `Energies`
- `Reflection`
- `Absorbance`
- `Reflection Spectral Count`
- `Reflection Baseline`
- `PL Measurement`
- `PL Spectral Count`
- `PL Baseline`

AD tag fields from the recipe:

- `Experiment Name`
- `RPM`
- `Spin Time`
- `Perovskite Volume`
- `Anti-Solvent Rate`
- `Anti-Solvent Volume`
- `Anti-Solvent Drip Time`
- `Measurement`

AD analyzed JSON fields added or overwritten:

- `Film Ranking`
  - `Score`
  - `Rank`
  - `Rank Name`
  - `Image Name`
- `Valid`
- `Utility`
  - `Utility Components`
  - `Utility over time`
  - `Last Utility Value`
  - `Max Utility Value`
  - `Film Score`
- `Parameters`
  - `Normalized parameters`
  - `Actual parameters`

## GQ Output Structure

Active campaign folder:

- Root folder: `C:\Users\Admin\Desktop\Holmes_Campaign_V9_GQ`.
- Created subfolders match AD:
  - `images/`
  - `Snapshots/`
  - `PL Analysis/`
  - `PL Analysis/FWHM Video/`
  - `PL Analysis/Difference Video/`
  - `UVvis Analysis/`
  - `UVvis Analysis/Video/`

Per-sample active outputs:

- `<fileName>.jpg`: raw camera capture, initially written in the campaign root.
- `images/<fileName>_film_*.jpg` or `images/<fileName>_error.jpg`: classified/moved film image.
- `<fileName>.json`: raw experiment JSON from `Save_Data.py`.
- `<fileName>_analyzed.json`: analyzed JSON copy with film ranking, utility, validity, and normalized/actual parameters.
- `<fileName>_Analyzed.jpeg`: active production visual report generated by inline plotting code in `gas_quench_v9/Analysis_SD.py`.

Campaign-level active outputs:

- `Campaign_Experiments.json`
- `MasterUtility.json`
- `TimePoints_MasterUtility.json`
- `NormParameters_MasterUtility.json`
- `Observations_MasterUtility.json`
- `Valid_MasterUtility.json`

Manual or legacy report outputs:

- Manual `New_Visual_test.py` defaults to `New_Visual_GQ_output/` or an absolute manual output folder when run directly.
- Manual `New_Visual_test.py` can write `campaign_surface_step_XX.png` frames.
- Legacy `Analysis_2/Plot_Data_2.py` writes to `Snapshots/<fileName>_Analyzed.jpeg`, but this is not the active `Analysis_SD.py` production path.
- `Spectroscopy_Calibration.py` has calibration-specific CSV/JPEG outputs, separate from campaign report generation.

GQ raw JSON fields from `Save_Data.py`:

- `Log`
- `Tags`
- `Parameters`
  - `Gas Quench Time`
  - `Gas Quench Duration`
  - `Parameter Names`
- `Wavelengths`
- `Energies`
- `Reflection`
- `Absorbance`
- `Reflection Spectral Count`
- `Reflection Baseline`
- `PL Measurement`
- `PL Spectral Count`
- `PL Baseline`

GQ tag fields from the recipe:

- `Experiment Name`
- `Process Mode`
- `RPM`
- `Spin Time`
- `Perovskite Volume`
- `Gas Quench Start Time`
- `Gas Quench Duration`
- `Measurement`

GQ analyzed JSON fields added or overwritten:

- `Film Ranking`
  - `Score`
  - `Rank`
  - `Rank Name`
  - `Image Name`
- `Valid`
- `Utility`
  - `Utility Components`
  - `Utility over time`
  - `Last Utility Value`
  - `Max Utility Value`
  - `Film Score`
- `Parameters`
  - `Parameter Names`
  - `Normalized parameters`
  - `Actual parameters`

## Side-By-Side Comparison

| Area | AD | GQ | Alignment |
| --- | --- | --- | --- |
| Active root folder | `Holmes_Campaign_V9` | `Holmes_Campaign_V9_GQ` | Legitimately separate to avoid output mixing. |
| Base file names | `Campaign_V9_...` | `Campaign_V9_GQ_...` | Legitimately separate. |
| Startup subfolders | Same `images`, `Snapshots`, `PL Analysis`, `UVvis Analysis` tree | Same tree | Aligned, but `Snapshots` appears legacy for active `Analysis_SD.py`. |
| Raw JSON filename | `<fileName>.json` | `<fileName>.json` | Aligned. |
| Analyzed JSON filename | `<fileName>_analyzed.json` | `<fileName>_analyzed.json` | Aligned. |
| Report JPEG filename | `<fileName>_Analyzed.jpeg` | `<fileName>_Analyzed.jpeg` | Aligned filename, not aligned generation path/content. |
| Film image storage | `images/<fileName>_film_*.jpg` | Same | Aligned. |
| Raw process parameters | `Drip Time`, `Drip Rate`, `Drip Volume` | `Gas Quench Time`, `Gas Quench Duration`, `Parameter Names` | Legitimate dimensional difference; `Parameter Names` consistency is not aligned. |
| Tag block | AD-specific antisolvent tags, no `Process Mode` | GQ-specific gas tags, includes `Process Mode` | Mostly legitimate; `Process Mode` could be common. |
| Utility block | Same keys | Same keys | Aligned. |
| Validity block | `Valid` boolean only | `Valid` boolean only | Aligned but weak. No reason/status fields. |
| Master utility files | Same five files | Same five files | Aligned. |
| Master `Parameters` block | `Normalized parameters`, `Actual parameters` | Adds `Parameter Names` too | Inconsistent but useful in GQ. |
| Campaign log entry | `Observation`, `Actions` | `Observation`, `Actions`, `Parameter Names` | Inconsistent. |
| Campaign log robustness | Can read analyzed or raw JSON; falls back to film score or `0.0` observation | Requires analyzed JSON and `Utility['Last Utility Value']` | Inconsistent; AD is more tolerant. |
| Production plot generator | Delegates to `New_Visual_test.py` | Inline plotting in `Analysis_SD.py` | Inconsistent. |
| Production report plot 7 | Campaign evolution map | Blank/off in inline report | Inconsistent. |
| Manual `New_Visual_test.py` | AD-aware alt report and campaign map | GQ-aware alt report and campaign map | Similar manual structure, but GQ manual path is not used by production analysis. |
| Event marker on contours | Drip start and drip end lines | GQ inline has limited/older event-line behavior; GQ manual visual has GQ start line | Partly legitimate, partly inconsistent between active and manual GQ report paths. |
| Time-axis semantics | AD New Visual uses relative time from drip in selected traces | GQ inline report mostly uses absolute seconds; GQ manual visual still uses legacy `drip_*` internal names for GQ axes | Inconsistent terminology and active report behavior. |

## Required Common Reporting Contract

A later reporting patch should define an explicit shared contract for both workflows before changing code:

- Raw JSON must always contain:
  - `Log`
  - `Tags`
  - `Parameters`
  - `Wavelengths`
  - `Energies`
  - optional reflection and PL data products by measurement mode.
- Analyzed JSON must always contain:
  - `Film Ranking`
  - `Valid`
  - `Validity Reason` or `Analysis Status` in a future patch
  - `Utility`
  - `Parameters`
    - `Parameter Names`
    - `Actual parameters`
    - `Normalized parameters`
- Campaign log entries should always contain:
  - `Observation`
  - `Actions`
  - `Parameter Names`
  - optional `Valid`
  - optional `Source JSON`
  - optional `Observation Source`.
- Master utility files should remain:
  - `MasterUtility.json`
  - `TimePoints_MasterUtility.json`
  - `NormParameters_MasterUtility.json`
  - `Observations_MasterUtility.json`
  - `Valid_MasterUtility.json`
- Report JPEG naming should remain `<fileName>_Analyzed.jpeg`.
- Classified images should remain under `images/`, with overwrite/recovery behavior fixed later.
- Production and manual report generation should use the same rendering path per workflow.

## Legitimate AD/GQ Differences

- AD has three action dimensions: drip time, drip rate, drip volume.
- GQ has two action dimensions: gas-quench start time and gas-quench duration.
- AD can compute drip duration from volume/rate; GQ directly receives gas pulse duration.
- AD report annotations should refer to drip start/end; GQ report annotations should refer to gas start/end.
- AD BO surfaces should map drip time versus drip duration or a documented AD projection; GQ BO surfaces should map GQ time versus GQ duration.
- AD and GQ should keep separate campaign root folders and filename prefixes.
- GQ tags should retain gas-specific fields; AD tags should retain antisolvent-specific fields.

## Inconsistencies To Fix Later

1. GQ production report does not delegate to `gas_quench_v9/New_Visual_test.py`, while AD production report delegates to `antisolvent_v9/New_Visual_test.py`.
2. GQ production report leaves plot 7 blank; AD production report uses the campaign evolution map.
3. GQ manual `New_Visual_test.py` still uses legacy internal names such as `drip_time` and `drip_duration` to represent GQ time/duration.
4. AD raw `Parameters` lacks `Parameter Names`, while GQ raw `Parameters` includes it.
5. AD analyzed `Parameters` lacks `Parameter Names`, while GQ analyzed `Parameters` includes it.
6. AD campaign log lacks `Parameter Names`, while GQ campaign log includes it.
7. AD campaign logging tolerates missing analyzed JSON and utility fields; GQ campaign logging is strict and can fail if analyzed output is absent or incomplete.
8. Both workflows have only `Valid` boolean and no structured invalid reason, analysis status, report status, or classifier status.
9. Both workflows write raw/analyzed/master/campaign JSON files directly, without temp-file plus atomic replace.
10. Both workflows can overwrite classified image destinations during classification.
11. Startup creates `Snapshots/`, but active `Analysis_SD.py` writes report JPEGs in the root campaign folder. `Snapshots/` appears legacy unless old `Analysis_2/Plot_Data_2.py` is used.
12. GQ calibration outputs are separate and not represented in the normal campaign output contract.

## Recommended Safe Patch Sequence

1. Documentation-only: approve this common reporting contract and decide whether `Parameter Names` should become required everywhere.
2. AD/GQ metadata-only patch: add `Parameter Names` consistently to AD raw/analyzed JSON and AD campaign log, without changing action values or HOLMES behavior.
3. GQ report alignment patch: make GQ production report use the GQ `New_Visual_test.py` renderer, matching the AD production pattern, after visual comparison with existing GQ reports.
4. GQ terminology patch: rename internal GQ manual-report variables/documentation away from `drip_*` aliases only after report-output equivalence is validated.
5. Campaign-log robustness patch: give GQ the same controlled fallback behavior as AD, or make both workflows strict, but do not change HOLMES observation policy without explicit review.
6. Status fields patch: add `Analysis Status`, `Classifier Status`, `Report Status`, and invalid reason fields to analyzed JSON and campaign logs.
7. Data-integrity patch: introduce atomic JSON writes for raw, analyzed, master, and campaign files.
8. Output-collision patch: refuse or quarantine overwrite-prone report/image outputs unless an operator selects recovery mode.

## Confirmation

This audit is documentation-only. No operational Python code, report generation code, analysis code, JSON schema, or HOLMES logic was edited.
