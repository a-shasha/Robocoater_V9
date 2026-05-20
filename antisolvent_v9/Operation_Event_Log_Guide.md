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

7. Antisolvent prep join duration
`prep_join_duration_s = t(antisolvent_prep_join_end) - t(antisolvent_prep_join_start)`

8. Compensated pre-drip wait target
Use `computed_pre_drip_wait_s` in the details column for `antisolvent_pre_drip_wait_start` and `antisolvent_pre_drip_wait_end`.

9. Alignment with external HC sensor CSV
Join/align records using `wall_time_local_mmddyyyy_hhmmss_ms` (same PC clock basis).

## Added Antisolvent Trace Events

Prep lifecycle:
- `antisolvent_prep_thread_scheduled`: antisolvent prep thread was created and scheduled. This is prep only, not the commanded substrate drip.
- `antisolvent_prep_join_start`: recipe is about to wait for prep completion before compensated drip timing.
- `antisolvent_prep_join_end`: prep wait has returned and the compensated pre-drip wait can be calculated.

Compensated drip timing:
- `antisolvent_pre_drip_wait_start`: includes requested drip time, requested volume/rate, `drip_edge_compensation_s`, and `computed_pre_drip_wait_s`.
- `antisolvent_pre_drip_wait_end`: same fields at the end of the software wait.

Dispense thread:
- `antisolvent_dispense_thread_scheduled`: thread object was created for the final antisolvent dispense.
- `antisolvent_dispense_thread_start_call_returned`: `Thread.start()` returned. This row is logged after the start call so it does not add another pre-start logging delay.
- `antisolvent_dispense_thread_started`: records whether the thread is alive immediately after the start call.

Pump command responses:
- `antisolvent_prep_command_responses`: raw pump responses for prep `DIR INF`, `VOL UL`/`VOL ML`, `VOL`, and `RUN`.
- `antisolvent_dispense_command_responses`: raw pump responses for final dispense `DIR INF`, `VOL UL`/`VOL ML`, `VOL`, and `RUN`.
- `perovskite_prep_command_responses`, `perovskite_dispense_command_responses`, and `perovskite_withdraw_command_responses`: matching response rows for perovskite pump operations that share the same command helpers.

## Warning Signs
- Command sent late by `> 0.5 s`: `delay_s > 0.5`
- Thread latency `> 0.2 s`: `thread_latency_s > 0.2`
- Pump duration error `> 0.5 s`: `abs(pump_duration_error_s) > 0.5`
- Prep join returns after the requested drip time: `t(antisolvent_prep_join_end) > requested_drip_time_s`
- Missing command response rows for an operation that has a corresponding command-sent row.
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
- `antisolvent_prep_join_end`
- `antisolvent_pre_drip_wait_start`
- `antisolvent_pre_drip_wait_end`
- `antisolvent_dispense_thread_start_call_returned`
- `antisolvent_dispense_command_sent`
- `antisolvent_dispense_wait_end`
- `wash_start`
- `wash_end`
- `sample_end`
