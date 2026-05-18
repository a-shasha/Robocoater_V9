
print('Analysis for Self-Driving (V9 - Full Fidelity)')


# Use headless backend to avoid Tkinter warnings in unattended runs
import matplotlib
matplotlib.use("Agg")


import pandas as pd
import numpy as np
import cv2
import json
import os
import traceback
import importlib.util
import matplotlib.pyplot as plt
from matplotlib import ticker, cm
from matplotlib import style
from matplotlib.gridspec import GridSpec
from scipy.ndimage import gaussian_filter1d  # currently not critical but fine to keep
from .Analysis_2.Film_Classification_2 import classify_Film




# ===========================
# USER INPUTS & CALIBRATION
# ===========================
MIN_WAVELENGTH_ABS = 400
MAX_WAVELENGTH_ABS = 900
MIN_WAVELENGTH_PL = 550
MAX_WAVELENGTH_PL = 900
ABS_LINE_SMOOTH_SIGMA = 4.0  # v7-style absorbance line smoothing
PL_LED_WAVELENGTH = 475
SHOW_PLOTS = 0
MAKE_SPECTRAL_VIDEOS = 0  # Placeholder; no GIF generation in this build

# Contour smoothing controls (set to 0 to disable that axis smoothing)
PL_CONTOUR_SMOOTH_SIGMA_WAVELENGTH = 1.0
PL_CONTOUR_SMOOTH_SIGMA_TIME = 2.0
REFL_CONTOUR_SMOOTH_SIGMA_WAVELENGTH = 1.0
REFL_CONTOUR_SMOOTH_SIGMA_TIME = 2.0

# Plot snapshot controls
# One pre-drip snapshot.
SNAPSHOT_PRE_DRIP_OFFSET_S = -2.0
# Six snapshots over the first 20 s after drip starts (inclusive).
SNAPSHOT_FIRST_WINDOW_S = 20.0
SNAPSHOT_FIRST_WINDOW_POINTS = 6
# Final snapshot at 20 s after drip ends.
SNAPSHOT_POST_DRIP_END_OFFSET_S = 20.0


# Utility weights & PLQY scaling
# (low reflection, low PLQY, high film score → high utility)
PLQY_CONSTANT = 20_000_000  # fixed scale to mirror v7 behavior
UTILITY_WEIGHT_FILM = 1
UTILITY_WEIGHT_REFLECTION = 0
UTILITY_WEIGHT_PLQY = 0


# Parameter Normalization Ranges (for Holmes)
DRIP_TIME_MIN, DRIP_TIME_MAX = 7, 70
DRIP_RATE_MIN, DRIP_RATE_MAX = 0.8, 15.0
DRIP_VOL_MIN, DRIP_VOL_MAX = 50, 500  # match v7


# Absorbance trace wavelength (v7-style OD monitoring)
ABS_FIXED_WAVELENGTH = 532.0




# ===========================
# HELPER FUNCTIONS
# ===========================
def _load_new_visual_module():
   """
   Load New_Visual_test robustly across package/runtime modes.

   The lab PC may execute this module in a context where relative imports
   (`from . import New_Visual_test`) are not resolvable. This loader tries:
   1) relative import
   2) absolute import
   3) direct import from sibling file path
   """
   import_errors = []

   try:
       from . import New_Visual_test as NVT
       return NVT
   except Exception as e:
       import_errors.append(f"relative import failed: {e}")

   try:
       import New_Visual_test as NVT
       return NVT
   except Exception as e:
       import_errors.append(f"absolute import failed: {e}")

   module_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'New_Visual_test.py')
   if os.path.exists(module_path):
       try:
           spec = importlib.util.spec_from_file_location('_self_driving_v9_new_visual_test', module_path)
           if spec is None or spec.loader is None:
               raise ImportError(f"Could not build import spec for {module_path}")
           module = importlib.util.module_from_spec(spec)
           spec.loader.exec_module(module)
           return module
       except Exception as e:
           import_errors.append(f"path import failed ({module_path}): {e}")
   else:
       import_errors.append(f"module file not found: {module_path}")

   raise ImportError(" | ".join(import_errors))


def _load_and_classify_data(file_folder, file_name):
   """Load raw JSON, write analyzed copy, run film classification."""
   json_path = os.path.join(file_folder, file_name + '.json')
   analyzed_json_path = os.path.join(file_folder, file_name + '_analyzed.json')


   try:
       with open(json_path, 'r') as f:
           master_dict = json.load(f)
   except Exception as e:
       print(f"  ERROR: Could not read JSON: {e}")
       return None, None


   # Write initial analyzed copy
   with open(analyzed_json_path, 'w') as outfile:
       json.dump(master_dict, outfile)


   # Film classification: let classify_Film manage image paths internally
   try:
       classify_Film(file_folder, file_name, file_name + '_analyzed')
   except Exception as e:
       print(f"  [Analysis Error] Vision Pipeline failed: {e}")
       # Fallback if Film Ranking is missing
       if 'Film Ranking' not in master_dict:
           master_dict['Film Ranking'] = {
               'Score': 0.0,
               'Rank': 'Error',
               'Image Name': 'N/A'
           }


   # Reload analyzed file (classification may have added Film Ranking)
   if os.path.exists(analyzed_json_path):
       with open(analyzed_json_path, 'r') as f:
           master_dict = json.load(f)


   return master_dict, analyzed_json_path




def _calculate_utility_metrics(master_dict):
   """Compute PLQY, reflection utilities, and total utility."""
   tags = master_dict.get('Tags', {})
   film_score = master_dict.get('Film Ranking', {}).get('Score', 0.0)


   # Extract process parameters
   dripTime = float(tags.get('Anti-Solvent Drip Time', 0))
   try:
       dripRate = float(str(tags.get('Anti-Solvent Rate', 0)).replace('MM', '').strip())
   except Exception:
       dripRate = 0.1
   dripVol = float(tags.get('Anti-Solvent Volume', 0))


   # Compute drip duration (used for reporting) and normalize parameters
   rate_ul_sec = (dripRate * 1000.0) / 60.0 if dripRate > 0 else 0.1  # µL/s
   drip_duration = dripVol / rate_ul_sec if rate_ul_sec > 0 else None


   # Normalize parameters for Holmes
   norm_params = [
       (dripTime - DRIP_TIME_MIN) / (DRIP_TIME_MAX - DRIP_TIME_MIN),
       (dripRate - DRIP_RATE_MIN) / (DRIP_RATE_MAX - DRIP_RATE_MIN),
       (dripVol - DRIP_VOL_MIN) / (DRIP_VOL_MAX - DRIP_VOL_MIN),
   ]


   # Base results structure
   results = {
       'parameter_list': [dripTime, dripRate, dripVol],
       'norm_parameters_list': norm_params,
       'dripTime': dripTime,
       'dripDuration': drip_duration,
       'valid': True,
       'utility_value': [0.0],
       'utility_components': {},
       'pl_times': [],
       'abs_times': [],
       'wavelengths_pl': [],
       'wavelengths_abs': [],
       'dd_plCorrect': {},
       'dd_absorbanceW': {},
       'dd_reflectionW': {},
       'dd_reflectionW_plot': {},
       'PLQY': [],
       'led_abs': [],
       'led_reflection': [],
       'peak_energy': [],
       'peak_area': [],
       'fwhm_energy': [],
       'abs_fixed': []
   }


   # Use full spectra
   dd_plMeasurement = {
       float(k): v for k, v in master_dict.get('PL Measurement', {}).items()
       if k != 'Wavelengths'
   }
   dd_absorbance = {
       float(k): v for k, v in master_dict.get('Absorbance', {}).items()
       if k != 'Wavelengths'
   }
   reflection_section = master_dict.get('Reflection', master_dict.get('Reflection %', {}))
   dd_reflection = {
       float(k): v for k, v in reflection_section.items()
       if k != 'Wavelengths'
   }
   dd_reflection_raw_counts = {
       float(k): v for k, v in master_dict.get('Reflection Spectral Count', {}).items()
       if k != 'Wavelengths'
   }
   dd_reflection_baseline = master_dict.get('Reflection Baseline', {})
   wavelengths = master_dict.get("Wavelengths", [])
   dd_plCorrect_raw = dd_plMeasurement
   dd_absorbanceW_raw = dd_absorbance
   dd_reflectionW_raw = dd_reflection


   # Early exit if no usable spectra
   if not dd_plCorrect_raw or not dd_absorbanceW_raw or not wavelengths:
       print("  [Logic Warning] No valid spectral data found. Using film score only.")
       util = UTILITY_WEIGHT_FILM * film_score
       results['utility_value'] = [util]
       results['utility_components'] = {
           0.0: {
               'Utility score': util,
               'Film Score': film_score
           }
       }
       results['valid'] = False
       return results


   # Spectral slicing and metric computation
   try:
       wavelengths_arr = np.array(wavelengths)


       idx_pl_min = int(np.argmin(np.abs(wavelengths_arr - MIN_WAVELENGTH_PL)))
       idx_pl_max = int(np.argmin(np.abs(wavelengths_arr - MAX_WAVELENGTH_PL)))
       idx_abs_min = int(np.argmin(np.abs(wavelengths_arr - MIN_WAVELENGTH_ABS)))
       idx_abs_max = int(np.argmin(np.abs(wavelengths_arr - MAX_WAVELENGTH_ABS)))


       wavelengths_pl = wavelengths[idx_pl_min:idx_pl_max]
       wavelengths_abs = wavelengths[idx_abs_min:idx_abs_max]
       energies_pl = [1239.9 / w for w in wavelengths_pl]


       # LED index relative to the sliced absorbance window
       idx_led = min(
           range(len(wavelengths_abs)),
           key=lambda i: abs(wavelengths_abs[i] - PL_LED_WAVELENGTH)
       )
       idx_abs_fixed = min(
           range(len(wavelengths_abs)),
           key=lambda i: abs(wavelengths_abs[i] - ABS_FIXED_WAVELENGTH)
       )


       # Slice data dictionaries into relevant wavelength windows
       dd_plCorrect = {
           k: v[idx_pl_min:idx_pl_max] for k, v in dd_plCorrect_raw.items()
           if len(v) >= idx_pl_max
       }
       dd_absorbanceW = {
           k: v[idx_abs_min:idx_abs_max] for k, v in dd_absorbanceW_raw.items()
           if len(v) >= idx_abs_max
       }
       # Recompute absorbance from raw reflection counts + dark/reference baselines
       # without clipping so line plots reflect the physical raw ratio/log behavior.
       dd_absorbanceW_unclipped = {}
       refl_base_full = np.array(
           dd_reflection_baseline.get('Reflective Baseline', []), dtype=float
       )
       dark_base_full = np.array(
           dd_reflection_baseline.get('Black Baseline', []), dtype=float
       )
       if (
           dd_reflection_raw_counts and
           len(refl_base_full) >= idx_abs_max and
           len(dark_base_full) >= idx_abs_max
       ):
           denom_full = refl_base_full - dark_base_full
           denom_safe = np.where(denom_full > 0, denom_full, np.nan)
           for k, v in dd_reflection_raw_counts.items():
               spectrum_raw = np.array(v, dtype=float)
               if len(spectrum_raw) < idx_abs_max:
                   continue
               with np.errstate(divide='ignore', invalid='ignore'):
                   refl_unclipped = (spectrum_raw - dark_base_full) / denom_safe
                   abs_unclipped = -np.log10(refl_unclipped)
               dd_absorbanceW_unclipped[k] = abs_unclipped[idx_abs_min:idx_abs_max].tolist()
       dd_absorbanceW_calc = (
           dd_absorbanceW_unclipped if dd_absorbanceW_unclipped else dd_absorbanceW
       )
       dd_reflectionW = {}
       for k, v in dd_reflectionW_raw.items():
           if len(v) < idx_abs_max:
               continue
           spectrum_ref = np.array(v[idx_abs_min:idx_abs_max], dtype=float)
           finite_vals = spectrum_ref[np.isfinite(spectrum_ref)]
           # Backward compatibility: older runs stored reflection in percent.
           if finite_vals.size > 0 and float(np.nanmedian(finite_vals)) > 2.0:
               spectrum_ref = spectrum_ref / 100.0
           dd_reflectionW[k] = spectrum_ref.tolist()
       # Recompute reflection from raw counts + baselines (no clipping) for plotting.
       dd_reflectionW_unclipped = {}
       if (
           dd_reflection_raw_counts and
           len(refl_base_full) >= idx_abs_max and
           len(dark_base_full) >= idx_abs_max
       ):
           denom_full = refl_base_full - dark_base_full
           denom_safe = np.where(denom_full > 0, denom_full, np.nan)
           for k, v in dd_reflection_raw_counts.items():
               spectrum_raw = np.array(v, dtype=float)
               if len(spectrum_raw) < idx_abs_max:
                   continue
               with np.errstate(divide='ignore', invalid='ignore'):
                   refl_unclipped = (spectrum_raw - dark_base_full) / denom_safe
               dd_reflectionW_unclipped[k] = refl_unclipped[idx_abs_min:idx_abs_max].tolist()
       dd_reflectionW_calc = (
           dd_reflectionW_unclipped if dd_reflectionW_unclipped else dd_reflectionW
       )


       # Keep PL/absorbance/reflection as measured for plotting.
       dd_plContour = {k: list(v) for k, v in dd_plCorrect.items()}
       dd_absContour = {k: list(v) for k, v in dd_absorbanceW.items()}
       dd_reflectionContour = {k: list(v) for k, v in dd_reflectionW_calc.items()}
       pl_Times_full = sorted(dd_plContour.keys())
       abs_Times_full = sorted(dd_absContour.keys())


       # Keep full-run measurements (pre- and post-drip).
       # Time-selection for line plots is handled later using v7-style offsets.


       pl_Times = sorted(dd_plCorrect.keys())
       abs_Times = sorted(dd_reflectionW_calc.keys())


       peakArea = []
       led_abs = []
       led_reflection = []
       reflection_avg = []
       peak_energy = []
       fwhm_energy = []
       abs_fixed = []


       for t in pl_Times:
           # Peak area: integrate full corrected spectrum window
           spectrum_pl = np.array(dd_plCorrect[t], dtype=float)
           peakArea.append(float(np.sum(spectrum_pl)))
           # Peak energy
           if np.max(spectrum_pl) > 0:
               idx_max = int(np.argmax(spectrum_pl))
               peak_energy.append(energies_pl[idx_max])
           else:
               peak_energy.append(None)


           # FWHM in energy space
           if np.max(spectrum_pl) > 0:
               y = spectrum_pl
               half_max = 0.5 * np.max(y)
               above = np.where(y >= half_max)[0]
               if len(above) >= 2:
                   left_idx, right_idx = above[0], above[-1]
                   fwhm_energy.append(energies_pl[left_idx] - energies_pl[right_idx])
               else:
                   fwhm_energy.append(0.0)
           else:
               fwhm_energy.append(0.0)


           # Match absorbance time to PL time
           closest_t_abs = min(dd_absorbanceW_calc.keys(), key=lambda x: abs(x - t))
           spectrum_abs = dd_absorbanceW_calc[closest_t_abs]
           if idx_led < len(spectrum_abs):
               led_abs.append(spectrum_abs[idx_led])
           else:
               led_abs.append(spectrum_abs[-1])


           # Absorbance at fixed wavelength (e.g., 532 nm)
           abs_fixed.append(spectrum_abs[idx_abs_fixed] if idx_abs_fixed < len(spectrum_abs) else spectrum_abs[-1])


           # Mean reflection in the same window
           closest_t_ref = min(dd_reflectionW_calc.keys(), key=lambda x: abs(x - t))
           spectrum_ref = np.array(dd_reflectionW_calc[closest_t_ref], dtype=float)
           reflection_avg.append(float(np.mean(spectrum_ref)))
           if idx_led < len(spectrum_ref):
               led_reflection.append(float(spectrum_ref[idx_led]))
           else:
               led_reflection.append(float(spectrum_ref[-1]))


       # Reflection utility: lower reflection is better
       reflection_utility = [
           max(0.0, min(1.0, 1.0 - r))
           for r in reflection_avg
       ]


       # PLQY and PLQY utility: lower PLQY is better (per-run min/max norm)
       PLQY = []
       for area, abs_val in zip(peakArea, led_abs):
           plqy_val = (area / abs_val) / PLQY_CONSTANT if abs_val > 0 else 0.0
           PLQY.append(plqy_val)


       # Convert to utility: low PLQY → high utility (clip to [0,1])
       PLQY_utility = [1.0 - max(0.0, min(1.0, v)) for v in PLQY]


       utility_value = []
       utility_components_dict = {}


       for i, t in enumerate(pl_Times):
           u_refl = reflection_utility[i]
           u_plqy = PLQY_utility[i]
           total_u = (
               UTILITY_WEIGHT_REFLECTION * u_refl +
               UTILITY_WEIGHT_PLQY * u_plqy +
               UTILITY_WEIGHT_FILM * film_score
           )
           utility_value.append(total_u)
           utility_components_dict[t] = {
               'Utility score': total_u,
               'Reflection Utility': u_refl,
               'PLQY Utility': u_plqy,
               'PLQY Actual': PLQY[i],
               'Film Score': film_score
           }


       # Update results with full data
       results.update({
           'utility_value': utility_value,
           'utility_components': utility_components_dict,
           'pl_times': pl_Times,
           'wavelengths_pl': wavelengths_pl,
           'wavelengths_abs': wavelengths_abs,
           'dd_plCorrect': dd_plCorrect,
           'dd_absorbanceW': dd_absorbanceW,
           'dd_reflectionW': dd_reflectionW,
           'dd_reflectionW_plot': dd_reflectionW_calc,
           'dd_absorbanceW_plot': (
               dd_absorbanceW_unclipped if dd_absorbanceW_unclipped else dd_absorbanceW
           ),
           'PLQY': PLQY,
           'led_abs': led_abs,
           'led_reflection': led_reflection,
           'energies_pl': energies_pl,
           'peak_energy': peak_energy,
           'peak_area': peakArea,
           'fwhm_energy': fwhm_energy,
           'abs_times': abs_Times,
           'abs_fixed': abs_fixed
       })
       # Add full (pre-drip) spectra for contours
       results.update({
           'dd_plContour': dd_plContour,
           'dd_absContour': dd_absContour,
           'dd_reflectionContour': dd_reflectionContour,
           'pl_times_full': pl_Times_full,
           'abs_times_full': abs_Times_full
       })
       # store drip duration (already computed)
       results['dripDuration'] = drip_duration


   except Exception as e:
       print(f"  [Logic Error] Calculation failed: {e}")
       # Fall back to film-only utility
       util = UTILITY_WEIGHT_FILM * film_score
       results['utility_value'] = [util]
       results['utility_components'] = {
           0.0: {
               'Utility score': util,
               'Film Score': film_score
           }
       }
       results['valid'] = False


   return results




def _generate_plots(master_dict, results, file_folder, file_name):
   """Generate production report with the exact New_Visual_test layout/content."""
   if not results or 'utility_value' not in results:
       return

   # Hard requirement: production report must match New_Visual_test exactly.
   # Use robust module loading to avoid runtime/package import differences on lab PCs.
   try:
       NVT = _load_new_visual_module()
   except Exception as e:
       print(f"[Plot Import Error] Could not load New_Visual_test renderer: {e}")
       traceback.print_exc()
       return

   all_points = []
   if getattr(NVT, 'BO_USE_CAMPAIGN_EXPERIMENTS', True):
       try:
           all_points = NVT._load_points_from_campaign_experiments(file_folder)
       except Exception:
           all_points = []

   # Fallback history source: derive campaign points from local json files.
   if not all_points:
       try:
           json_files = NVT._resolve_inputs(file_folder, inputs=None)
       except Exception:
           json_files = []
       for json_path in json_files:
           try:
               name = NVT._get_file_name_base(json_path)
               d = NVT._prepare_master_dict(json_path)
               p = NVT._extract_campaign_point(d, name)
               if p is not None:
                   all_points.append(p)
           except Exception:
               continue

   # Ensure the current experiment is present even before Campaign_Experiments.json
   # is updated by save_experiment_log().
   current_point = NVT._extract_campaign_point(master_dict, file_name)
   if current_point is not None:
       replaced = False
       for idx, point in enumerate(all_points):
           if str(point.get('name', '')) == str(file_name):
               all_points[idx] = current_point
               replaced = True
               break
       if not replaced:
           all_points.append(current_point)

   all_points = sorted(
       all_points,
       key=lambda p: NVT._sample_sort_key(str(p.get('name', '')))
   )
   total_steps = len(all_points)
   objective_limits = NVT._objective_limits_from_points(
       all_points,
       objective_mode=NVT.BO_OBJECTIVE_MODE
   )
   history_points = [
       p for p in all_points
       if NVT._sample_sort_key(str(p.get('name', '')))
       <= NVT._sample_sort_key(file_name)
   ]
   step_idx = len(history_points)
   bo_state = {"kernel_cache": {}, "prev_surface": None}

   NVT._generate_plots_new(
       master_dict=master_dict,
       results=results,
       output_folder=file_folder,
       source_folder=file_folder,
       file_name=file_name,
       history_points=history_points,
       all_points=all_points,
       step_idx=step_idx,
       total_steps=total_steps,
       objective_limits=objective_limits,
       bo_strategy=NVT.BO_SURROGATE_STRATEGY,
       objective_mode=NVT.BO_OBJECTIVE_MODE,
       bo_state=bo_state,
   )




def _update_json_file(folder, filename, key, data):
   """Safe helper to read/update/save a JSON dictionary."""
   path = os.path.join(folder, filename)
   try:
       with open(path, 'r') as f:
           current_dict = json.load(f)
   except Exception:
       current_dict = {}


   current_dict[key] = data
   with open(path, 'w') as f:
       json.dump(current_dict, f, default=str)




def _save_master_files(master_dict, results, file_folder, file_name, analyzed_json_path):
   """Update individual analyzed JSON + all 4 master tracking JSON files."""
   if not results or 'utility_value' not in results:
       return


   # 1) Update analyzed JSON for this experiment
   master_dict['Valid'] = results.get('valid', True)
   master_dict['Utility'] = {
       'Utility Components': results['utility_components'],
       'Utility over time': results['utility_value'],
       'Last Utility Value': [results['utility_value'][-1]],
       'Max Utility Value': [max(results['utility_value'])],
       'Film Score': master_dict.get('Film Ranking', {}).get('Score', 0.0)
   }
   master_dict['Parameters'] = {
       'Normalized parameters': results['norm_parameters_list'],
       'Actual parameters': results['parameter_list']
   }


   with open(analyzed_json_path, 'w') as f:
       json.dump(master_dict, f, default=str)
   print("Saved analyzed data")


   # 2) MasterUtility.json (central utility + parameters)
   utility_data = {**master_dict['Utility'], **master_dict['Parameters']}
   _update_json_file(file_folder, 'MasterUtility.json', file_name, utility_data)


   # 3) TimePoints_MasterUtility.json (PL times)
   _update_json_file(
       file_folder,
       'TimePoints_MasterUtility.json',
       file_name,
       results.get('pl_times', [])
   )


   # 4) NormParameters_MasterUtility.json (normalized parameters)
   _update_json_file(
       file_folder,
       'NormParameters_MasterUtility.json',
       file_name,
       results['norm_parameters_list']
   )


   # 5) Observations_MasterUtility.json (utility trajectory)
   _update_json_file(
       file_folder,
       'Observations_MasterUtility.json',
       file_name,
       results['utility_value']
   )


   # 6) Valid_MasterUtility.json (validity flag)
   _update_json_file(
       file_folder,
       'Valid_MasterUtility.json',
       file_name,
       results.get('valid', True)
   )


   print("Saved all Master utility files")




# ===========================
# PUBLIC ENTRY POINT
# ===========================
def analyze_Data(fileFolder, fileName):
   """
   Main entry that Self_Driving_V9.run_campaign should call.


   Parameters
   ----------
   fileFolder : str
       Campaign folder path.
   fileName : str
       Base name for this experiment (no extension).
   """
   print(f'--- V9 Analyzing Data for: {fileName} ---')
   try:
       master_Dict, analyzed_path = _load_and_classify_data(fileFolder, fileName)
       if master_Dict is None:
           print("  [Fatal] Could not load data. Skipping analysis.")
           return


       results = _calculate_utility_metrics(master_Dict)
       _generate_plots(master_Dict, results, fileFolder, fileName)
       _save_master_files(master_Dict, results, fileFolder, fileName, analyzed_path)


       # Spectral videos are intentionally disabled in this build
       if MAKE_SPECTRAL_VIDEOS:
           print("Generating spectral videos... (disabled in current build)")
       else:
           print("Skipping UV/PL GIF generation (MAKE_SPECTRAL_VIDEOS = 0).")


   except Exception:
       print(f"AN ERROR OCCURRED IN analyze_Data for {fileName}:")
       traceback.print_exc()
