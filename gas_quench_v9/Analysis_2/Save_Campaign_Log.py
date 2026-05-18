import json
import os


def save_experiment_log(file_folder, new_experiment):
    """Append one analyzed GQ experiment to Campaign_Experiments.json."""
    campaign_path = os.path.join(file_folder, 'Campaign_Experiments.json')
    analyzed_path = os.path.join(file_folder, new_experiment + '_analyzed.json')

    try:
        with open(campaign_path, 'r') as f:
            campaign_dict = json.load(f)
    except Exception:
        campaign_dict = {}

    with open(analyzed_path, 'r') as f:
        master_dict = json.load(f)

    params = master_dict['Parameters']['Actual parameters']
    if len(params) < 2:
        raise ValueError(
            f"Expected 2 GQ parameters in analyzed payload for {new_experiment}, got {params}"
        )

    gqTime = params[0]
    gqDuration = params[1]

    # Use the final utility score as the observation for Holmes.
    final_utility = master_dict['Utility']['Last Utility Value'][0]

    campaign_dict[new_experiment] = {
        'Observation': final_utility,
        'Actions': [gqTime, gqDuration],
        'Parameter Names': ['Gas Quench Time', 'Gas Quench Duration'],
    }

    with open(campaign_path, 'w') as outfile:
        json.dump(campaign_dict, outfile)
