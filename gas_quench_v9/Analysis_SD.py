
print('Analysis for Self-Driving (V9_GQ - Full Fidelity)')


# Use headless backend to avoid Tkinter warnings in unattended runs
import matplotlib
matplotlib.use("Agg")


import pandas as pd
import numpy as np
import cv2
import json
import os
import traceback
import matplotlib.pyplot as plt
from matplotlib import ticker, cm
from matplotlib import style
from matplotlib.gridspec import GridSpec
from scipy.ndimage import gaussian_filter1d  # currently not critical but fine to keep
from .Analysis_2.Film_Classification_2 import classify_Film




# ===========================
# USER INPUTS & CALIBRATION
# ===========================
MIN_WAVELENGTH_ABS = 550
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
# One pre-quench snapshot.
SNAPSHOT_PRE_DRIP_OFFSET_S = -2.0
# Six snapshots over the first 20 s after the gas quench starts (inclusive).
SNAPSHOT_FIRST_WINDOW_S = 20.0
SNAPSHOT_FIRST_WINDOW_POINTS = 6
# Final snapshot at 20 s after the gas pulse ends.
SNAPSHOT_POST_DRIP_END_OFFSET_S = 20.0


# Utility weights & PLQY scaling
# (low reflection, low PLQY, high film score → high utility)
PLQY_CONSTANT = 20_000_000  # fixed scale to mirror v7 behavior
UTILITY_WEIGHT_FILM = 1
UTILITY_WEIGHT_REFLECTION = 0
UTILITY_WEIGHT_PLQY = 0


# Parameter Normalization Ranges (for Holmes)
GQ_TIME_MIN, GQ_TIME_MAX = 7, 70
GQ_DURATION_MIN, GQ_DURATION_MAX = 1, 14


# Absorbance trace wavelength (v7-style OD monitoring)
ABS_FIXED_WAVELENGTH = 532.0




# ===========================
# HELPER FUNCTIONS
# ===========================
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


   # Extract the two gas-quench process parameters.
   gqTime = float(tags.get('Gas Quench Start Time', 0))
   gq_duration = float(tags.get('Gas Quench Duration', 0))


   # Normalize parameters for Holmes in the 2D GQ space.
   norm_params = [
       (gqTime - GQ_TIME_MIN) / (GQ_TIME_MAX - GQ_TIME_MIN),
       (gq_duration - GQ_DURATION_MIN) / (GQ_DURATION_MAX - GQ_DURATION_MIN),
   ]


   # Base results structure
   results = {
       'parameter_list': [gqTime, gq_duration],
       'norm_parameters_list': norm_params,
       'gqTime': gqTime,
       'gqDuration': gq_duration,
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


       # Keep full-run measurements before and after the gas-quench event.
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
       # Add full pre-event spectra for the contour panels.
       results.update({
           'dd_plContour': dd_plContour,
           'dd_absContour': dd_absContour,
           'dd_reflectionContour': dd_reflectionContour,
           'pl_times_full': pl_Times_full,
           'abs_times_full': abs_Times_full
       })
       # Store the gas pulse duration explicitly for reporting and snapshot anchoring.
       results['gqDuration'] = gq_duration


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
   """Generate v7-style summary plot with utility header."""
   if not results or 'utility_value' not in results:
       return


   try:
       style.use('default')
       # Target ~720p height: 12x6 in at 120 dpi → 1440x720px
       fig = plt.figure(figsize=(12, 6), constrained_layout=True)
       gs = GridSpec(4, 4, figure=fig)


       def _nearest_times(sorted_times, drip_time, offsets, include_last=False):
           """Return unique measurement times nearest fixed offsets; optionally append final time."""
           if not sorted_times:
               return []
           selected = []
           seen = set()
           if drip_time is not None:
               for off in offsets:
                   target = drip_time + off
                   closest = min(sorted_times, key=lambda t: abs(t - target))
                   if closest not in seen:
                       selected.append(closest)
                       seen.add(closest)
           if include_last:
               last_t = sorted_times[-1]
               if last_t not in seen:
                   selected.append(last_t)
           return selected

       def _nearest_targets(sorted_times, targets, include_last=False):
           """Return unique measurement times nearest explicit target timestamps."""
           if not sorted_times:
               return []
           selected = []
           seen = set()
           for target in targets:
               closest = min(sorted_times, key=lambda t: abs(t - target))
               if closest not in seen:
                   selected.append(closest)
                   seen.add(closest)
           if include_last:
               last_t = sorted_times[-1]
               if last_t not in seen:
                   selected.append(last_t)
           return selected

       def _event_anchored_targets(event_time, event_duration):
           """Build snapshot targets from gas-quench start/end timing policy."""
           if event_time is None:
               return []
           try:
               event_start = float(event_time)
           except Exception:
               return []

           targets = [event_start + SNAPSHOT_PRE_DRIP_OFFSET_S]

           if SNAPSHOT_FIRST_WINDOW_POINTS <= 1:
               targets.append(event_start)
           else:
               for off in np.linspace(0.0, SNAPSHOT_FIRST_WINDOW_S, SNAPSHOT_FIRST_WINDOW_POINTS):
                   targets.append(event_start + float(off))

           try:
               pulse_dur = max(0.0, float(event_duration))
           except Exception:
               pulse_dur = 0.0
           event_end = event_start + pulse_dur
           targets.append(event_end + SNAPSHOT_POST_DRIP_END_OFFSET_S)
           return targets

       def _finite_xy(x_vals, y_vals):
           """Convert x/y to float arrays and drop non-finite points."""
           x_arr = np.asarray(x_vals, dtype=float)
           y_arr = np.asarray(
               [np.nan if v is None else float(v) for v in y_vals],
               dtype=float
           )
           mask = np.isfinite(x_arr) & np.isfinite(y_arr)
           return x_arr[mask], y_arr[mask]

       def _smooth_axis_if_needed(arr, sigma, axis):
           """Apply 1D gaussian smoothing only when sigma is strictly positive."""
           if sigma is None:
               return arr
           try:
               sigma_val = float(sigma)
           except Exception:
               return arr
           if sigma_val <= 0:
               return arr
           return gaussian_filter1d(arr, sigma=sigma_val, axis=axis)


       tags = master_dict.get('Tags', {})
       gqTime = results.get('gqTime', tags.get('Gas Quench Start Time'))
       gqDuration = results.get('gqDuration', tags.get('Gas Quench Duration'))
       film_info = master_dict.get('Film Ranking', {})
       film_rank = film_info.get('Rank', 'N/A')
       film_score = film_info.get('Score', 'N/A')
       final_u = results['utility_value'][-1]
       total_time = tags.get('Spin Time', None)


       # Clamp header to 2 decimal places to avoid long floats from JSON
       def _fmt(val, suffix=""):
           try:
               return f"{float(val):.2f}{suffix}"
           except Exception:
               return "N/A" + suffix

       gq_duration = results.get('gqDuration', None)
       titleFig = (
           f"{file_name} | GQ Time: {_fmt(gqTime)} s | "
           f"GQ Duration: {_fmt(gq_duration)} s\n"
           f"Film Rank: {film_rank} | Utility: {final_u:.2f}"
       )
       fig.suptitle(titleFig, fontsize=13)


       # Create sub plots as grid (v7 layout)
       plt1 = fig.add_subplot(gs[0:2, 0])
       plt2 = fig.add_subplot(gs[0:2, 1])
       plt3a = fig.add_subplot(gs[0, 2])
       plt3b = fig.add_subplot(gs[1, 2])
       plt4 = fig.add_subplot(gs[2:4, 0])
       plt5 = fig.add_subplot(gs[2:4, 1])
       plt6a = fig.add_subplot(gs[2, 2])
       plt6b = fig.add_subplot(gs[3, 2])
       plt7 = fig.add_subplot(gs[2:4, 3])
       plt8 = fig.add_subplot(gs[0:2, 3])


       # Unpack results
       pl_Times = sorted(results.get('pl_times', []))
       abs_Times = sorted(results.get('abs_times', []))
       pl_Times_full = sorted(results.get('pl_times_full', pl_Times))
       abs_Times_full = sorted(results.get('abs_times_full', abs_Times))
       wavelengths_pl = results.get('wavelengths_pl', [])
       wavelengths_abs = results.get('wavelengths_abs', [])
       dd_plCorrect = results.get('dd_plCorrect', {})
       dd_absorbanceW = results.get('dd_absorbanceW', {})
       dd_reflectionW = results.get('dd_reflectionW', {})
       dd_reflectionW_plot = results.get('dd_reflectionW_plot', dd_reflectionW)
       dd_plContour = results.get('dd_plContour', dd_plCorrect)
       dd_reflectionContour = results.get('dd_reflectionContour', dd_reflectionW_plot)
       energies_pl = results.get('energies_pl', [])
       utility_value = results.get('utility_value', [])
       PLQY = results.get('PLQY', [])
       peak_energy = results.get('peak_energy', [])
       peak_area = results.get('peak_area', [])
       fwhm_energy = results.get('fwhm_energy', [])
       led_reflection = results.get('led_reflection', [])


       # Find indices closest to the gas-quench start time for post-quench traces.
       gq_idx_pl = 0
       gq_idx_abs = 0
       if pl_Times and gqTime is not None:
           gq_idx_pl = min(range(len(pl_Times)), key=lambda i: abs(pl_Times[i] - gqTime))
       if abs_Times and gqTime is not None:
           gq_idx_abs = min(range(len(abs_Times)), key=lambda i: abs(abs_Times[i] - gqTime))


       # Snapshot selection for both PL and reflection:
       # 2 s before GQ, 6 points in the first 20 s after GQ start,
       # and one final point 20 s after the gas pulse ends.
       snapshot_targets = _event_anchored_targets(gqTime, gq_duration)
       pl_selected = _nearest_targets(pl_Times, snapshot_targets, include_last=False)
       refl_selected = _nearest_targets(abs_Times, snapshot_targets, include_last=False)


       # Plot 1: PL at selected times (v7-style line logic)
       if pl_selected and dd_plCorrect and wavelengths_pl:
           for k in pl_selected:
               if k in dd_plCorrect:
                   plt1.plot(wavelengths_pl, dd_plCorrect[k])
           plt1.legend([f"{k:.2f}" for k in pl_selected], prop={'size': 7}, title="Times")
           plt1.set_title("PL at Selected Times")
           plt1.set_xlabel("Wavelength (nm)")
           plt1.set_ylabel("PL Count")
       else:
           plt1.text(0.5, 0.5, 'NO PL DATA', ha='center', va='center')
           plt1.axis('off')


       # Plot 2: PL contour (Energy vs Time)
       if pl_Times_full and energies_pl and dd_plContour:
           df_pl = pd.DataFrame.from_dict(dict(sorted(dd_plContour.items())))
           X, Y = np.meshgrid(sorted(df_pl.columns), energies_pl)
           Z = np.array(df_pl)
           # Smooth along wavelength (energy) and time axes to reduce banding.
           Z = _smooth_axis_if_needed(Z, PL_CONTOUR_SMOOTH_SIGMA_WAVELENGTH, axis=0)
           Z = _smooth_axis_if_needed(Z, PL_CONTOUR_SMOOTH_SIGMA_TIME, axis=1)
           zmin, zmax = float(np.min(Z)), float(np.max(Z))
           if zmax <= zmin:
               zmax = zmin + 1e-6
           levels = np.linspace(zmin, zmax, 256)
           contourPlot = plt2.contourf(X, Y, Z, levels=levels, cmap=cm.rainbow)
           cpBar = fig.colorbar(contourPlot, ax=plt2)
           plt2.set_title("PL Intensity contour vs. Time")
           plt2.set_xlabel('Time (seconds)')
           plt2.set_ylabel('PL Energy (eV)')
           cpBar.ax.set_ylabel('PL Intensity (a.u.)')
       else:
           plt2.text(0.5, 0.5, 'NO PL DATA', ha='center', va='center')
           plt2.axis('off')


       # Peak energy and area traces (post-quench)
       if peak_energy and pl_Times:
           plTime_AD = pl_Times[gq_idx_pl:]
           peakEnergy_AD = peak_energy[gq_idx_pl:len(plTime_AD) + gq_idx_pl]
           x_e, y_e = _finite_xy(plTime_AD, peakEnergy_AD)
           if y_e.size > 0:
               y_plot = gaussian_filter1d(y_e, sigma=5) if y_e.size >= 3 else y_e
               plt3a.plot(x_e, y_plot)
               plt3a.set_title('Final Peak: {:.2f} eV'.format(y_e[-1]))
               plt3a.set_ylabel('PL Energy (eV)')
               plt3a.set_xlabel('Time (seconds)')
           else:
               plt3a.text(0.5, 0.5, 'N/A', ha='center', va='center')
               plt3a.axis('off')
       else:
           plt3a.text(0.5, 0.5, 'N/A', ha='center', va='center')
           plt3a.axis('off')


       if peak_area and pl_Times:
           plTime_AD = pl_Times[gq_idx_pl:]
           peakArea_AD = peak_area[gq_idx_pl:len(plTime_AD) + gq_idx_pl]
           x_a, y_a = _finite_xy(plTime_AD, peakArea_AD)
           if y_a.size > 0:
               y_plot = gaussian_filter1d(y_a, sigma=2) if y_a.size >= 3 else y_a
               plt3b.plot(x_a, y_plot)
               plt3b.set_title('PL Peak Area')
               plt3b.set_ylabel('PLn (a.u.)')
               plt3b.set_xlabel('Time (seconds)')
           else:
               plt3b.text(0.5, 0.5, 'N/A', ha='center', va='center')
               plt3b.axis('off')
       else:
           plt3b.text(0.5, 0.5, 'N/A', ha='center', va='center')
           plt3b.axis('off')


       # Plot 4: Reflection at selected times (v7-style line logic)
       if refl_selected and dd_reflectionW_plot and wavelengths_abs:
           for k in refl_selected:
               if k not in dd_reflectionW_plot:
                   continue
               y = np.array(dd_reflectionW_plot[k], dtype=float)
               if ABS_LINE_SMOOTH_SIGMA > 0 and np.all(np.isfinite(y)):
                   y = gaussian_filter1d(y, sigma=ABS_LINE_SMOOTH_SIGMA)
               plt4.plot(wavelengths_abs, y)
           plt4.legend([f"{k:.2f}" for k in refl_selected], prop={'size': 7}, title="Times")
           plt4.set_title("Reflection at Selected Times")
           plt4.set_xlabel("Wavelength (nm)")
           plt4.set_ylabel("Reflection (R)")
       else:
           plt4.text(0.5, 0.5, 'NO REFLECTION DATA', ha='center', va='center')
           plt4.axis('off')


       # Plot 5: Reflection contour
       if dd_reflectionContour and wavelengths_abs:
           df_refl = pd.DataFrame.from_dict(dict(sorted(dd_reflectionContour.items())))
           refl_times_sorted = sorted(df_refl.columns)
           X, Y = np.meshgrid(refl_times_sorted, wavelengths_abs)
           Z = np.array(df_refl, dtype=float)
           if np.isfinite(Z).any():
               if not np.all(np.isfinite(Z)):
                   finite_vals = Z[np.isfinite(Z)]
                   fill_val = float(np.median(finite_vals)) if finite_vals.size > 0 else 0.0
                   Z = np.where(np.isfinite(Z), Z, fill_val)
               # Smooth along wavelength and time axes to reduce banding.
               Z = _smooth_axis_if_needed(Z, REFL_CONTOUR_SMOOTH_SIGMA_WAVELENGTH, axis=0)
               Z = _smooth_axis_if_needed(Z, REFL_CONTOUR_SMOOTH_SIGMA_TIME, axis=1)
               zmin, zmax = float(np.min(Z)), float(np.max(Z))
               if zmax <= zmin:
                   zmax = zmin + 1e-6
               levels = np.linspace(zmin, zmax, 256)
               contourPlot = plt5.contourf(X, Y, Z, levels=levels, cmap=cm.rainbow)
               cpBar = fig.colorbar(contourPlot, ax=plt5)
               plt5.set_title('Reflection contour vs Time')
               plt5.set_xlabel('Time (seconds)')
               plt5.set_ylabel('Wavelengths (nm)')
               cpBar.ax.set_ylabel('Reflection (R)')
           else:
               plt5.text(0.5, 0.5, 'NO REFLECTION DATA', ha='center', va='center')
               plt5.axis('off')
       else:
           plt5.text(0.5, 0.5, 'NO REFLECTION DATA', ha='center', va='center')
           plt5.axis('off')


       # Plot 6a: PLQY vs time (post-quench)
       if PLQY and pl_Times:
           plqy_Times = pl_Times
           start_idx = min(max(gq_idx_pl, 0), len(PLQY) - 1, len(plqy_Times) - 1)
           plt6a.plot(plqy_Times[start_idx:], PLQY[start_idx:])
           plt6a.set_title("PLQY")
           plt6a.set_xlabel("Time (seconds)")
       else:
           plt6a.text(0.5, 0.5, 'N/A', ha='center', va='center')
           plt6a.axis('off')


       # Plot 6b: Reflection at LED wavelength vs time (post-quench)
       if led_reflection and abs_Times:
           start_idx_abs = min(max(gq_idx_abs, 0), len(abs_Times) - 1, len(led_reflection) - 1)
           n = min(len(abs_Times) - start_idx_abs, len(led_reflection) - start_idx_abs)
           if n > 0:
               plt6b.plot(
                   abs_Times[start_idx_abs:start_idx_abs + n],
                   led_reflection[start_idx_abs:start_idx_abs + n]
               )
               plt6b.set_title(f'Reflection at {PL_LED_WAVELENGTH:.0f} nm')
               plt6b.set_xlabel("Time (seconds)")
               plt6b.set_ylabel("Reflection (R)")
           else:
               plt6b.text(0.5, 0.5, 'N/A', ha='center', va='center')
               plt6b.axis('off')
       else:
           plt6b.text(0.5, 0.5, 'N/A', ha='center', va='center')
           plt6b.axis('off')

       # Plot 7: Utility over time removed (no longer used)
       plt7.axis('off')


       # Plot 8: Film image
       img_path = os.path.join(
           file_folder,
           'images',
           film_info.get('Image Name', '')
       )
       if os.path.exists(img_path):
            img = cv2.imread(img_path)
            if img is not None:
                plt8.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                plt8.axis('off')
                plt8.text(0.5, -0.06, f"Film Rank {film_rank}", transform=plt8.transAxes,
                          ha='center', va='top', fontsize=10)
            else:
                plt8.text(0.5, 0.5, 'IMAGE READ ERROR', ha='center', va='center')
                plt8.axis('off')
                plt8.text(0.5, -0.06, f"Film Rank {film_rank}", transform=plt8.transAxes,
                          ha='center', va='top', fontsize=10)
       else:
           plt8.text(0.5, 0.5, 'IMAGE NOT FOUND', ha='center', va='center')
           plt8.axis('off')
           plt8.text(0.5, -0.06, f"Film Rank {film_rank}", transform=plt8.transAxes,
                     ha='center', va='top', fontsize=10)


       save_path = os.path.join(file_folder, file_name + '_Analyzed.jpeg')
       # Save at 120 dpi to hit ~1440x720px output
       plt.savefig(save_path, dpi=120)
       print(f"Saved Analysis plot to {save_path}")
       if SHOW_PLOTS >= 1:
           plt.show()
       plt.close(fig)


   except Exception as e:
       print(f"  [Plotting Error] {e}")
       traceback.print_exc()




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
       'Parameter Names': ['Gas Quench Time', 'Gas Quench Duration'],
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
