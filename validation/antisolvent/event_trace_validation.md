# Antisolvent Event Trace Validation

Purpose: validate V9-P1-AS01 event-trace additions without changing chemistry, recipe timing, pump commands, spin profile, HOLMES behavior, or classifier/model behavior.

## No-Chemistry Dry Run

Run an antisolvent V9 no-chemistry dry run using the normal campaign path and preserve the full campaign output folder.

Verify `Operation_Event_Log.csv` contains these event groups in the expected order for an antisolvent sample:

1. `antisolvent_prep_thread_scheduled`
2. `antisolvent_prep_command_sent`
3. `antisolvent_prep_command_responses`
4. `antisolvent_prep_wait_start`
5. `antisolvent_prep_wait_end`
6. `requested_antisolvent_drip_time`
7. `antisolvent_prep_join_start`
8. `antisolvent_prep_join_end`
9. `antisolvent_pre_drip_wait_start`
10. `antisolvent_pre_drip_wait_end`
11. `antisolvent_dispense_thread_scheduled`
12. `antisolvent_dispense_thread_start_call_returned`
13. `antisolvent_dispense_thread_started`
14. `antisolvent_dispense_command_sent`
15. `antisolvent_dispense_command_responses`
16. `antisolvent_dispense_wait_start`
17. `antisolvent_dispense_wait_end`

## Field Checks

For the prep and dispense rows, confirm the `details` column includes:

- `pump_number`
- `prep_volume_ul` for prep lifecycle rows
- `requested_drip_time_s`
- `requested_volume_ul`
- `requested_rate_ml_min`
- `drip_edge_compensation_s`
- `computed_pre_drip_wait_s`
- raw responses for `DIR INF`, `VOL UL` or `VOL ML`, `VOL`, and `RUN`

## Behavior Checks

Confirm by diff review and dry-run observation:

- `antisolventDripEdgeCompensationS` is unchanged.
- `dripTime`, `dripRate`, and `dripVol` behavior is unchanged.
- Pump volume and rate commands are unchanged.
- Spin profile is unchanged.
- HOLMES and classifier/model behavior are unchanged.
- Gas-quench code is untouched.

## Reconstruction Check

Compare these rows by `elapsed_from_sample_start_s`:

- requested drip time from `requested_antisolvent_drip_time`
- prep completion from `antisolvent_prep_join_end`
- compensated wait start and end from `antisolvent_pre_drip_wait_start` and `antisolvent_pre_drip_wait_end`
- final dispense scheduling from `antisolvent_dispense_thread_scheduled`
- pump command dispatch from `antisolvent_dispense_command_sent`
- pump completion from `antisolvent_dispense_wait_end`

Use wall-clock columns only for alignment with external HC sensor CSV timestamps.
