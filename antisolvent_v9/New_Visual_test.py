print('New Visual Test for Self-Driving (V9 alt report)')

import argparse
import copy
import json
import os
import re
import traceback
import warnings

import cv2
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from matplotlib import cm, style
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from scipy.ndimage import gaussian_filter1d
from sklearn.preprocessing import PolynomialFeatures
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, RBF, RationalQuadratic


# ===========================
# V9-derived settings
# ===========================
MIN_WAVELENGTH_ABS = 400
MAX_WAVELENGTH_ABS = 900
MIN_WAVELENGTH_PL = 550
MAX_WAVELENGTH_PL = 900

ABS_LINE_SMOOTH_SIGMA = 4.0
PL_LED_WAVELENGTH = 475
SHOW_PLOTS = 0

PL_CONTOUR_SMOOTH_SIGMA_WAVELENGTH = 1.0
PL_CONTOUR_SMOOTH_SIGMA_TIME = 2.0
REFL_CONTOUR_SMOOTH_SIGMA_WAVELENGTH = 1.0
REFL_CONTOUR_SMOOTH_SIGMA_TIME = 2.0

SNAPSHOT_PRE_DRIP_OFFSET_S = -2.0
SNAPSHOT_FIRST_WINDOW_S = 20.0
SNAPSHOT_FIRST_WINDOW_POINTS = 6
SNAPSHOT_POST_DRIP_END_OFFSET_S = 20.0

PLQY_CONSTANT = 20_000_000
UTILITY_WEIGHT_FILM = 1
UTILITY_WEIGHT_REFLECTION = 0
UTILITY_WEIGHT_PLQY = 0

ABS_FIXED_WAVELENGTH = 532.0

# New-visual specific settings
OUTPUT_DPI = 120
OUTPUT_SUFFIX = "_Analyzed.jpeg"
OUTPUT_SUBFOLDER_DEFAULT = "New_Visual_test_output"
REFLECTION_TRACE_WAVELENGTHS_NM = [700.0, 600.0, 750.0, 800.0]

# BO response-surface map settings
BO_X_RANGE = (10.0, 70.0)   # drip_time
BO_Y_RANGE = (0.0, 14.0)    # drip_duration
BO_GRID_N = 420
BO_USE_CAMPAIGN_EXPERIMENTS = True
BO_CLIP_POINTS_TO_PANEL_RANGE = True
BO_OBJECTIVE_MODE = "observation"   # observation | rank_score | hybrid
BO_SURROGATE_STRATEGY = "auto"      # auto | gp_matern_local | gp_poly2_local | gp_rq_local | idw
BO_STRATEGY_CANDIDATES = ("gp_matern_local", "gp_poly2_local", "gp_rq_local")
BO_VISUALIZATION_SURROGATE_ONLY = True
BO_RENDER_MODE = "image"            # image | contourf
BO_IMAGE_INTERPOLATION = "bicubic"
BO_SHOW_MEAN_CONTOURS = False
BO_SHOW_STD_CONTOUR = False
BO_STRIPE_RATIO_WARN = 4.0
BO_STRIPE_RATIO_REJECT = 5.0
BO_HYPER_FREEZE_AFTER = 12
BO_LOCAL_UPDATE_RADIUS = 0.18
BO_FAR_FIELD_INSTABILITY_WEIGHT = 1.25
BO_VIS_LOCAL_BLEND_SIGMA = 0.16
BO_VIS_FAR_BLEND_FLOOR = 0.12
RANK_PIN_COLORS = {
    1: '#440154',  # viridis low
    2: '#31688e',
    3: '#35b779',
    4: '#fde725',  # viridis high
}

# ===========================
# MANUAL TEST INPUTS
# ===========================
# Set these once, then run this script without command-line arguments.
MANUAL_CAMPAIGN_FOLDER = (
    "/Users/alishashaani/Desktop/Courses/NCSU/RC_workspace2/visual output test/Data samples"
)
# Example: ["Campaign_V9_5_GPEI", "Campaign_V9_8_GPEI"]
# Use None to process all campaign JSON files in MANUAL_CAMPAIGN_FOLDER.
MANUAL_INPUTS = None
MANUAL_OUTPUT_SUBFOLDER = "/Users/alishashaani/Desktop/Courses/NCSU/RC_workspace2/visual output test/outputs"


def _drip_anchored_targets(drip_time, drip_duration):
    if drip_time is None:
        return []
    try:
        drip_start = float(drip_time)
    except Exception:
        return []

    targets = [drip_start + SNAPSHOT_PRE_DRIP_OFFSET_S]

    if SNAPSHOT_FIRST_WINDOW_POINTS <= 1:
        targets.append(drip_start)
    else:
        for off in np.linspace(0.0, SNAPSHOT_FIRST_WINDOW_S, SNAPSHOT_FIRST_WINDOW_POINTS):
            targets.append(drip_start + float(off))

    try:
        drip_dur = max(0.0, float(drip_duration))
    except Exception:
        drip_dur = 0.0
    drip_end = drip_start + drip_dur
    targets.append(drip_end + SNAPSHOT_POST_DRIP_END_OFFSET_S)
    return targets


def _nearest_targets(sorted_times, targets, include_last=False):
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


def _finite_xy(x_vals, y_vals):
    x_arr = np.asarray(x_vals, dtype=float)
    y_arr = np.asarray([np.nan if v is None else float(v) for v in y_vals], dtype=float)
    mask = np.isfinite(x_arr) & np.isfinite(y_arr)
    return x_arr[mask], y_arr[mask]


def _relative_time_array(x_vals, drip_time):
    x_arr = np.asarray(x_vals, dtype=float)
    if drip_time is None:
        return x_arr
    try:
        return x_arr - float(drip_time)
    except Exception:
        return x_arr


def _relative_time_label(time_val, drip_time):
    if time_val is None:
        return "N/A"
    try:
        rel_time = float(time_val) - float(drip_time) if drip_time is not None else float(time_val)
        return f"{rel_time:+.2f} s"
    except Exception:
        return "N/A"


def _selected_time_color_map(selected_times, cmap_name='turbo'):
    if not selected_times:
        return {}
    cmap = plt.get_cmap(cmap_name)
    if len(selected_times) == 1:
        return {selected_times[0]: cmap(0.6)}
    color_vals = np.linspace(0.08, 0.92, len(selected_times))
    return {time_val: cmap(color_vals[idx]) for idx, time_val in enumerate(selected_times)}


def _annotate_selected_times_on_contour(ax, selected_times, time_colors=None, fallback_color='k'):
    if not selected_times:
        return
    for time_val in selected_times:
        try:
            x_pos = float(time_val)
        except Exception:
            continue
        arrow_color = fallback_color
        if isinstance(time_colors, dict):
            arrow_color = time_colors.get(time_val, fallback_color)
        ax.annotate(
            '',
            xy=(x_pos, 0.93),
            xytext=(x_pos, 1.03),
            xycoords=('data', 'axes fraction'),
            textcoords=('data', 'axes fraction'),
            arrowprops=dict(
                arrowstyle='-|>',
                color=arrow_color,
                linewidth=0.75,
                shrinkA=0.0,
                shrinkB=0.0,
                mutation_scale=8,
                alpha=0.9,
            ),
            annotation_clip=False,
        )


def _apply_shared_contour_time_axis(axes, time_values):
    if not axes or not time_values:
        return
    finite_times = np.asarray(time_values, dtype=float)
    finite_times = finite_times[np.isfinite(finite_times)]
    if finite_times.size == 0:
        return

    time_min = float(np.min(finite_times))
    time_max = float(np.max(finite_times))
    if time_max <= time_min:
        time_max = time_min + 1e-6

    locator = MaxNLocator(nbins=6)
    for ax in axes:
        ax.set_xlim(time_min, time_max)
        ax.xaxis.set_major_locator(locator)


def _annotate_relative_drip_window(ax, drip_duration):
    try:
        ax.axvline(0.0, color='k', linestyle='--', linewidth=1.0)
        x_left, x_right = ax.get_xlim()
        new_left = min(float(x_left), 0.0)
        new_right = float(x_right)
        if drip_duration is not None:
            drip_end_rel = float(drip_duration)
            ax.axvline(drip_end_rel, color='0.25', linestyle='--', linewidth=1.0)
            new_right = max(new_right, drip_end_rel)
        if new_right <= new_left:
            new_right = new_left + 1e-6
        ax.set_xlim(new_left, new_right)
    except Exception:
        return


def _apply_shared_metric_time_axis(axes, time_arrays, min_left=None, min_right=None):
    if not axes:
        return

    finite_chunks = []
    for arr in time_arrays:
        arr_np = np.asarray(arr, dtype=float)
        arr_np = arr_np[np.isfinite(arr_np)]
        if arr_np.size > 0:
            finite_chunks.append(arr_np)

    if finite_chunks:
        all_times = np.concatenate(finite_chunks)
        x_min = float(np.min(all_times))
        x_max = float(np.max(all_times))
    else:
        x_min, x_max = 0.0, 1.0

    if min_left is not None:
        x_min = min(float(min_left), x_min)
    if min_right is not None:
        x_max = max(float(min_right), x_max)
    if x_max <= x_min:
        x_max = x_min + 1e-6

    locator = MaxNLocator(nbins=5)
    for ax in axes:
        ax.set_xlim(x_min, x_max)
        ax.xaxis.set_major_locator(locator)


def _smooth_axis_if_needed(arr, sigma, axis):
    if sigma is None:
        return arr
    try:
        sigma_val = float(sigma)
    except Exception:
        return arr
    if sigma_val <= 0:
        return arr
    return gaussian_filter1d(arr, sigma=sigma_val, axis=axis)


def _calculate_utility_metrics(master_dict):
    """Standalone V9-style metric extraction for plotting/reporting."""
    tags = master_dict.get('Tags', {})
    film_score = master_dict.get('Film Ranking', {}).get('Score', 0.0)

    drip_time = float(tags.get('Anti-Solvent Drip Time', 0))
    try:
        drip_rate = float(str(tags.get('Anti-Solvent Rate', 0)).replace('MM', '').strip())
    except Exception:
        drip_rate = 0.1
    drip_vol = float(tags.get('Anti-Solvent Volume', 0))

    rate_ul_sec = (drip_rate * 1000.0) / 60.0 if drip_rate > 0 else 0.1
    drip_duration = drip_vol / rate_ul_sec if rate_ul_sec > 0 else None

    norm_drip_time = ((drip_time - 7) / (70 - 7)) * 2 - 1
    norm_drip_rate = ((drip_rate - 0.8) / (15.0 - 0.8)) * 2 - 1
    norm_drip_vol = ((drip_vol - 50) / (500 - 50)) * 2 - 1

    results = {
        'parameter_list': [drip_time, drip_rate, drip_vol],
        'norm_parameters_list': [norm_drip_time, norm_drip_rate, norm_drip_vol],
        'dripTime': drip_time,
        'dripDuration': drip_duration,
        'valid': True,
    }

    dd_pl_measurement = {
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

    wavelengths = master_dict.get('Wavelengths', [])

    if not dd_pl_measurement or (not dd_absorbance and not dd_reflection) or not wavelengths:
        util = UTILITY_WEIGHT_FILM * film_score
        results['utility_value'] = [util]
        results['utility_components'] = {
            0.0: {
                'Utility score': util,
                'Film Score': film_score,
            }
        }
        results['valid'] = False
        return results

    try:
        wavelengths_arr = np.array(wavelengths, dtype=float)

        idx_pl_min = int(np.argmin(np.abs(wavelengths_arr - MIN_WAVELENGTH_PL)))
        idx_pl_max = int(np.argmin(np.abs(wavelengths_arr - MAX_WAVELENGTH_PL)))
        idx_abs_min = int(np.argmin(np.abs(wavelengths_arr - MIN_WAVELENGTH_ABS)))
        idx_abs_max = int(np.argmin(np.abs(wavelengths_arr - MAX_WAVELENGTH_ABS)))

        if idx_pl_min > idx_pl_max:
            idx_pl_min, idx_pl_max = idx_pl_max, idx_pl_min
        if idx_abs_min > idx_abs_max:
            idx_abs_min, idx_abs_max = idx_abs_max, idx_abs_min

        wavelengths_pl = wavelengths[idx_pl_min:idx_pl_max]
        wavelengths_abs = wavelengths[idx_abs_min:idx_abs_max]
        energies_pl = [1239.9 / w for w in wavelengths_pl] if wavelengths_pl else []

        if not wavelengths_abs or not wavelengths_pl:
            raise ValueError('Invalid wavelength slices for PL/Reflection windows.')

        idx_led = min(range(len(wavelengths_abs)), key=lambda i: abs(wavelengths_abs[i] - PL_LED_WAVELENGTH))
        idx_abs_fixed = min(range(len(wavelengths_abs)), key=lambda i: abs(wavelengths_abs[i] - ABS_FIXED_WAVELENGTH))

        dd_pl_correct = {
            k: v[idx_pl_min:idx_pl_max] for k, v in dd_pl_measurement.items()
            if len(v) >= idx_pl_max
        }
        dd_absorbance_w = {
            k: v[idx_abs_min:idx_abs_max] for k, v in dd_absorbance.items()
            if len(v) >= idx_abs_max
        }

        # Recompute absorbance from raw reflection + baselines (unclipped), same as V9.
        dd_absorbance_w_unclipped = {}
        refl_base_full = np.array(dd_reflection_baseline.get('Reflective Baseline', []), dtype=float)
        dark_base_full = np.array(dd_reflection_baseline.get('Black Baseline', []), dtype=float)
        if (
            dd_reflection_raw_counts
            and len(refl_base_full) >= idx_abs_max
            and len(dark_base_full) >= idx_abs_max
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
                dd_absorbance_w_unclipped[k] = abs_unclipped[idx_abs_min:idx_abs_max].tolist()
        dd_absorbance_w_calc = dd_absorbance_w_unclipped if dd_absorbance_w_unclipped else dd_absorbance_w

        # Reflection window from Reflection/Reflection%.
        dd_reflection_w = {}
        for k, v in dd_reflection.items():
            if len(v) < idx_abs_max:
                continue
            spectrum_ref = np.array(v[idx_abs_min:idx_abs_max], dtype=float)
            finite_vals = spectrum_ref[np.isfinite(spectrum_ref)]
            if finite_vals.size > 0 and float(np.nanmedian(finite_vals)) > 2.0:
                spectrum_ref = spectrum_ref / 100.0
            dd_reflection_w[k] = spectrum_ref.tolist()

        # Recompute reflection from raw counts + baselines (unclipped), same as V9 plot source.
        dd_reflection_w_unclipped = {}
        if (
            dd_reflection_raw_counts
            and len(refl_base_full) >= idx_abs_max
            and len(dark_base_full) >= idx_abs_max
        ):
            denom_full = refl_base_full - dark_base_full
            denom_safe = np.where(denom_full > 0, denom_full, np.nan)
            for k, v in dd_reflection_raw_counts.items():
                spectrum_raw = np.array(v, dtype=float)
                if len(spectrum_raw) < idx_abs_max:
                    continue
                with np.errstate(divide='ignore', invalid='ignore'):
                    refl_unclipped = (spectrum_raw - dark_base_full) / denom_safe
                dd_reflection_w_unclipped[k] = refl_unclipped[idx_abs_min:idx_abs_max].tolist()
        dd_reflection_w_calc = dd_reflection_w_unclipped if dd_reflection_w_unclipped else dd_reflection_w

        dd_pl_contour = {k: list(v) for k, v in dd_pl_correct.items()}
        dd_abs_contour = {k: list(v) for k, v in dd_absorbance_w.items()}
        dd_reflection_contour = {k: list(v) for k, v in dd_reflection_w_calc.items()}
        pl_times_full = sorted(dd_pl_contour.keys())
        abs_times_full = sorted(dd_abs_contour.keys())

        pl_times = sorted(dd_pl_correct.keys())
        abs_times = sorted(dd_reflection_w_calc.keys())

        peak_area = []
        led_abs = []
        led_reflection = []
        reflection_avg = []
        peak_energy = []
        fwhm_energy = []
        abs_fixed = []

        for t in pl_times:
            spectrum_pl = np.array(dd_pl_correct[t], dtype=float)
            peak_area.append(float(np.sum(spectrum_pl)))

            if spectrum_pl.size > 0 and np.max(spectrum_pl) > 0:
                idx_max = int(np.argmax(spectrum_pl))
                peak_energy.append(energies_pl[idx_max])
            else:
                peak_energy.append(None)

            if spectrum_pl.size > 0 and np.max(spectrum_pl) > 0:
                half_max = 0.5 * np.max(spectrum_pl)
                above = np.where(spectrum_pl >= half_max)[0]
                if len(above) >= 2:
                    left_idx, right_idx = above[0], above[-1]
                    fwhm_energy.append(energies_pl[left_idx] - energies_pl[right_idx])
                else:
                    fwhm_energy.append(0.0)
            else:
                fwhm_energy.append(0.0)

            if dd_absorbance_w_calc:
                closest_t_abs = min(dd_absorbance_w_calc.keys(), key=lambda x: abs(x - t))
                spectrum_abs = dd_absorbance_w_calc[closest_t_abs]
                led_abs.append(spectrum_abs[idx_led] if idx_led < len(spectrum_abs) else spectrum_abs[-1])
                abs_fixed.append(spectrum_abs[idx_abs_fixed] if idx_abs_fixed < len(spectrum_abs) else spectrum_abs[-1])
            else:
                led_abs.append(0.0)
                abs_fixed.append(0.0)

            if dd_reflection_w_calc:
                closest_t_ref = min(dd_reflection_w_calc.keys(), key=lambda x: abs(x - t))
                spectrum_ref = np.array(dd_reflection_w_calc[closest_t_ref], dtype=float)
                reflection_avg.append(float(np.mean(spectrum_ref)))
                led_reflection.append(float(spectrum_ref[idx_led] if idx_led < len(spectrum_ref) else spectrum_ref[-1]))
            else:
                reflection_avg.append(0.0)
                led_reflection.append(0.0)

        reflection_utility = [max(0.0, min(1.0, 1.0 - r)) for r in reflection_avg]

        plqy = []
        for area, abs_val in zip(peak_area, led_abs):
            plqy_val = (area / abs_val) / PLQY_CONSTANT if abs_val > 0 else 0.0
            plqy.append(plqy_val)
        plqy_utility = [1.0 - max(0.0, min(1.0, v)) for v in plqy]

        utility_value = []
        utility_components_dict = {}
        for i, t in enumerate(pl_times):
            u_refl = reflection_utility[i] if i < len(reflection_utility) else 0.0
            u_plqy = plqy_utility[i] if i < len(plqy_utility) else 0.0
            total_u = (
                UTILITY_WEIGHT_REFLECTION * u_refl
                + UTILITY_WEIGHT_PLQY * u_plqy
                + UTILITY_WEIGHT_FILM * film_score
            )
            utility_value.append(total_u)
            utility_components_dict[t] = {
                'Utility score': total_u,
                'Reflection Utility': u_refl,
                'PLQY Utility': u_plqy,
                'PLQY Actual': plqy[i] if i < len(plqy) else 0.0,
                'Film Score': film_score,
            }

        results.update({
            'utility_value': utility_value,
            'utility_components': utility_components_dict,
            'pl_times': pl_times,
            'wavelengths_pl': wavelengths_pl,
            'wavelengths_abs': wavelengths_abs,
            'dd_plCorrect': dd_pl_correct,
            'dd_absorbanceW': dd_absorbance_w,
            'dd_reflectionW': dd_reflection_w,
            'dd_reflectionW_plot': dd_reflection_w_calc,
            'dd_absorbanceW_plot': dd_absorbance_w_unclipped if dd_absorbance_w_unclipped else dd_absorbance_w,
            'PLQY': plqy,
            'led_abs': led_abs,
            'led_reflection': led_reflection,
            'energies_pl': energies_pl,
            'peak_energy': peak_energy,
            'peak_area': peak_area,
            'fwhm_energy': fwhm_energy,
            'abs_times': abs_times,
            'abs_fixed': abs_fixed,
        })

        results.update({
            'dd_plContour': dd_pl_contour,
            'dd_absContour': dd_abs_contour,
            'dd_reflectionContour': dd_reflection_contour,
            'pl_times_full': pl_times_full,
            'abs_times_full': abs_times_full,
        })
        results['dripDuration'] = drip_duration

    except Exception as e:
        print(f"[Logic Error] Calculation failed: {e}")
        util = UTILITY_WEIGHT_FILM * film_score
        results['utility_value'] = [util]
        results['utility_components'] = {
            0.0: {
                'Utility score': util,
                'Film Score': film_score,
            }
        }
        results['valid'] = False

    return results


def _extract_reflection_trace(abs_times, dd_reflection_w, wavelengths_abs, target_nm):
    if not abs_times or not wavelengths_abs:
        return None, None, np.array([]), np.array([])

    idx = min(range(len(wavelengths_abs)), key=lambda i: abs(wavelengths_abs[i] - target_nm))
    actual_nm = float(wavelengths_abs[idx])

    x_vals, y_vals = [], []
    for t in sorted(abs_times):
        if t not in dd_reflection_w:
            continue
        y = np.asarray(dd_reflection_w[t], dtype=float)
        if idx >= len(y):
            continue
        x_vals.append(float(t))
        y_vals.append(float(y[idx]))

    return idx, actual_nm, np.asarray(x_vals, dtype=float), np.asarray(y_vals, dtype=float)


def _sample_sort_key(name):
    """
    Natural-ish sort for campaign names, prioritizing the numeric token after V9_.
    """
    m = re.search(r'V9_(\d+)', name)
    if m:
        return (int(m.group(1)), name)
    nums = re.findall(r'(\d+)', name)
    if nums:
        return (int(nums[0]), name)
    return (10**9, name)


def _as_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def _parse_rate_mL_min(rate_value):
    if rate_value is None:
        return None
    if isinstance(rate_value, (int, float)):
        return float(rate_value)
    rate_str = str(rate_value).replace('MM', '').strip()
    return _as_float(rate_str, default=None)


def _score_to_rank(score):
    if score is None:
        return None
    targets = [0.0, 0.33, 0.66, 1.0]
    idx = int(np.argmin([abs(float(score) - t) for t in targets]))
    return idx + 1


def _extract_campaign_point(master_dict, file_name):
    tags = master_dict.get('Tags', {})
    params = master_dict.get('Parameters', {})

    drip_time = _as_float(tags.get('Anti-Solvent Drip Time', params.get('Drip Time')), default=None)
    drip_rate = _parse_rate_mL_min(tags.get('Anti-Solvent Rate', params.get('Drip Rate')))
    drip_vol = _as_float(tags.get('Anti-Solvent Volume', params.get('Drip Volume')), default=None)

    drip_duration = None
    if drip_rate is not None and drip_rate > 0 and drip_vol is not None:
        drip_duration = drip_vol / ((drip_rate * 1000.0) / 60.0)

    film_info = master_dict.get('Film Ranking', {})
    film_score = _as_float(film_info.get('Score'), default=None)
    rank_num = _score_to_rank(film_score)
    if rank_num is None:
        rank_text = str(film_info.get('Rank', '')).strip().upper()
        rank_map = {'I': 1, 'II': 2, 'III': 3, 'IV': 4}
        rank_num = rank_map.get(rank_text, None)

    objective_value = None
    # Prefer direct objective fields when present.
    for key in ['objective_value', 'Objective Value', 'observation', 'Observation']:
        if key in master_dict:
            objective_value = _as_float(master_dict.get(key), default=None)
            if objective_value is not None and np.isfinite(objective_value):
                break

    # Fall back to utility score if available in analyzed payloads.
    if objective_value is None:
        util_block = master_dict.get('Utility Components', {})
        if isinstance(util_block, dict) and util_block:
            for _, item in sorted(util_block.items(), key=lambda kv: _as_float(kv[0], default=0.0)):
                if isinstance(item, dict):
                    cand = _as_float(item.get('Utility score'), default=None)
                    if cand is not None and np.isfinite(cand):
                        objective_value = cand

    # Fall back to film score, then rank-normalized score.
    if objective_value is None and film_score is not None and np.isfinite(film_score):
        objective_value = float(film_score)
    if objective_value is None and rank_num is not None:
        objective_value = float(rank_num - 1) / 3.0

    if drip_time is None or drip_duration is None or rank_num is None or objective_value is None:
        return None

    return {
        'name': file_name,
        'drip_time': float(drip_time),
        'drip_duration': float(drip_duration),
        'rank': int(rank_num),
        'objective_value': float(objective_value),
    }


def _target_from_point(point, objective_mode=BO_OBJECTIVE_MODE):
    obj = _as_float(point.get('objective_value'), default=None)
    rank_val = point.get('rank', None)
    rank_score = None
    if rank_val is not None:
        try:
            rank_score = (float(rank_val) - 1.0) / 3.0
        except Exception:
            rank_score = None

    if objective_mode == "rank_score":
        return rank_score
    if objective_mode == "hybrid":
        if obj is None and rank_score is None:
            return None
        if obj is None:
            return rank_score
        if rank_score is None:
            return obj
        return 0.70 * obj + 0.30 * rank_score
    # default: observation / objective
    if obj is not None:
        return obj
    return rank_score


def _objective_limits_from_points(points, objective_mode=BO_OBJECTIVE_MODE):
    vals = [_target_from_point(p, objective_mode=objective_mode) for p in points]
    arr = np.asarray(vals, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0, 1.0

    # Keep native BO semantics stable when objective is normalized.
    if float(np.min(arr)) >= -0.05 and float(np.max(arr)) <= 1.05:
        return 0.0, 1.0

    lo = float(np.quantile(arr, 0.05))
    hi = float(np.quantile(arr, 0.95))
    if hi <= lo:
        lo = float(np.min(arr))
        hi = float(np.max(arr))
    if hi <= lo:
        pad = 1.0 if lo == 0 else abs(lo) * 0.15
        return lo - pad, hi + pad

    pad = 0.08 * (hi - lo)
    return lo - pad, hi + pad


def _normalize_bo_xy(X):
    X = np.asarray(X, dtype=float)
    x_span = max(1e-12, float(BO_X_RANGE[1] - BO_X_RANGE[0]))
    y_span = max(1e-12, float(BO_Y_RANGE[1] - BO_Y_RANGE[0]))
    Xn = np.empty_like(X, dtype=float)
    Xn[:, 0] = (X[:, 0] - float(BO_X_RANGE[0])) / x_span
    Xn[:, 1] = (X[:, 1] - float(BO_Y_RANGE[0])) / y_span
    return Xn


def _build_bo_training_arrays(data, objective_mode=BO_OBJECTIVE_MODE):
    grouped = {}
    for p in data:
        dt = _as_float(p.get('drip_time'), default=None)
        dd = _as_float(p.get('drip_duration'), default=None)
        yy = _target_from_point(p, objective_mode=objective_mode)
        yy = _as_float(yy, default=None)
        if dt is None or dd is None or yy is None:
            continue
        if not np.isfinite(dt) or not np.isfinite(dd) or not np.isfinite(yy):
            continue
        if BO_CLIP_POINTS_TO_PANEL_RANGE:
            dt = float(np.clip(dt, BO_X_RANGE[0], BO_X_RANGE[1]))
            dd = float(np.clip(dd, BO_Y_RANGE[0], BO_Y_RANGE[1]))
        # Collapse exact/near-duplicate campaign coordinates to stabilize GP fitting.
        key = (round(dt, 4), round(dd, 4))
        grouped.setdefault(key, []).append(float(yy))

    if not grouped:
        return np.empty((0, 2), dtype=float), np.empty((0,), dtype=float)
    X_rows = []
    y_rows = []
    for (dt, dd), vals in grouped.items():
        X_rows.append([float(dt), float(dd)])
        y_rows.append(float(np.mean(vals)))
    X_raw = np.asarray(X_rows, dtype=float)
    y_arr = np.asarray(y_rows, dtype=float)
    return X_raw, y_arr


def _safe_gp_fit(gp, X, y):
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ConvergenceWarning)
        gp.fit(X, y)
    return gp


def _fit_gp_bundle(X_norm, y, strategy, prior_kernel=None, freeze_hyper=False):
    y_span = float(np.nanmax(y) - np.nanmin(y)) if y.size > 0 else 0.0
    alpha_val = 1e-4 if y_span <= 1.2 else 5e-4
    normalize_y = True
    restarts = 1 if len(y) < 9 else 2

    if strategy == "gp_matern_local":
        default_kernel = (
            ConstantKernel(1.0, constant_value_bounds=(0.45, 2.6))
            * Matern(
                length_scale=[0.28, 0.24],
                length_scale_bounds=[(0.07, 1.00), (0.06, 0.95)],
                nu=1.5,
            )
            + RationalQuadratic(
                alpha=0.9,
                length_scale=0.35,
                alpha_bounds=(0.2, 3.0),
                length_scale_bounds=(0.09, 1.30),
            )
        )
        kernel = copy.deepcopy(prior_kernel) if prior_kernel is not None else default_kernel
        gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=alpha_val,
            normalize_y=normalize_y,
            optimizer=None if freeze_hyper else "fmin_l_bfgs_b",
            n_restarts_optimizer=0 if freeze_hyper else restarts,
            random_state=42,
        )
        gp = _safe_gp_fit(gp, X_norm, y)
        return {
            "kind": "gp",
            "strategy": strategy,
            "model": gp,
            "featurizer": None,
            "X_train": X_norm,
            "y_train": y,
            "log_ml": float(gp.log_marginal_likelihood_value_),
        }

    if strategy == "gp_rq_local":
        default_kernel = (
            ConstantKernel(1.0, constant_value_bounds=(0.40, 2.8))
            * RationalQuadratic(
                alpha=0.7,
                length_scale=0.30,
                alpha_bounds=(0.15, 4.5),
                length_scale_bounds=(0.07, 1.40),
            )
            + RBF(
                length_scale=[0.40, 0.36],
                length_scale_bounds=[(0.10, 1.35), (0.10, 1.35)],
            )
        )
        kernel = copy.deepcopy(prior_kernel) if prior_kernel is not None else default_kernel
        gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=alpha_val,
            normalize_y=normalize_y,
            optimizer=None if freeze_hyper else "fmin_l_bfgs_b",
            n_restarts_optimizer=0 if freeze_hyper else restarts,
            random_state=42,
        )
        gp = _safe_gp_fit(gp, X_norm, y)
        return {
            "kind": "gp",
            "strategy": strategy,
            "model": gp,
            "featurizer": None,
            "X_train": X_norm,
            "y_train": y,
            "log_ml": float(gp.log_marginal_likelihood_value_),
        }

    if strategy == "gp_poly2_local":
        poly = PolynomialFeatures(degree=2, include_bias=False)
        X_poly = poly.fit_transform(X_norm)
        default_kernel = (
            ConstantKernel(1.0, constant_value_bounds=(0.30, 3.0))
            * RBF(
                length_scale=np.full(X_poly.shape[1], 0.75, dtype=float),
                length_scale_bounds=(0.18, 2.5),
            )
        )
        kernel = copy.deepcopy(prior_kernel) if prior_kernel is not None else default_kernel
        gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=max(alpha_val, 3e-4),
            normalize_y=normalize_y,
            optimizer=None if freeze_hyper else "fmin_l_bfgs_b",
            n_restarts_optimizer=0 if freeze_hyper else 1,
            random_state=42,
        )
        gp = _safe_gp_fit(gp, X_poly, y)
        return {
            "kind": "gp",
            "strategy": strategy,
            "model": gp,
            "featurizer": poly,
            "X_train": X_norm,
            "y_train": y,
            "log_ml": float(gp.log_marginal_likelihood_value_),
        }

    if strategy == "idw":
        return {
            "kind": "idw",
            "strategy": strategy,
            "model": None,
            "featurizer": None,
            "X_train": X_norm,
            "y_train": y,
            "log_ml": np.nan,
        }

    return None


def _predict_bundle(bundle, X_query_norm):
    if bundle is None:
        return None, None

    X_query_norm = np.asarray(X_query_norm, dtype=float)
    kind = bundle.get("kind")

    if kind == "gp":
        model = bundle.get("model")
        feat = bundle.get("featurizer")
        Xq = feat.transform(X_query_norm) if feat is not None else X_query_norm
        with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                mean, std = model.predict(Xq, return_std=True)
        mean = np.nan_to_num(mean, nan=float(np.nanmean(bundle.get("y_train", [0.0]))), posinf=1.0, neginf=0.0)
        std = np.nan_to_num(std, nan=0.0, posinf=0.0, neginf=0.0)
        return mean, std

    if kind == "idw":
        X_train = np.asarray(bundle.get("X_train"), dtype=float)
        y_train = np.asarray(bundle.get("y_train"), dtype=float)
        if X_train.size == 0 or y_train.size == 0:
            return None, None
        diff = X_query_norm[:, None, :] - X_train[None, :, :]
        dist2 = np.sum(diff * diff, axis=2)
        weights = 1.0 / np.power(np.maximum(dist2, 1e-7), 1.15)
        weights = np.clip(weights, 0.0, 1e6)
        wsum = np.sum(weights, axis=1)
        mean = (weights @ y_train) / np.maximum(wsum, 1e-12)
        second = (weights @ (y_train * y_train)) / np.maximum(wsum, 1e-12)
        var = np.maximum(0.0, second - mean * mean)
        return mean, np.sqrt(var)

    return None, None


def _gradient_balance_ratio(z):
    if z is None or not np.isfinite(z).any():
        return np.inf
    dz_dy, dz_dx = np.gradient(z)
    gx = float(np.nanmean(np.abs(dz_dx)))
    gy = float(np.nanmean(np.abs(dz_dy)))
    if not np.isfinite(gx) or not np.isfinite(gy):
        return np.inf
    return max(gx, gy) / max(1e-9, min(gx, gy))


def _surface_style_metrics(z, newest_xy_norm=None):
    if z is None or not np.isfinite(z).any():
        return {
            "ratio": np.inf,
            "band_axis": 1.0,
            "roughness": np.inf,
            "local_resp": 0.0,
        }

    z = np.asarray(z, dtype=float)
    z_min = float(np.nanmin(z))
    z_max = float(np.nanmax(z))
    z_ptp = max(1e-9, z_max - z_min)
    z_norm = (z - z_min) / z_ptp

    gy, gx = np.gradient(z_norm)
    ratio = _gradient_balance_ratio(z_norm)
    axis_dom = np.abs(np.abs(gx) - np.abs(gy)) / (np.abs(gx) + np.abs(gy) + 1e-9)
    band_axis = float(np.nanmean(axis_dom))

    lap = np.gradient(gx, axis=1) + np.gradient(gy, axis=0)
    roughness = float(np.nanmean(np.abs(lap)))

    local_resp = 0.0
    if newest_xy_norm is not None:
        ny = int(np.clip(round(float(newest_xy_norm[1]) * (z.shape[0] - 1)), 0, z.shape[0] - 1))
        nx = int(np.clip(round(float(newest_xy_norm[0]) * (z.shape[1] - 1)), 0, z.shape[1] - 1))
        rad = max(2, int(0.06 * min(z.shape[0], z.shape[1])))
        y0, y1 = max(0, ny - rad), min(z.shape[0], ny + rad + 1)
        x0, x1 = max(0, nx - rad), min(z.shape[1], nx + rad + 1)
        patch = z_norm[y0:y1, x0:x1]
        if patch.size > 4 and np.isfinite(patch).any():
            local_resp = float(np.nanstd(patch))

    return {
        "ratio": ratio,
        "band_axis": band_axis,
        "roughness": roughness,
        "local_resp": local_resp,
    }


def _far_field_instability_score(z_current, z_previous, newest_xy_norm):
    if (
        z_current is None
        or z_previous is None
        or newest_xy_norm is None
        or z_current.shape != z_previous.shape
    ):
        return 0.0, 0.0, 0.0

    z_cur = np.asarray(z_current, dtype=float)
    z_prev = np.asarray(z_previous, dtype=float)
    if not (np.isfinite(z_cur).any() and np.isfinite(z_prev).any()):
        return 0.0, 0.0, 0.0

    h, w = z_cur.shape
    xx = np.linspace(0.0, 1.0, w)
    yy = np.linspace(0.0, 1.0, h)
    gx, gy = np.meshgrid(xx, yy)
    dist = np.sqrt((gx - float(newest_xy_norm[0])) ** 2 + (gy - float(newest_xy_norm[1])) ** 2)
    local_mask = dist <= float(BO_LOCAL_UPDATE_RADIUS)
    far_mask = ~local_mask

    delta = np.abs(z_cur - z_prev)
    if not np.isfinite(delta).any():
        return 0.0, 0.0, 0.0

    far_change = float(np.nanmean(delta[far_mask])) if np.any(far_mask) else 0.0
    local_change = float(np.nanmean(delta[local_mask])) if np.any(local_mask) else 0.0
    disproportion = max(0.0, far_change - 0.7 * local_change)
    return far_change, local_change, disproportion


def _strategy_fit_score(bundle, X_norm, y, newest_xy_norm=None, prev_surface=None):
    pred_train, _ = _predict_bundle(bundle, X_norm)
    if pred_train is None:
        return np.inf
    rmse = float(np.sqrt(np.mean((pred_train - y) ** 2)))

    # Evaluate surface quality (not only train fit) to match native panel behavior.
    gx = np.linspace(BO_X_RANGE[0], BO_X_RANGE[1], 120)
    gy = np.linspace(BO_Y_RANGE[0], BO_Y_RANGE[1], 120)
    gX, gY = np.meshgrid(gx, gy)
    X_preview = np.column_stack([gX.ravel(), gY.ravel()])
    z_pred, _ = _predict_bundle(bundle, _normalize_bo_xy(X_preview))
    if z_pred is None:
        return np.inf
    z_preview = z_pred.reshape(gX.shape)
    metrics = _surface_style_metrics(z_preview, newest_xy_norm=newest_xy_norm)
    ratio = metrics["ratio"]
    band_axis = metrics["band_axis"]
    roughness = metrics["roughness"]
    local_resp = metrics["local_resp"]

    if np.isfinite(ratio) and ratio > BO_STRIPE_RATIO_REJECT and len(y) >= 6:
        return np.inf

    aniso_penalty = (
        0.22 * max(0.0, ratio - BO_STRIPE_RATIO_WARN)
        if np.isfinite(ratio) else 1.5
    )
    band_penalty = 0.55 * max(0.0, band_axis - 0.52)
    # Keep transitions smooth but not over-flat.
    rough_penalty = 0.85 * max(0.0, roughness - 0.12)
    flat_penalty = 0.90 * max(0.0, 0.025 - local_resp)

    far_change, local_change, disproportion = _far_field_instability_score(
        z_current=z_preview,
        z_previous=prev_surface,
        newest_xy_norm=newest_xy_norm,
    )
    far_penalty = BO_FAR_FIELD_INSTABILITY_WEIGHT * (far_change + 1.6 * disproportion)

    lml = bundle.get("log_ml", np.nan)
    lml_bonus = 0.0 if not np.isfinite(lml) else (-0.0012 * lml / max(1.0, float(len(y))))
    kind_penalty = 0.20 if bundle.get("kind") == "idw" and len(y) >= 6 else 0.0
    return (
        rmse
        + aniso_penalty
        + band_penalty
        + rough_penalty
        + flat_penalty
        + far_penalty
        + lml_bonus
        + kind_penalty
    )


def choose_surrogate_strategy(
    data,
    objective_mode=BO_OBJECTIVE_MODE,
    candidates=BO_STRATEGY_CANDIDATES,
    bo_state=None,
):
    X_raw, y = _build_bo_training_arrays(data, objective_mode=objective_mode)
    if len(y) < 2:
        return "idw"
    X_norm = _normalize_bo_xy(X_raw)
    newest = data[-1] if data else None
    newest_xy_norm = None
    if newest is not None:
        newest_xy_norm = _normalize_bo_xy(
            np.asarray([[newest.get('drip_time', 0.0), newest.get('drip_duration', 0.0)]], dtype=float)
        )[0]
    prev_surface = None
    kernel_cache = {}
    if isinstance(bo_state, dict):
        prev_surface = bo_state.get("prev_surface", None)
        kernel_cache = bo_state.setdefault("kernel_cache", {})

    best_name = None
    best_score = np.inf
    best_gp_name = None
    best_gp_score = np.inf
    for name in candidates:
        try:
            prior_kernel = kernel_cache.get(name, None)
            freeze_hyper = bool(len(y) >= BO_HYPER_FREEZE_AFTER and prior_kernel is not None)
            bundle = _fit_gp_bundle(
                X_norm,
                y,
                strategy=name,
                prior_kernel=prior_kernel,
                freeze_hyper=freeze_hyper,
            )
            if bundle is None:
                continue
            score = _strategy_fit_score(
                bundle,
                X_norm,
                y,
                newest_xy_norm=newest_xy_norm,
                prev_surface=prev_surface,
            )
            if bundle.get("kind") == "gp" and bundle.get("model") is not None:
                kernel_cache[name] = copy.deepcopy(bundle["model"].kernel_)
            if score < best_score:
                best_score = score
                best_name = name
            if bundle.get("kind") == "gp" and score < best_gp_score:
                best_gp_score = score
                best_gp_name = name
        except Exception:
            continue
    if best_gp_name is not None:
        return best_gp_name
    return best_name if best_name is not None else "gp_matern_local"


def fit_surrogate_model(
    data,
    strategy=BO_SURROGATE_STRATEGY,
    objective_mode=BO_OBJECTIVE_MODE,
    bo_state=None,
):
    X_raw, y = _build_bo_training_arrays(data, objective_mode=objective_mode)
    if len(y) < 2:
        return None
    X_norm = _normalize_bo_xy(X_raw)

    strategy_name = strategy
    if strategy_name == "auto":
        strategy_name = choose_surrogate_strategy(
            data=data,
            objective_mode=objective_mode,
            candidates=BO_STRATEGY_CANDIDATES,
            bo_state=bo_state,
        )

    kernel_cache = {}
    if isinstance(bo_state, dict):
        kernel_cache = bo_state.setdefault("kernel_cache", {})
    prior_kernel = kernel_cache.get(strategy_name, None)
    freeze_hyper = bool(len(y) >= BO_HYPER_FREEZE_AFTER and prior_kernel is not None)
    bundle = _fit_gp_bundle(
        X_norm,
        y,
        strategy=strategy_name,
        prior_kernel=prior_kernel,
        freeze_hyper=freeze_hyper,
    )
    if (
        isinstance(bo_state, dict)
        and isinstance(bundle, dict)
        and bundle.get("kind") == "gp"
        and bundle.get("model") is not None
    ):
        kernel_cache[strategy_name] = copy.deepcopy(bundle["model"].kernel_)
    return bundle


def predict_on_grid(model_bundle, x_range, y_range, n_grid=BO_GRID_N):
    gx = np.linspace(float(x_range[0]), float(x_range[1]), int(n_grid))
    gy = np.linspace(float(y_range[0]), float(y_range[1]), int(n_grid))
    grid_x, grid_y = np.meshgrid(gx, gy)

    if model_bundle is None:
        return grid_x, grid_y, None, None

    grid_points = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    z_mean, z_std = _predict_bundle(model_bundle, _normalize_bo_xy(grid_points))
    if z_mean is None:
        return grid_x, grid_y, None, None
    return grid_x, grid_y, z_mean.reshape(grid_x.shape), z_std.reshape(grid_x.shape)


def plot_campaign_surface(
    ax,
    data,
    step_idx,
    total_steps,
    objective_limits=None,
    x_range=BO_X_RANGE,
    y_range=BO_Y_RANGE,
    n_grid=BO_GRID_N,
    strategy=BO_SURROGATE_STRATEGY,
    objective_mode=BO_OBJECTIVE_MODE,
    bo_state=None,
    update_state=False,
):
    if not data:
        ax.text(0.5, 0.5, 'NO CAMPAIGN DATA', ha='center', va='center', fontsize=7)
        ax.axis('off')
        return None

    model_bundle = fit_surrogate_model(
        data=data,
        strategy=strategy,
        objective_mode=objective_mode,
        bo_state=bo_state,
    )
    grid_x, grid_y, z_mean, z_std = predict_on_grid(
        model_bundle,
        x_range=x_range,
        y_range=y_range,
        n_grid=n_grid,
    )

    y_vals = np.asarray([_target_from_point(p, objective_mode=objective_mode) for p in data], dtype=float)
    finite_y = y_vals[np.isfinite(y_vals)]
    if finite_y.size == 0:
        finite_y = np.array([0.0], dtype=float)

    if z_mean is None:
        z_mean = np.full_like(grid_x, float(np.mean(finite_y)))
        z_std = np.full_like(grid_x, np.nan)

    if objective_limits is None:
        vmin, vmax = _objective_limits_from_points(data, objective_mode=objective_mode)
    else:
        vmin, vmax = float(objective_limits[0]), float(objective_limits[1])
    if vmax <= vmin:
        vmax = vmin + 1e-6

    n_pts = len(data)
    newest = data[-1]
    newest_x = float(np.clip(newest['drip_time'], x_range[0], x_range[1]))
    newest_y = float(np.clip(newest['drip_duration'], y_range[0], y_range[1]))

    if n_pts < 5:
        n_levels = 14
        note = 'Early campaign: sparse data'
        z_show = gaussian_filter1d(gaussian_filter1d(z_mean, sigma=0.50, axis=0), sigma=0.50, axis=1)
    elif n_pts < 15:
        n_levels = 22
        note = 'Intermediate campaign'
        z_show = gaussian_filter1d(gaussian_filter1d(z_mean, sigma=0.45, axis=0), sigma=0.45, axis=1)
    else:
        n_levels = 30
        note = 'Mature campaign'
        z_show = gaussian_filter1d(gaussian_filter1d(z_mean, sigma=0.35, axis=0), sigma=0.35, axis=1)

    z_show = np.clip(z_show, vmin, vmax)
    # Visualization-specific conservative blend: local updates stay local, far-field remains stable.
    prev_surface = None
    if isinstance(bo_state, dict):
        prev_surface = bo_state.get("prev_surface", None)
    if (
        BO_VISUALIZATION_SURROGATE_ONLY
        and prev_surface is not None
        and isinstance(prev_surface, np.ndarray)
        and prev_surface.shape == z_show.shape
        and step_idx > 1
    ):
        x_norm = (grid_x - float(x_range[0])) / max(1e-9, float(x_range[1] - x_range[0]))
        y_norm = (grid_y - float(y_range[0])) / max(1e-9, float(y_range[1] - y_range[0]))
        nx = (newest_x - float(x_range[0])) / max(1e-9, float(x_range[1] - x_range[0]))
        ny = (newest_y - float(y_range[0])) / max(1e-9, float(y_range[1] - y_range[0]))
        dist = np.sqrt((x_norm - nx) ** 2 + (y_norm - ny) ** 2)
        local_w = np.exp(-(dist ** 2) / max(1e-9, 2.0 * BO_VIS_LOCAL_BLEND_SIGMA ** 2))
        blend_w = BO_VIS_FAR_BLEND_FLOOR + (1.0 - BO_VIS_FAR_BLEND_FLOOR) * local_w
        z_show = blend_w * z_show + (1.0 - blend_w) * prev_surface
        z_show = np.clip(z_show, vmin, vmax)

    contour_levels = np.linspace(vmin, vmax, n_levels)

    if BO_RENDER_MODE == "contourf":
        artist = ax.contourf(
            grid_x,
            grid_y,
            z_show,
            levels=contour_levels,
            cmap='viridis',
            antialiased=True,
        )
    else:
        artist = ax.imshow(
            z_show,
            origin='lower',
            extent=(x_range[0], x_range[1], y_range[0], y_range[1]),
            cmap='viridis',
            vmin=vmin,
            vmax=vmax,
            interpolation=BO_IMAGE_INTERPOLATION,
            aspect='auto',
        )
        if BO_SHOW_MEAN_CONTOURS:
            ax.contour(
                grid_x,
                grid_y,
                z_show,
                levels=np.linspace(vmin, vmax, min(10, n_levels)),
                colors='k',
                linewidths=0.20,
                alpha=0.15,
            )

    if BO_SHOW_STD_CONTOUR and z_std is not None and np.isfinite(z_std).any() and n_pts < 12:
        std_q = 75 if n_pts < 8 else 85
        std_level = float(np.nanpercentile(z_std, std_q))
        if np.isfinite(std_level) and std_level > 0:
            ax.contour(
                grid_x,
                grid_y,
                z_std,
                levels=[std_level],
                colors='white',
                linewidths=0.65,
                linestyles='--',
                alpha=0.72,
            )

    x_hist = np.asarray([_as_float(p.get('drip_time'), default=np.nan) for p in data], dtype=float)
    y_hist = np.asarray([_as_float(p.get('drip_duration'), default=np.nan) for p in data], dtype=float)
    if BO_CLIP_POINTS_TO_PANEL_RANGE:
        x_hist = np.clip(x_hist, x_range[0], x_range[1])
        y_hist = np.clip(y_hist, y_range[0], y_range[1])
    r_hist = np.asarray([int(p.get('rank', 1)) for p in data], dtype=int)
    c_hist = [RANK_PIN_COLORS.get(int(r), '#888888') for r in r_hist]

    if len(data) > 1:
        ax.scatter(
            x_hist[:-1],
            y_hist[:-1],
            s=18,
            c=c_hist[:-1],
            edgecolor='k',
            linewidth=0.30,
            alpha=0.95,
            zorder=5,
        )

    newest_c = RANK_PIN_COLORS.get(int(newest.get('rank', 1)), '#888888')
    ax.scatter(
        newest_x,
        newest_y,
        s=35,
        c=[newest_c],
        marker='o',
        edgecolor='white',
        linewidth=0.75,
        zorder=8,
    )
    ax.scatter(
        newest_x,
        newest_y,
        s=39,
        c='none',
        marker='o',
        edgecolor='k',
        linewidth=0.45,
        zorder=9,
    )

    if np.isfinite(y_vals).any():
        best_idx = int(np.nanargmax(y_vals))
    else:
        best_idx = 0
    best_point = data[best_idx]
    best_x = float(np.clip(best_point['drip_time'], x_range[0], x_range[1]))
    best_y = float(np.clip(best_point['drip_duration'], y_range[0], y_range[1]))
    ax.scatter(
        best_x,
        best_y,
        s=56,
        marker='*',
        c='gold',
        edgecolor='k',
        linewidth=0.45,
        zorder=10,
    )

    ax.set_xlim(*x_range)
    ax.set_ylim(*y_range)
    ax.set_xlabel('Drip Time (s)', fontsize=6.4)
    ax.set_ylabel('Drip Duration (s)', fontsize=6.4)
    ax.set_title('Reduced Dimensionality BO Predictions', fontsize=7.1, pad=2)
    ax.tick_params(labelsize=5.6, length=2.0)
    ax.grid(False)

    step_txt = f"Sample {int(step_idx):02d}/{int(total_steps):02d}"
    label = (
        f"{step_txt}\n"
        f"Best: {best_point['objective_value']:.2f} @ ({best_point['drip_time']:.1f}, {best_point['drip_duration']:.2f})\n"
        f"Newest: ({newest['drip_time']:.1f}, {newest['drip_duration']:.2f}) | Rank {int(newest.get('rank', 1))}\n"
        f"{note}"
    )
    ax.text(
        0.02,
        0.98,
        label,
        transform=ax.transAxes,
        ha='left',
        va='top',
        fontsize=5.2,
        bbox=dict(boxstyle='round,pad=0.18', fc='white', ec='0.45', lw=0.45, alpha=0.87),
    )

    rank_handles = [
        Line2D(
            [0], [0], marker='o', color='none',
            markerfacecolor=RANK_PIN_COLORS[r], markeredgecolor='k',
            markeredgewidth=0.3, markersize=4.1, label=f'Rank {r}'
        )
        for r in [1, 2, 3, 4]
    ]
    style_handles = [
        Line2D([0], [0], marker='o', color='none', markerfacecolor='white', markeredgecolor='k',
               markeredgewidth=0.45, markersize=4.5, label='Newest'),
        Line2D([0], [0], marker='*', color='none', markerfacecolor='gold', markeredgecolor='k',
               markeredgewidth=0.40, markersize=5.8, label='Best'),
    ]
    ax.legend(
        handles=rank_handles + style_handles,
        title='Samples',
        title_fontsize=5.6,
        fontsize=5.0,
        loc='lower left',
        framealpha=0.90,
        borderpad=0.18,
        handletextpad=0.25,
        labelspacing=0.17,
        borderaxespad=0.18,
    )

    # Expose chosen surrogate in tiny footer for debugging/monitoring consistency.
    strategy_used = model_bundle.get("strategy") if isinstance(model_bundle, dict) else "none"
    ax.text(
        0.985, 0.01,
        f"{objective_mode} | {strategy_used}",
        transform=ax.transAxes,
        ha='right',
        va='bottom',
        fontsize=4.6,
        color='0.25',
    )
    if isinstance(bo_state, dict) and update_state:
        bo_state["prev_surface"] = np.array(z_show, dtype=float)
        bo_state["prev_step"] = int(step_idx)
        bo_state["last_newest_xy"] = (float(newest_x), float(newest_y))
    return artist


def _plot_campaign_evolution(
    ax,
    history_points,
    all_points,
    step_idx,
    total_steps,
    objective_limits=None,
    bo_strategy=BO_SURROGATE_STRATEGY,
    objective_mode=BO_OBJECTIVE_MODE,
    bo_state=None,
    update_state=False,
):
    artist = plot_campaign_surface(
        ax=ax,
        data=history_points,
        step_idx=step_idx,
        total_steps=total_steps,
        objective_limits=objective_limits,
        strategy=bo_strategy,
        objective_mode=objective_mode,
        bo_state=bo_state,
        update_state=update_state,
    )
    if artist is not None:
        cax = inset_axes(
            ax,
            width="3.4%",
            height="84%",
            loc='lower left',
            bbox_to_anchor=(1.02, 0.08, 1, 1),
            bbox_transform=ax.transAxes,
            borderpad=0.0,
        )
        cbar = ax.figure.colorbar(artist, cax=cax)
        cbar.set_label('Objective', fontsize=5.8)
        cbar.ax.tick_params(labelsize=5.0, width=0.4, length=1.7)


def _generate_plots_new(
    master_dict,
    results,
    output_folder,
    source_folder,
    file_name,
    history_points,
    all_points,
    step_idx,
    total_steps,
    objective_limits,
    bo_strategy,
    objective_mode,
    bo_state,
):
    if not results or 'utility_value' not in results:
        return

    try:
        style.use('default')
        fig = plt.figure(figsize=(12, 6), constrained_layout=True)
        gs = GridSpec(4, 4, figure=fig)

        plt1 = fig.add_subplot(gs[0:2, 0])
        plt2 = fig.add_subplot(gs[0:2, 1])
        plt4 = fig.add_subplot(gs[2:4, 0])
        plt5 = fig.add_subplot(gs[2:4, 1])
        plt7 = fig.add_subplot(gs[2:4, 3])
        plt8 = fig.add_subplot(gs[0:2, 3])

        # Keep V9 panel structure for top-middle plots.
        plt3a = fig.add_subplot(gs[0, 2])
        plt3b = fig.add_subplot(gs[1, 2])

        bottom_mid = gs[2:4, 2].subgridspec(4, 1, hspace=0.08)
        refl_axes = [
            fig.add_subplot(bottom_mid[0, 0]),
            fig.add_subplot(bottom_mid[1, 0]),
            fig.add_subplot(bottom_mid[2, 0]),
            fig.add_subplot(bottom_mid[3, 0]),
        ]

        tags = master_dict.get('Tags', {})
        drip_time = results.get('dripTime', tags.get('Anti-Solvent Drip Time'))
        drip_rate = results.get('parameter_list', [None, None, None])[1]
        drip_vol = results.get('parameter_list', [None, None, None])[2]
        drip_duration = results.get('dripDuration', None)
        drip_end_time = None
        try:
            if drip_time is not None and drip_duration is not None:
                drip_end_time = float(drip_time) + float(drip_duration)
        except Exception:
            drip_end_time = None
        film_info = master_dict.get('Film Ranking', {})
        film_rank = film_info.get('Rank', 'N/A')
        final_u = results['utility_value'][-1]

        def _fmt(val, suffix=''):
            try:
                return f"{float(val):.2f}{suffix}"
            except Exception:
                return f"N/A{suffix}"

        title_fig = (
            f"{file_name} | Drip Time: {_fmt(drip_time)} s | "
            f"Rate: {_fmt(drip_rate)} mL/min | "
            f"Volume: {_fmt(drip_vol)} uL | "
            f"Duration: {_fmt(drip_duration)} s\n"
            f"Film Rank: {film_rank} | Utility: {final_u:.2f}"
        )
        fig.suptitle(title_fig, fontsize=13)

        pl_times = sorted(results.get('pl_times', []))
        abs_times = sorted(results.get('abs_times', []))
        pl_times_full = sorted(results.get('pl_times_full', pl_times))
        abs_times_full = sorted(results.get('abs_times_full', abs_times))

        wavelengths_pl = results.get('wavelengths_pl', [])
        wavelengths_abs = results.get('wavelengths_abs', [])
        dd_pl_correct = results.get('dd_plCorrect', {})
        dd_pl_contour = results.get('dd_plContour', dd_pl_correct)
        dd_reflection_w_plot = results.get('dd_reflectionW_plot', results.get('dd_reflectionW', {}))
        dd_reflection_contour = results.get('dd_reflectionContour', dd_reflection_w_plot)
        energies_pl = results.get('energies_pl', [])

        peak_energy = results.get('peak_energy', [])
        peak_area = results.get('peak_area', [])

        drip_idx_pl = 0
        drip_idx_abs = 0
        if pl_times and drip_time is not None:
            drip_idx_pl = min(range(len(pl_times)), key=lambda i: abs(pl_times[i] - drip_time))
        if abs_times and drip_time is not None:
            drip_idx_abs = min(range(len(abs_times)), key=lambda i: abs(abs_times[i] - drip_time))

        snapshot_targets = _drip_anchored_targets(drip_time, drip_duration)
        pl_selected = _nearest_targets(pl_times, snapshot_targets, include_last=False)
        refl_selected = _nearest_targets(abs_times, snapshot_targets, include_last=False)
        pl_time_colors = _selected_time_color_map(pl_selected)
        refl_time_colors = _selected_time_color_map(refl_selected)
        contour_time_values = list(pl_times_full) + list(abs_times_full)

        # Plot 1
        if pl_selected and dd_pl_correct and wavelengths_pl:
            for k in pl_selected:
                if k in dd_pl_correct:
                    plt1.plot(
                        wavelengths_pl,
                        dd_pl_correct[k],
                        color=pl_time_colors.get(k),
                        label=_relative_time_label(k, drip_time),
                    )
            leg1 = plt1.legend(prop={'size': 5}, title='Time from Drip')
            if leg1 is not None:
                leg1.get_title().set_fontsize(6)
            plt1.set_title('PL at Selected Times')
            plt1.set_xlabel('Wavelength (nm)')
            plt1.set_ylabel('PL Count')
        else:
            plt1.text(0.5, 0.5, 'NO PL DATA', ha='center', va='center')
            plt1.axis('off')

        # Plot 2 + drip line
        if pl_times_full and energies_pl and dd_pl_contour:
            df_pl = pd.DataFrame.from_dict(dict(sorted(dd_pl_contour.items())))
            X, Y = np.meshgrid(sorted(df_pl.columns), energies_pl)
            Z = np.array(df_pl)
            Z = _smooth_axis_if_needed(Z, PL_CONTOUR_SMOOTH_SIGMA_WAVELENGTH, axis=0)
            Z = _smooth_axis_if_needed(Z, PL_CONTOUR_SMOOTH_SIGMA_TIME, axis=1)
            zmin, zmax = float(np.min(Z)), float(np.max(Z))
            if zmax <= zmin:
                zmax = zmin + 1e-6
            levels = np.linspace(zmin, zmax, 256)
            contour_plot = plt2.contourf(X, Y, Z, levels=levels, cmap=cm.rainbow)
            cp_bar = fig.colorbar(contour_plot, ax=plt2)
            if drip_time is not None:
                plt2.axvline(float(drip_time), color='k', linestyle='--', linewidth=1.2)
            if drip_end_time is not None:
                plt2.axvline(float(drip_end_time), color='0.25', linestyle='--', linewidth=1.2)
            _annotate_selected_times_on_contour(plt2, pl_selected, time_colors=pl_time_colors)
            plt2.set_title('PL Intensity contour vs Time')
            plt2.set_xlabel('Time (seconds)')
            plt2.set_ylabel('PL Energy (eV)')
            cp_bar.ax.set_ylabel('PL Intensity (a.u.)')
        else:
            plt2.text(0.5, 0.5, 'NO PL DATA', ha='center', va='center')
            plt2.axis('off')

        metric_time_arrays = []

        # Plot 3a
        if peak_energy and pl_times:
            x_e, y_e = _finite_xy(pl_times[drip_idx_pl:], peak_energy[drip_idx_pl:])
            if y_e.size > 0:
                x_e = _relative_time_array(x_e, drip_time)
                metric_time_arrays.append(x_e)
                y_plot = gaussian_filter1d(y_e, sigma=5) if y_e.size >= 3 else y_e
                plt3a.plot(x_e, y_plot)
                _annotate_relative_drip_window(plt3a, drip_duration)
                plt3a.set_title(f'Final Peak: {y_e[-1]:.2f} eV', fontsize=8)
                plt3a.set_ylabel('Energy (eV)', fontsize=8)
                plt3a.tick_params(labelsize=7)
                plt3a.set_xlabel('Time from Drip (s)', fontsize=8)
            else:
                plt3a.text(0.5, 0.5, 'N/A', ha='center', va='center')
                plt3a.axis('off')
        else:
            plt3a.text(0.5, 0.5, 'N/A', ha='center', va='center')
            plt3a.axis('off')

        # Plot 3b
        if peak_area and pl_times:
            x_a, y_a = _finite_xy(pl_times[drip_idx_pl:], peak_area[drip_idx_pl:])
            if y_a.size > 0:
                x_a = _relative_time_array(x_a, drip_time)
                metric_time_arrays.append(x_a)
                y_plot = gaussian_filter1d(y_a, sigma=2) if y_a.size >= 3 else y_a
                plt3b.plot(x_a, y_plot)
                _annotate_relative_drip_window(plt3b, drip_duration)
                plt3b.set_title('PL Peak Area', fontsize=8)
                plt3b.set_ylabel('PLn (a.u.)', fontsize=8)
                plt3b.set_xlabel('Time from Drip (s)', fontsize=8)
                plt3b.tick_params(labelsize=7)
            else:
                plt3b.text(0.5, 0.5, 'N/A', ha='center', va='center')
                plt3b.axis('off')
        else:
            plt3b.text(0.5, 0.5, 'N/A', ha='center', va='center')
            plt3b.axis('off')

        # Plot 4
        if refl_selected and dd_reflection_w_plot and wavelengths_abs:
            for k in refl_selected:
                if k not in dd_reflection_w_plot:
                    continue
                y = np.array(dd_reflection_w_plot[k], dtype=float)
                if ABS_LINE_SMOOTH_SIGMA > 0 and np.all(np.isfinite(y)):
                    y = gaussian_filter1d(y, sigma=ABS_LINE_SMOOTH_SIGMA)
                plt4.plot(
                    wavelengths_abs,
                    y,
                    color=refl_time_colors.get(k),
                    label=_relative_time_label(k, drip_time),
                )
            leg4 = plt4.legend(prop={'size': 5}, title='Time from Drip')
            if leg4 is not None:
                leg4.get_title().set_fontsize(6)
            plt4.set_title('Reflection at Selected Times')
            plt4.set_xlabel('Wavelength (nm)')
            plt4.set_ylabel('Reflection (R)')
        else:
            plt4.text(0.5, 0.5, 'NO REFLECTION DATA', ha='center', va='center')
            plt4.axis('off')

        # Plot 5: 400-900 and drip line
        if dd_reflection_contour and wavelengths_abs:
            df_refl = pd.DataFrame.from_dict(dict(sorted(dd_reflection_contour.items())))
            refl_times_sorted = sorted(df_refl.columns)
            X, Y = np.meshgrid(refl_times_sorted, wavelengths_abs)
            Z = np.array(df_refl, dtype=float)
            if np.isfinite(Z).any():
                if not np.all(np.isfinite(Z)):
                    finite_vals = Z[np.isfinite(Z)]
                    fill_val = float(np.median(finite_vals)) if finite_vals.size > 0 else 0.0
                    Z = np.where(np.isfinite(Z), Z, fill_val)
                Z = _smooth_axis_if_needed(Z, REFL_CONTOUR_SMOOTH_SIGMA_WAVELENGTH, axis=0)
                Z = _smooth_axis_if_needed(Z, REFL_CONTOUR_SMOOTH_SIGMA_TIME, axis=1)
                zmin, zmax = float(np.min(Z)), float(np.max(Z))
                if zmax <= zmin:
                    zmax = zmin + 1e-6
                levels = np.linspace(zmin, zmax, 256)
                contour_plot = plt5.contourf(X, Y, Z, levels=levels, cmap=cm.rainbow)
                cp_bar = fig.colorbar(contour_plot, ax=plt5)
                if drip_time is not None:
                    plt5.axvline(float(drip_time), color='k', linestyle='--', linewidth=1.2)
                if drip_end_time is not None:
                    plt5.axvline(float(drip_end_time), color='0.25', linestyle='--', linewidth=1.2)
                _annotate_selected_times_on_contour(plt5, refl_selected, time_colors=refl_time_colors)
                plt5.set_ylim(400, 900)
                plt5.set_title('Reflection contour vs Time')
                plt5.set_xlabel('Time (seconds)')
                plt5.set_ylabel('Wavelength (nm)')
                cp_bar.ax.set_ylabel('Reflection (R)')
            else:
                plt5.text(0.5, 0.5, 'NO REFLECTION DATA', ha='center', va='center')
                plt5.axis('off')
        else:
            plt5.text(0.5, 0.5, 'NO REFLECTION DATA', ha='center', va='center')
            plt5.axis('off')

        _apply_shared_contour_time_axis([plt2, plt5], contour_time_values)

        # Replace old 6a/6b with 4 stacked reflection-vs-time traces
        for i, target_nm in enumerate(REFLECTION_TRACE_WAVELENGTHS_NM):
            ax = refl_axes[i]
            _, actual_nm, x_r, y_r = _extract_reflection_trace(
                abs_times, dd_reflection_w_plot, wavelengths_abs, target_nm
            )

            if x_r.size > 0 and y_r.size > 0:
                x_rel = _relative_time_array(x_r, drip_time)
                mask = np.isfinite(x_rel) & np.isfinite(y_r) & (x_rel >= SNAPSHOT_PRE_DRIP_OFFSET_S)
                if np.any(mask):
                    x_plot = x_rel[mask]
                    y_plot = y_r[mask]
                else:
                    x_plot = x_rel
                    y_plot = y_r
                metric_time_arrays.append(x_plot)
                ax.plot(x_plot, y_plot)
                _annotate_relative_drip_window(ax, drip_duration)
                if actual_nm is not None:
                    ax.set_title(f"Reflection at {actual_nm:.1f} nm", fontsize=8)
                else:
                    ax.set_title(f"Reflection at {target_nm:.1f} nm", fontsize=8)
                ax.tick_params(labelsize=7)
                if i < len(refl_axes) - 1:
                    ax.set_xticklabels([])
                else:
                    ax.set_xlabel('Time from Drip (s)', fontsize=8)
            else:
                ax.text(0.5, 0.5, 'N/A', ha='center', va='center')
                ax.axis('off')

        _apply_shared_metric_time_axis(
            [plt3a, plt3b] + refl_axes,
            metric_time_arrays,
            min_left=SNAPSHOT_PRE_DRIP_OFFSET_S,
            min_right=drip_duration,
        )

        # Plot 7: campaign evolution map (stepwise accumulation, GP surrogate mean).
        _plot_campaign_evolution(
            plt7,
            history_points,
            all_points,
            step_idx=step_idx,
            total_steps=total_steps,
            objective_limits=objective_limits,
            bo_strategy=bo_strategy,
            objective_mode=objective_mode,
            bo_state=bo_state,
            update_state=False,
        )

        # Plot 8: Film image
        img_path = os.path.join(source_folder, 'images', film_info.get('Image Name', ''))
        if os.path.exists(img_path):
            img = cv2.imread(img_path)
            if img is not None:
                plt8.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                plt8.axis('off')
                plt8.text(
                    0.5,
                    -0.06,
                    f"Film Rank {film_rank}",
                    transform=plt8.transAxes,
                    ha='center',
                    va='top',
                    fontsize=10,
                )
            else:
                plt8.text(0.5, 0.5, 'IMAGE READ ERROR', ha='center', va='center')
                plt8.axis('off')
        else:
            plt8.text(0.5, 0.5, 'IMAGE NOT FOUND', ha='center', va='center')
            plt8.axis('off')

        os.makedirs(output_folder, exist_ok=True)
        save_path = os.path.join(output_folder, file_name + OUTPUT_SUFFIX)
        plt.savefig(save_path, dpi=OUTPUT_DPI)
        print(f"Saved alt visual report: {save_path}")
        if SHOW_PLOTS >= 1:
            plt.show()
        plt.close(fig)

    except Exception as e:
        print(f"[New_Visual_test Plot Error] {e}")
        traceback.print_exc()


def _prepare_master_dict(json_path):
    with open(json_path, 'r') as f:
        return json.load(f)


def _get_file_name_base(json_path):
    stem = os.path.splitext(os.path.basename(json_path))[0]
    return stem[: -len('_analyzed')] if stem.endswith('_analyzed') else stem


def _resolve_inputs(campaign_folder, inputs):
    if inputs:
        resolved = []
        for item in inputs:
            if os.path.isabs(item) and os.path.exists(item):
                resolved.append(item)
                continue
            direct = os.path.join(campaign_folder, item)
            if os.path.exists(direct):
                resolved.append(direct)
                continue
            if not item.endswith('.json'):
                c1 = os.path.join(campaign_folder, item + '.json')
                c2 = os.path.join(campaign_folder, item + '_analyzed.json')
                if os.path.exists(c1):
                    resolved.append(c1)
                    continue
                if os.path.exists(c2):
                    resolved.append(c2)
                    continue
            print(f"[WARN] Input not found, skipping: {item}")
        return resolved

    candidates = {}
    for name in sorted(os.listdir(campaign_folder)):
        if not name.endswith('.json'):
            continue
        if not name.startswith('Campaign_'):
            continue
        if name == 'Campaign_Experiments.json':
            continue

        # Normalize key so raw/analyzed variants map to one experiment name.
        key = name[: -len('_analyzed.json')] if name.endswith('_analyzed.json') else name[: -len('.json')]
        full_path = os.path.join(campaign_folder, name)

        # Prefer raw JSON when both exist; otherwise keep analyzed JSON.
        if key not in candidates:
            candidates[key] = full_path
        elif not name.endswith('_analyzed.json'):
            candidates[key] = full_path

    return [candidates[k] for k in sorted(candidates.keys(), key=_sample_sort_key)]


def _load_points_from_campaign_experiments(campaign_folder):
    campaign_path = os.path.join(campaign_folder, 'Campaign_Experiments.json')
    if not os.path.exists(campaign_path):
        return []

    try:
        campaign_dict = json.load(open(campaign_path, 'r'))
    except Exception:
        return []

    points = []
    for name in sorted(campaign_dict.keys(), key=_sample_sort_key):
        item = campaign_dict.get(name, {})
        actions = item.get('Actions', [])
        if not isinstance(actions, (list, tuple)) or len(actions) < 3:
            continue
        drip_time = _as_float(actions[0], default=None)
        drip_rate = _as_float(actions[1], default=None)
        drip_vol = _as_float(actions[2], default=None)
        obs = _as_float(item.get('Observation'), default=None)
        if drip_time is None or drip_rate is None or drip_vol is None or obs is None:
            continue
        if drip_rate <= 0:
            continue

        drip_duration = drip_vol / drip_rate * 0.06
        if not np.isfinite(drip_duration):
            continue

        rank = _score_to_rank(obs)
        if rank is None:
            rank = 1

        points.append({
            'name': str(name),
            'drip_time': float(drip_time),
            'drip_duration': float(drip_duration),
            'rank': int(rank),
            'objective_value': float(obs),
        })

    return points


def update_campaign_plot(
    history_points,
    all_points,
    step_idx,
    total_steps,
    output_folder,
    objective_limits=None,
    bo_strategy=BO_SURROGATE_STRATEGY,
    objective_mode=BO_OBJECTIVE_MODE,
    bo_state=None,
):
    """
    Save a standalone BO surface frame for each campaign step.
    This makes downstream GIF/video stitching straightforward.
    """
    if not history_points:
        return

    fig, ax = plt.subplots(figsize=(6.6, 4.8), constrained_layout=True)
    _plot_campaign_evolution(
        ax=ax,
        history_points=history_points,
        all_points=all_points,
        step_idx=step_idx,
        total_steps=total_steps,
        objective_limits=objective_limits,
        bo_strategy=bo_strategy,
        objective_mode=objective_mode,
        bo_state=bo_state,
        update_state=True,
    )
    frame_path = os.path.join(output_folder, f'campaign_surface_step_{int(step_idx):02d}.png')
    fig.savefig(frame_path, dpi=220)
    plt.close(fig)
    print(f"Saved campaign BO surface frame: {frame_path}")


def run_manual(campaign_folder, inputs=None, output_subfolder=OUTPUT_SUBFOLDER_DEFAULT):
    json_files = _resolve_inputs(campaign_folder, inputs)
    if not json_files:
        print('No campaign json files found to process.')
        return

    if os.path.isabs(output_subfolder):
        output_folder = output_subfolder
    else:
        output_folder = os.path.join(campaign_folder, output_subfolder)
    os.makedirs(output_folder, exist_ok=True)

    all_points = []
    if BO_USE_CAMPAIGN_EXPERIMENTS:
        all_points = _load_points_from_campaign_experiments(campaign_folder)

    # Fallback: derive points directly from analyzed json files if campaign file is absent.
    if not all_points:
        for json_path in json_files:
            try:
                file_name = _get_file_name_base(json_path)
                master_dict = _prepare_master_dict(json_path)
                point = _extract_campaign_point(master_dict, file_name)
                if point is not None:
                    all_points.append(point)
            except Exception:
                continue

    total_steps = len(all_points)
    objective_limits = _objective_limits_from_points(all_points, objective_mode=BO_OBJECTIVE_MODE)
    bo_state = {"kernel_cache": {}, "prev_surface": None}
    print(f"[BO] objective_mode={BO_OBJECTIVE_MODE}, strategy_mode={BO_SURROGATE_STRATEGY}")

    for json_path in json_files:
        try:
            file_name = _get_file_name_base(json_path)
            print(f"--- New_Visual_test processing: {file_name} ---")
            master_dict = _prepare_master_dict(json_path)
            results = _calculate_utility_metrics(master_dict)
            history_points = [
                p for p in all_points
                if _sample_sort_key(p['name']) <= _sample_sort_key(file_name)
            ]
            step_idx = len(history_points)
            _generate_plots_new(
                master_dict,
                results,
                output_folder,
                campaign_folder,
                file_name,
                history_points,
                all_points,
                step_idx,
                total_steps,
                objective_limits,
                BO_SURROGATE_STRATEGY,
                BO_OBJECTIVE_MODE,
                bo_state,
            )
            update_campaign_plot(
                history_points=history_points,
                all_points=all_points,
                step_idx=step_idx,
                total_steps=total_steps,
                output_folder=output_folder,
                objective_limits=objective_limits,
                bo_strategy=BO_SURROGATE_STRATEGY,
                objective_mode=BO_OBJECTIVE_MODE,
                bo_state=bo_state,
            )
        except Exception:
            print(f"[ERROR] Failed on {json_path}")
            traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description='Manual V9 alt visual report generator')
    parser.add_argument(
        '--campaign-folder',
        default=MANUAL_CAMPAIGN_FOLDER,
        help='Folder containing campaign json outputs',
    )
    parser.add_argument(
        '--inputs',
        nargs='*',
        default=MANUAL_INPUTS,
        help='Optional list of file names/stems/paths to process',
    )
    parser.add_argument(
        '--output-subfolder',
        default=MANUAL_OUTPUT_SUBFOLDER,
        help='Output subfolder inside campaign folder',
    )
    args = parser.parse_args()

    if not args.campaign_folder:
        raise ValueError(
            "No campaign folder provided. Set MANUAL_CAMPAIGN_FOLDER at the top of the script or pass --campaign-folder."
        )

    run_manual(
        campaign_folder=args.campaign_folder,
        inputs=args.inputs,
        output_subfolder=args.output_subfolder,
    )


if __name__ == '__main__':
    main()
