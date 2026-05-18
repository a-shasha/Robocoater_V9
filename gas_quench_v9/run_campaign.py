import json
import os
import time

import numpy as np
import requests

from .Perovskite_Recipe_SD import run_Perovskite_Recipe
from .Analysis_2.start_up_folders_2 import create_folders
from . import Dual_Send_Commands as DSC
from . import Dual_Send_OceanFlame as DSO


## User Inputs ##
# Operator action: set the campaign output folder on the lab PC.
file_folder = r"C:\Users\Admin\Desktop\Holmes_Campaign_V9_GQ"
# Operator action: keep a unique base name so GQ runs never mix with antisolvent runs.
baseName = 'Campaign_V9_GQ_'
create_folders(file_folder)
# Operator action: total number of GQ experiments to run in this campaign.
experiment_budget = 45


# --- Hardware Parameters ---
# Operator action: select the in-situ measurement mode.
# 1 = reflection, 2 = PL, 3 = dual reflection + PL.
measType = 3
# Operator action: wait this long after dispense before spin-up starts.
spreadTime = 12
# Operator action: final spin speed used after the 2000 rpm ramp.
rpm = 4000
# Operator action: perovskite dispense volume in uL.
perovVol = 60
# Operator action: keep collecting data this many seconds after the gas quench starts.
timeAfterQuench = 60


# --- Holmes Server Configuration ---
BASE_URL = "http://127.0.0.1:5000/holmes"

# Holmes action-space bounds in real units:
# [Gas Quench Start Time (s), Gas Quench Duration (s)]
# The duration range is aligned to the existing V9 timing-style visualization window.
HOLMES_BOUNDS = [
    [7.0, 70.0],
    [1.0, 14.0],
]

# Fixed BO domain in normalized coordinates for the 2D GQ space.
HOLMES_NORMALIZED_BOUNDS = [
    [0.0, 0.0],
    [1.0, 1.0],
]


# Adaptive BO cadence: 2 exploit (GPEI) then 1 explore (MAXVAR).
EXPLOIT_POLICY = "gpei"
EXPLORE_POLICY = "maxvar"
EXPLORE_EVERY = 3


# Optional drift/noise check: every N adaptive runs, repeat best-so-far action.
# Set to 0 to disable replicate checks.
REPLICATE_EVERY = 5


# Deterministic LHS shuffling for resume-safe campaigns.
LHS_RANDOM_SEED = 42


# Constrained LHS seed for the 2D GQ space.
# Operator action: adjust only if you intentionally want a different warm-start design.
LHS_GQ_TIMES = [7, 12, 19, 27, 33, 39, 45]
LHS_GQ_DURATION_LEVELS = [1.0, 2.5, 4.0, 6.0, 8.0, 11.0, 14.0]


def _campaign_file_path():
    return os.path.join(file_folder, "Campaign_Experiments.json")


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_campaign_dict():
    campaign_file = _campaign_file_path()
    if not os.path.exists(campaign_file):
        return {}
    try:
        with open(campaign_file, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _count_completed_runs():
    return len(_read_campaign_dict())


def _normalize_parameters(params):
    """Map real-valued GQ action [time, duration] into [0,1]^2."""
    norm = []
    for val, (lb, ub) in zip(params, HOLMES_BOUNDS):
        denom = (ub - lb)
        if denom <= 0:
            norm.append(0.0)
        else:
            norm.append((val - lb) / denom)
    return norm


def _denormalize_parameters(norm_params):
    """Map normalized GQ action [0,1]^2 back into real-valued [time, duration]."""
    params = []
    for val, (lb, ub) in zip(norm_params, HOLMES_BOUNDS):
        params.append(lb + val * (ub - lb))
    return params


def constrain_parameters(params):
    """Clip the Holmes suggestion to lab-safe GQ bounds."""
    gq_time, gq_duration = [float(x) for x in params]
    safe_gq_time = max(HOLMES_BOUNDS[0][0], min(gq_time, HOLMES_BOUNDS[0][1]))
    safe_gq_duration = max(HOLMES_BOUNDS[1][0], min(gq_duration, HOLMES_BOUNDS[1][1]))
    constrained = [safe_gq_time, safe_gq_duration]
    if constrained != params:
        print(
            f"WARNING: Holmes suggestion {params} was outside hardware limits. "
            f"Constraining to {constrained}."
        )
    return constrained


def run_experiment(params_list, fileFolder, fileName):
    """Run one complete gas-quench experiment from baseline to wash."""
    safe_params = constrain_parameters(params_list)
    gqTime, gqDuration = safe_params

    print(f"--- Starting GQ Experiment: {fileName} ---")
    print(
        f"Parameters: GQ Time={gqTime:.2f}s, "
        f"GQ Duration={gqDuration:.2f}s"
    )

    # Action 0: resolve the relay port before any wet chemistry begins.
    if float(gqDuration) > 0:
        DSC.resolve_usb_relay_target(DSC.usbRelayPort, DSC.usbRelaySerialNumber)

    # Action 1: clear timing logs from the previous run.
    DSC.init_List()
    # Action 2: clear spectroscopy dictionaries before new baseline collection.
    DSO.create_Dataframes()

    # Action 3: collect the reflection baseline while keeping the spinner ready.
    DSO.reflc_Baseline(rpm, keep_spinner_on=True)
    # Action 4: insert a short source-settle gap before switching to PL baseline.
    time.sleep(0.8)
    # Action 5: collect the PL baseline with the spinner already running.
    DSO.pl_Baseline(rpm, spinner_already_on=True)
    # Action 6: add a short settle before the live deposition sequence begins.
    time.sleep(6)

    # Action 7: define the in-situ runtime relative to the GQ start time.
    runTime = gqTime + timeAfterQuench
    timeStart = time.time()

    # Action 8: execute the full GQ recipe.
    run_Perovskite_Recipe(
        timeStart,
        measType,
        perovVol,
        spreadTime,
        rpm,
        runTime,
        gqTime,
        gqDuration,
        fileFolder,
        fileName,
    )
    print(f"--- GQ Experiment {fileName} Complete ---")


def _build_lhs_seed():
    """Create constrained LHS seed points with deterministic shuffled pairings."""
    if len(LHS_GQ_TIMES) != len(LHS_GQ_DURATION_LEVELS):
        raise ValueError("LHS lists must have identical lengths.")

    rng = np.random.default_rng(LHS_RANDOM_SEED)
    idx_duration = rng.permutation(len(LHS_GQ_TIMES))
    gq_durations = [LHS_GQ_DURATION_LEVELS[i] for i in idx_duration]
    return [[t, d] for t, d in zip(LHS_GQ_TIMES, gq_durations)]


def _campaign_rows_for_holmes():
    """Return Holmes training rows as normalized [time, duration, observation]."""
    campaign_dict = _read_campaign_dict()
    rows = []

    for _, value in campaign_dict.items():
        actions = value.get("Actions", [])
        obs = _as_float(value.get("Observation", None))
        if not (isinstance(actions, list) and len(actions) == 2 and obs is not None):
            continue

        actions_num = [_as_float(x) for x in actions]
        if any(x is None for x in actions_num):
            continue

        actions_safe = constrain_parameters(actions_num)
        actions_norm = _normalize_parameters(actions_safe)
        rows.append(actions_norm + [obs])

    return rows


def _query_holmes_suggestions(rows):
    print("\n--- Querying Holmes Server for GQ suggestions ---")
    if not rows:
        raise ValueError("Cannot query Holmes with no training rows.")

    body = {
        "data_sources": {"_raw": rows},
        "policy_refs": ["{xplt}", "{maxvar}", "{mcei}", "{gpei}"],
        "model_specs": {
            "_uniform_action_dist_from_data": {
                "name": "holmes.distributions.UniformBoxDistribution",
                "params": {"bounds": HOLMES_NORMALIZED_BOUNDS},
            }
        },
    }

    try:
        response = requests.post(BASE_URL + "/basic/suggest", json=body, timeout=90)
        response.raise_for_status()
        res = response.json()
        if "suggestions" not in res:
            raise ValueError(f"Invalid response from Holmes server: {res}")

        suggestion_map = {}
        for item in res["suggestions"]:
            policy_name = str(item.get("policy", "")).lower()
            suggestion = item.get("suggestion", [])
            if isinstance(suggestion, list) and suggestion and isinstance(suggestion[0], list):
                suggestion_map[policy_name] = suggestion[0]

        if EXPLOIT_POLICY not in suggestion_map or EXPLORE_POLICY not in suggestion_map:
            raise ValueError(
                f"Holmes suggestions missing required policies: {suggestion_map.keys()}"
            )

        print(
            f"Holmes {EXPLOIT_POLICY.upper()} (norm): {suggestion_map[EXPLOIT_POLICY]}\n"
            f"Holmes {EXPLORE_POLICY.upper()} (norm): {suggestion_map[EXPLORE_POLICY]}"
        )
        return suggestion_map

    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Holmes server: {e}")
        raise


def _suggest_action(policy_name):
    rows = _campaign_rows_for_holmes()
    suggestion_map = _query_holmes_suggestions(rows)
    norm_suggestion = np.clip(np.array(suggestion_map[policy_name], dtype=float), 0.0, 1.0).tolist()
    real_suggestion = _denormalize_parameters(norm_suggestion)
    return constrain_parameters(real_suggestion)


def _best_action_from_campaign():
    """Return the best-so-far GQ action by max observed utility."""
    campaign_dict = _read_campaign_dict()
    best_action = None
    best_obs = None
    for _, value in campaign_dict.items():
        actions = value.get("Actions", [])
        obs = _as_float(value.get("Observation", None))
        if not (isinstance(actions, list) and len(actions) == 2 and obs is not None):
            continue
        actions_num = [_as_float(x) for x in actions]
        if any(x is None for x in actions_num):
            continue
        if (best_obs is None) or (obs > best_obs):
            best_obs = obs
            best_action = constrain_parameters(actions_num)
    return best_action, best_obs


def _pause_if_needed(completed_runs):
    if completed_runs % 3 == 0 and completed_runs < experiment_budget:
        input("\nCampaign paused for hardware adjustment. Press Enter to continue...")


def main():
    lhs_seed = _build_lhs_seed()
    learning_experiments = len(lhs_seed)
    print(f"GQ LHS seed count: {learning_experiments}")

    try:
        completed = _count_completed_runs()
        if completed > 0:
            print(f"Resuming GQ campaign with {completed} completed runs.")

        # Stage 1: deterministic LHS warm start in the 2D GQ space.
        for i in range(completed, min(learning_experiments, experiment_budget)):
            params = lhs_seed[i]
            fileName = f"{baseName}{i}_LHS"
            run_experiment(params, file_folder, fileName)
            completed = _count_completed_runs()
            _pause_if_needed(completed)

        # Stage 2: adaptive BO with explicit exploit/explore cadence.
        while completed < experiment_budget:
            adaptive_idx = max(0, completed - learning_experiments)

            # Optional periodic replicate for drift/noise awareness.
            if REPLICATE_EVERY > 0 and adaptive_idx > 0 and (adaptive_idx % REPLICATE_EVERY == 0):
                best_action, best_obs = _best_action_from_campaign()
                if best_action is not None:
                    print(
                        f"\n--- Running GQ replicate check at observed best utility={best_obs:.4f} ---"
                    )
                    run_experiment(best_action, file_folder, f"{baseName}{completed}_REPL")
                    completed = _count_completed_runs()
                    _pause_if_needed(completed)
                    if completed >= experiment_budget:
                        break

            adaptive_idx = max(0, completed - learning_experiments)
            use_explore = ((adaptive_idx + 1) % EXPLORE_EVERY == 0)
            policy = EXPLORE_POLICY if use_explore else EXPLOIT_POLICY
            next_action = _suggest_action(policy)
            run_experiment(next_action, file_folder, f"{baseName}{completed}_{policy.upper()}")
            completed = _count_completed_runs()
            _pause_if_needed(completed)

    finally:
        print("\nGQ campaign finished or interrupted. Shutting down hardware.")
        DSC.stopSpinner(time.time())
        DSC.close_Ser()
        if DSO:
            DSO.close_spectrometer()
        print("Hardware shutdown complete.")


if __name__ == "__main__":
    main()
