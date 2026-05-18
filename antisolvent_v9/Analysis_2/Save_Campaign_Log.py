import json
import os


def _as_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _parse_rate_mL_min(rate_value):
    if isinstance(rate_value, str):
        rate_value = rate_value.replace("MM", "").strip()
    return _as_float(rate_value)


def _extract_actions(master_dict):
    params = master_dict.get("Parameters", {})
    tags = master_dict.get("Tags", {})

    # Preferred analyzed payload format.
    actual_params = params.get("Actual parameters")
    if isinstance(actual_params, list) and len(actual_params) >= 3:
        drip_time = _as_float(actual_params[0])
        drip_rate = _as_float(actual_params[1])
        drip_vol = _as_float(actual_params[2])
        if None not in (drip_time, drip_rate, drip_vol):
            return [drip_time, drip_rate, drip_vol]

    # Raw saved-json format from Save_Data.py.
    drip_time = _as_float(params.get("Drip Time"))
    drip_rate = _as_float(params.get("Drip Rate"))
    drip_vol = _as_float(params.get("Drip Volume"))
    if None not in (drip_time, drip_rate, drip_vol):
        return [drip_time, drip_rate, drip_vol]

    # Last fallback from Tags block.
    drip_time = _as_float(tags.get("Anti-Solvent Drip Time"))
    drip_rate = _parse_rate_mL_min(tags.get("Anti-Solvent Rate"))
    drip_vol = _as_float(tags.get("Anti-Solvent Volume"))
    if None not in (drip_time, drip_rate, drip_vol):
        return [drip_time, drip_rate, drip_vol]

    raise ValueError("Could not extract [drip_time, drip_rate, drip_volume] from experiment payload.")


def _extract_observation(master_dict):
    utility = master_dict.get("Utility", {})
    if isinstance(utility, dict):
        last_utility = utility.get("Last Utility Value", [])
        if isinstance(last_utility, list) and len(last_utility) > 0:
            obs = _as_float(last_utility[0])
            if obs is not None:
                return obs

        utility_over_time = utility.get("Utility over time", [])
        if isinstance(utility_over_time, list) and len(utility_over_time) > 0:
            obs = _as_float(utility_over_time[-1])
            if obs is not None:
                return obs

    # Fallback keeps the campaign moving even if analysis failed before utility writeback.
    film_score = _as_float(master_dict.get("Film Ranking", {}).get("Score"))
    if film_score is not None:
        print("[Save_Campaign_Log] Utility missing, falling back to Film Ranking score.")
        return film_score

    print("[Save_Campaign_Log] Utility and Film Ranking score missing, defaulting observation to 0.0.")
    return 0.0


def save_experiment_log(file_folder, new_experiment):
    campaign_path = os.path.join(file_folder, "Campaign_Experiments.json")
    analyzed_path = os.path.join(file_folder, new_experiment + "_analyzed.json")
    raw_path = os.path.join(file_folder, new_experiment + ".json")

    try:
        with open(campaign_path, "r") as f:
            campaign_dict = json.load(f)
    except Exception:
        campaign_dict = {}

    source_path = analyzed_path if os.path.exists(analyzed_path) else raw_path
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Missing experiment JSON for logging: {analyzed_path} and {raw_path}")

    with open(source_path, "r") as f:
        master_dict = json.load(f)

    actions = _extract_actions(master_dict)
    observation = _extract_observation(master_dict)

    campaign_dict[new_experiment] = {
        "Observation": observation,
        "Actions": actions,
    }

    with open(campaign_path, "w") as outfile:
        json.dump(campaign_dict, outfile)

