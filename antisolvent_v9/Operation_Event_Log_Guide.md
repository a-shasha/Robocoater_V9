# Operation Event Log Guide (V9)

Use `Operation_Event_Log.csv` to evaluate timing behavior **per sample** (`sample_id` / `file_name`).

## Core Columns
- `event_name`: operation marker.
- `elapsed_from_sample_start_s`: monotonic elapsed time from `sample_start`.
- `requested_drip_time_s`, `requested_rate_ml_min`, `requested_volume_ul`: requested antisolvent settings.
- `wall_time_local_mmddyyyy_hhmmss_ms`: local wall-clock with milliseconds for cross-system alignment.

## Calculation Formulas
For each sample, pull the event row times from `elapsed_from_sample_start_s` unless noted.

1. Requested vs software antisolvent command delay  
`delay_s = t(antisolvent_dispense_command_sent) - requested_drip_time_s`

2. Pre-drip wait accuracy  
`pre_drip_wait_s = t(antisolvent_pre_drip_wait_end) - t(antisolvent_pre_drip_wait_start)`

3. Thread scheduling latency  
`thread_latency_s = t(antisolvent_dispense_command_sent) - t(antisolvent_dispense_thread_scheduled)`

4. Antisolvent pump duration  
`actual_pump_duration_s = t(antisolvent_dispense_wait_end) - t(antisolvent_dispense_wait_start)`

5. Expected pump duration  
`expected_pump_duration_s = requested_volume_ul / (requested_rate_ml_min * 1000 / 60)`

6. Pump duration error  
`pump_duration_error_s = actual_pump_duration_s - expected_pump_duration_s`

7. Alignment with external HC sensor CSV  
Join/align records using `wall_time_local_mmddyyyy_hhmmss_ms` (same PC clock basis).

## Warning Signs
- Command sent late by `> 0.5 s`: `delay_s > 0.5`
- Thread latency `> 0.2 s`: `thread_latency_s > 0.2`
- Pump duration error `> 0.5 s`: `abs(pump_duration_error_s) > 0.5`
- Missing wait end: `antisolvent_dispense_wait_start` exists but `antisolvent_dispense_wait_end` missing
- Exception before normal completion: `sample_exception` present before `sample_end`
- Wall-clock discontinuity: non-monotonic or large unexpected jumps in `wall_time_local_mmddyyyy_hhmmss_ms` within one sample

## Practical Interpretation Notes
- Positive `delay_s` means software issued drip later than requested.
- Large `thread_latency_s` indicates scheduling/contention delay before command dispatch.
- Large positive pump duration error suggests slower-than-expected delivery; large negative suggests faster/shorter execution or mismatch in requested metadata vs real command path.

## HC Sensor Alignment Note

Do not expect exact timestamp equality between `Operation_Event_Log.csv` and the HC sensor CSV.

Use nearest-neighbor timestamp alignment:
- Convert both timestamp columns to datetime.
- For each RoboCoater event, find the nearest HC sensor timestamp.
- Start with tolerance = ±1.0 s.
- Tighten to ±0.5 s if both systems are stable.
- If no HC record exists within tolerance, mark the event as unmatched.

Recommended anchor events:
- `sample_start`
- `antisolvent_dispense_command_sent`
- `antisolvent_dispense_wait_end`
- `wash_start`
- `wash_end`
- `sample_end`