import time
import requests
import json
import os
import numpy as np
from .Perovskite_Recipe_SD import run_Perovskite_Recipe
from .Analysis_2.start_up_folders_2 import create_folders
from . import Dual_Send_Commands as DSC
from . import Dual_Send_OceanFlame as DSO




## User Inputs ##
file_folder = r"C:\Users\Admin\Desktop\Holmes_Campaign_V9"
baseName = 'Campaign_V9_'
create_folders(file_folder)
experiment_budget = 45




# --- Hardware Parameters ---
measType = 3
spreadTime = 12
rpm = 4000
perovVol = 60
timeAfterDrip = 60




# --- Holmes Server Configuration ---
BASE_URL = "http://127.0.0.1:5000/holmes"
# Holmes action-space bounds in real units (time s, rate mL/min, volume uL)
HOLMES_BOUNDS = [
  [7.0, 70.0],
  [0.8, 15.0],
  [50.0, 500.0],
]
# Fixed BO domain in normalized coordinates.
HOLMES_NORMALIZED_BOUNDS = [
  [0.0, 0.0, 0.0],
  [1.0, 1.0, 1.0],
]




# Adaptive BO cadence: 2 exploit (GPEI) then 1 explore (MAXVAR)
EXPLOIT_POLICY = "gpei"
EXPLORE_POLICY = "maxvar"
EXPLORE_EVERY = 3




# Optional drift/noise check: every N adaptive runs, repeat best-so-far action. put 0 to disable.
# Note that this adds extra runs to the campaign, so plan experiment_budget accordingly.
REPLICATE_EVERY = 5




# Deterministic LHS shuffling for resume-safe campaigns.
LHS_RANDOM_SEED = 42




# Constrained LHS7 seed
LHS_DRIP_TIMES = [7, 12, 19, 27, 33, 39, 45]
LHS_RATE_LEVELS = [0.8, 3.0, 6.0, 9.0, 12.0, 13.5, 15.0]
LHS_VOL_LEVELS = [50, 125, 200, 300, 400, 450, 500]








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
  """Map real-valued action [time, rate, vol] into [0,1]^3."""
  norm = []
  for val, (lb, ub) in zip(params, HOLMES_BOUNDS):
      denom = (ub - lb)
      if denom <= 0:
          norm.append(0.0)
      else:
          norm.append((val - lb) / denom)
  return norm








def _denormalize_parameters(norm_params):
  """Map normalized action [0,1]^3 back into real-valued [time, rate, vol]."""
  params = []
  for val, (lb, ub) in zip(norm_params, HOLMES_BOUNDS):
      params.append(lb + val * (ub - lb))
  return params








def constrain_parameters(params):
  """Clip suggested parameters to hardware-safe action bounds."""
  drip_time, drip_rate, drip_vol = [float(x) for x in params]
  safe_drip_time = max(HOLMES_BOUNDS[0][0], min(drip_time, HOLMES_BOUNDS[0][1]))
  safe_drip_rate = max(HOLMES_BOUNDS[1][0], min(drip_rate, HOLMES_BOUNDS[1][1]))
  safe_drip_vol = max(HOLMES_BOUNDS[2][0], min(drip_vol, HOLMES_BOUNDS[2][1]))
  constrained = [safe_drip_time, safe_drip_rate, safe_drip_vol]
  if constrained != params:
      print(f"WARNING: Holmes suggestion {params} was outside hardware limits. Constraining to {constrained}.")
  return constrained








def run_experiment(params_list, fileFolder, fileName):
  safe_params = constrain_parameters(params_list)
  print(f"--- Starting Experiment: {fileName} ---")
  print(
      f"Parameters: Drip Time={safe_params[0]:.2f}s, Drip Rate={safe_params[1]:.2f}ml/min, Drip Vol={safe_params[2]:.2f}uL")
  dripTime, dripRate, dripVol = safe_params
  sample_start_monotonic = time.monotonic()
  DSC.configure_operation_event_logger(
      campaign_folder=fileFolder,
      file_name=fileName,
      sample_start_monotonic=sample_start_monotonic,
      requested_drip_time_s=dripTime,
      requested_rate_ml_min=dripRate,
      requested_volume_ul=dripVol,
  )
  DSC.log_operation_event(
      "sample_start",
      details=(
          f"file_name={fileName}, drip_time_s={dripTime:.3f}, "
          f"drip_rate_ml_min={dripRate:.3f}, drip_volume_ul={dripVol:.3f}"
      ),
  )
  DSC.init_List()
  DSO.create_Dataframes()
  # Keep spinner running across reflection baseline -> dark baseline -> PL baseline.
  DSC.log_operation_event(
      "baseline_start",
      details=f"measurement_type={measType}, spinner_target_rpm={rpm}",
  )
  DSO.reflc_Baseline(rpm, keep_spinner_on=True)
  # Explicit transition gap between LED and UV baseline phases.
  time.sleep(0.8)
  DSO.pl_Baseline(rpm, spinner_already_on=True)
  time.sleep(6)
  DSC.log_operation_event(
      "baseline_end",
      details=f"measurement_type={measType}, spinner_target_rpm={rpm}",
  )
  runTime = dripTime + timeAfterDrip
  timeStart = time.time()
  # This is the only function that should be called here.
  # It now handles the entire sequence internally.
  run_Perovskite_Recipe(timeStart, measType, perovVol, spreadTime, rpm, runTime, dripTime, dripVol, dripRate,
                        fileFolder, fileName)
  print(f"--- Experiment {fileName} Complete ---")








def _build_lhs_seed():
  """Create constrained LHS seed points with deterministic shuffled pairings."""
  if not (len(LHS_DRIP_TIMES) == len(LHS_RATE_LEVELS) == len(LHS_VOL_LEVELS)):
      raise ValueError("LHS lists must have identical lengths.")




  rng = np.random.default_rng(LHS_RANDOM_SEED)




  idx_rates = rng.permutation(len(LHS_DRIP_TIMES))
  drip_rates = [LHS_RATE_LEVELS[i] for i in idx_rates]




  idx_vols = rng.permutation(len(LHS_DRIP_TIMES))
  drip_volumes = [LHS_VOL_LEVELS[i] for i in idx_vols]




  return [[t, r, v] for t, r, v in zip(LHS_DRIP_TIMES, drip_rates, drip_volumes)]








def _campaign_rows_for_holmes():
  """Return Holmes training rows as normalized [time, rate, vol, observation]."""
  campaign_dict = _read_campaign_dict()
  rows = []




  for _, v in campaign_dict.items():
      actions = v.get("Actions", [])
      obs = _as_float(v.get("Observation", None))
      if not (isinstance(actions, list) and len(actions) == 3 and obs is not None):
          continue




      actions_num = [_as_float(x) for x in actions]
      if any(x is None for x in actions_num):
          continue




      actions_safe = constrain_parameters(actions_num)
      actions_norm = _normalize_parameters(actions_safe)
      rows.append(actions_norm + [obs])




  return rows








def _query_holmes_suggestions(rows):
  print("\n--- Querying Holmes Server ---")
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
          raise ValueError(f"Holmes suggestions missing required policies: {suggestion_map.keys()}")




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
  """Return best-so-far action by max observed utility (for replicate checks)."""
  campaign_dict = _read_campaign_dict()
  best_action = None
  best_obs = None
  for _, v in campaign_dict.items():
      actions = v.get("Actions", [])
      obs = _as_float(v.get("Observation", None))
      if not (isinstance(actions, list) and len(actions) == 3 and obs is not None):
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
  print(f"LHS seed count: {learning_experiments}")




  try:
      completed = _count_completed_runs()
      if completed > 0:
          print(f"Resuming campaign with {completed} completed runs.")




      # Stage 1: LHS warm start
      for i in range(completed, min(learning_experiments, experiment_budget)):
          params = lhs_seed[i]
          fileName = f"{baseName}{i}_LHS"
          run_experiment(params, file_folder, fileName)
          completed = _count_completed_runs()
          _pause_if_needed(completed)




      # Stage 2: Adaptive BO with explicit exploit/explore cadence
      while completed < experiment_budget:
          adaptive_idx = max(0, completed - learning_experiments)




          # Optional periodic replicate for drift/noise awareness.
          if REPLICATE_EVERY > 0 and adaptive_idx > 0 and (adaptive_idx % REPLICATE_EVERY == 0):
              best_action, best_obs = _best_action_from_campaign()
              if best_action is not None:
                  print(f"\n--- Running replicate check at observed best utility={best_obs:.4f} ---")
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
      print("\nCampaign finished or interrupted. Shutting down hardware.")
      DSC.log_operation_event(
          "campaign_finally_shutdown_start",
          details="run_campaign.main finally block entered",
      )
      DSC.stopSpinner(time.time())
      DSC.close_Ser()
      if DSO:
          DSO.close_spectrometer()
      DSC.log_operation_event(
          "campaign_finally_shutdown_end",
          details="run_campaign.main finally block completed",
      )
      print("Hardware shutdown complete.")








if __name__ == "__main__":
  main()














