print("Spectroscopy Calibration (V9)")

from . import Dual_Send_Commands as DSC
from . import Dual_Send_OceanFlame as DSO
from . import Save_Data

import os
import time
import traceback
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ===========================
# USER SETTINGS
# ===========================
# Define your output directory here.
CALIBRATION_OUTPUT_DIR = r"C:\Users\Admin\Desktop\Holmes_Spectroscopy_Calibration"

# Spinner controls
CALIBRATION_RPM = 4000
SPINUP_AFTER_SWAP_S = 3.0

# Spectrometer timing controls
CAL_SAMPLE_RATE_PL_US = 50000
CAL_SAMPLE_RATE_REFL_US = 10000
CAL_DATA_RATE_PL_S = 0.3
CAL_DATA_RATE_REFL_S = 0.2

# Dual measurement leg controls
REFLECTION_DWELL_S = 0.05
PL_DWELL_S = 0.05
N_AVG_SCANS = 1

# Baseline controls
CAL_BASELINE_SPINUP_S = 3.0
CAL_BASELINE_LIGHT_SETTLE_S = 0.5
CAL_BASELINE_SAMPLE_COUNT = 20
CAL_DARK_DISCARD_COUNT = 5

# Transition pause between baseline phases (between reflection/dark block and PL baseline)
BASELINE_PHASE_GAP_S = 0.8

# Spectral window controls
CAL_WAVELENGTH_MIN_NM = 300
CAL_WAVELENGTH_MAX_NM = 1000

# Reflection LED power for this calibration only (0-100)
CAL_REFLECTION_LED_POWER_PERCENT = 30


def _make_file_name():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"SpectroCal_{ts}"


def _apply_calibration_config():
    """Push calibration settings into DSO runtime globals so this script is self-contained."""
    if getattr(DSO, "device", None) is None:
        raise RuntimeError("Spectrometer is not connected. DSO.device is None.")

    # Timing / integration
    DSO.sampleRatePL = int(CAL_SAMPLE_RATE_PL_US)
    DSO.sampleRateReflc = int(CAL_SAMPLE_RATE_REFL_US)
    DSO.dataRatePL = float(CAL_DATA_RATE_PL_S)
    DSO.dataRateReflc = float(CAL_DATA_RATE_REFL_S)
    DSO.samplingRatePL = DSO.sampleRatePL / 1_000_000.0
    DSO.samplingRateReflc = DSO.sampleRateReflc / 1_000_000.0
    if DSO.dataRatePL < DSO.samplingRatePL:
        DSO.dataRatePL = DSO.samplingRatePL
    if DSO.dataRateReflc < DSO.samplingRateReflc:
        DSO.dataRateReflc = DSO.samplingRateReflc
    DSO.device.integration_time_micros(DSO.sampleRatePL)

    # Baseline behavior
    DSO.BASELINE_SPINUP_S = float(CAL_BASELINE_SPINUP_S)
    DSO.BASELINE_LIGHT_SETTLE_S = float(CAL_BASELINE_LIGHT_SETTLE_S)
    DSO.BASELINE_SAMPLE_COUNT = int(CAL_BASELINE_SAMPLE_COUNT)
    DSO.DARK_DISCARD_COUNT = int(CAL_DARK_DISCARD_COUNT)

    # Wavelength window
    DSO.lLightNM = float(CAL_WAVELENGTH_MIN_NM)
    DSO.uLightNM = float(CAL_WAVELENGTH_MAX_NM)
    all_wavelengths = list(DSO.device.wavelengths())
    DSO.lower_light_index = min(
        range(len(all_wavelengths)), key=lambda i: abs(all_wavelengths[i] - DSO.lLightNM)
    )
    DSO.upper_light_index = min(
        range(len(all_wavelengths)), key=lambda i: abs(all_wavelengths[i] - DSO.uLightNM)
    )
    if DSO.upper_light_index <= DSO.lower_light_index:
        raise RuntimeError(
            f"Invalid wavelength window: {CAL_WAVELENGTH_MIN_NM} to {CAL_WAVELENGTH_MAX_NM} nm"
        )

    # Reflection LED power override for this script.
    original_turn_on = DSC.turnON_rflc_led
    led_pct = int(max(0, min(100, CAL_REFLECTION_LED_POWER_PERCENT)))

    def _turn_on_rflc_led_cal():
        DSC.write_led(f"p{led_pct}")

    DSC.turnON_rflc_led = _turn_on_rflc_led_cal
    return original_turn_on


def _print_active_config():
    print("\n--- Active Calibration Config ---")
    print(f"Output Dir: {CALIBRATION_OUTPUT_DIR}")
    print(f"RPM: {CALIBRATION_RPM}")
    print(f"Wavelength window: {CAL_WAVELENGTH_MIN_NM} to {CAL_WAVELENGTH_MAX_NM} nm")
    print(f"LED power: {CAL_REFLECTION_LED_POWER_PERCENT}%")
    print(
        f"PL integration/data rate: {CAL_SAMPLE_RATE_PL_US} us / {CAL_DATA_RATE_PL_S} s "
        f"(effective {DSO.dataRatePL:.4f} s)"
    )
    print(
        f"Refl integration/data rate: {CAL_SAMPLE_RATE_REFL_US} us / {CAL_DATA_RATE_REFL_S} s "
        f"(effective {DSO.dataRateReflc:.4f} s)"
    )
    print(f"Dual dwell (Refl/PL): {REFLECTION_DWELL_S} s / {PL_DWELL_S} s")
    print(f"Averaging scans per leg: {N_AVG_SCANS}")
    print(
        f"Baseline spinup/settle/samples/discard: {CAL_BASELINE_SPINUP_S} s / "
        f"{CAL_BASELINE_LIGHT_SETTLE_S} s / {CAL_BASELINE_SAMPLE_COUNT} / {CAL_DARK_DISCARD_COUNT}"
    )
    print("---------------------------------\n")


def _latest_trace(trace_dict):
    """Return (time_key_float, trace_array) for the latest numeric key in a dict."""
    if not isinstance(trace_dict, dict):
        return None, None

    candidates = []
    for key in trace_dict.keys():
        if key == "Wavelengths":
            continue
        try:
            candidates.append((float(key), key))
        except Exception:
            continue

    if not candidates:
        return None, None

    t_val, key_ref = max(candidates, key=lambda x: x[0])
    return t_val, np.array(trace_dict[key_ref], dtype=float)


def _latest_reflection_unclipped():
    """
    Recompute latest reflection (R) from raw reflection + baselines without clipping.
    Formula: R = (I_sample - I_dark) / (I_ref - I_dark)
    """
    t_raw, raw_trace = _latest_trace(DSO.ddRawR)
    if raw_trace is None:
        return None, None

    refl_base = np.array(DSO.ddBaseR.get("Reflective Baseline", []), dtype=float)
    dark_base = np.array(DSO.ddBaseR.get("Black Baseline", []), dtype=float)
    if len(refl_base) != len(raw_trace) or len(dark_base) != len(raw_trace):
        return None, None

    denom = refl_base - dark_base
    denom_safe = np.where(denom > 0, denom, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        refl = (raw_trace - dark_base) / denom_safe
    return t_raw, refl


def _interp_at_nm(wavelengths, trace, nm):
    if wavelengths is None or trace is None:
        return np.nan
    if len(wavelengths) == 0 or len(trace) != len(wavelengths):
        return np.nan
    try:
        return float(np.interp(float(nm), wavelengths, trace))
    except Exception:
        return np.nan


def _safe_max(arr):
    if arr is None:
        return np.nan
    arr = np.array(arr, dtype=float)
    if arr.size == 0:
        return np.nan
    return float(np.max(arr))


def _save_spectral_csv(output_dir, file_name):
    """
    Save one per-run CSV with wavelength axis + baselines + latest single-shot traces.
    """
    wavelengths = np.array(DSO.wavelengths, dtype=float)
    if wavelengths.size == 0:
        return None

    t_pl, pl_trace = _latest_trace(DSO.ddPL)
    t_pl_raw, pl_raw_trace = _latest_trace(DSO.ddRawPL)
    t_abs, abs_trace = _latest_trace(DSO.ddAbsR)
    t_refl, refl_trace = _latest_trace(DSO.ddR)
    t_raw_refl, raw_refl_trace = _latest_trace(DSO.ddRawR)
    t_refl_calc, refl_calc_trace = _latest_reflection_unclipped()

    refl_base = np.array(DSO.ddBaseR.get("Reflective Baseline", []), dtype=float)
    dark_base = np.array(DSO.ddBaseR.get("Black Baseline", []), dtype=float)
    pl_base = np.array(DSO.ddBasePL.get("PL Baseline", []), dtype=float)

    cols = {"Wavelengths (nm)": wavelengths}
    if len(refl_base) == len(wavelengths):
        cols["Reflective Baseline"] = refl_base
    if len(dark_base) == len(wavelengths):
        cols["Dark Baseline"] = dark_base
    if len(pl_base) == len(wavelengths):
        cols["PL Baseline"] = pl_base
    if pl_trace is not None and len(pl_trace) == len(wavelengths):
        cols[f"PL Measurement @ {t_pl:.3f}s"] = pl_trace
    if pl_raw_trace is not None and len(pl_raw_trace) == len(wavelengths):
        cols[f"PL Raw @ {t_pl_raw:.3f}s"] = pl_raw_trace
    if abs_trace is not None and len(abs_trace) == len(wavelengths):
        cols[f"Absorbance @ {t_abs:.3f}s"] = abs_trace
    if refl_trace is not None and len(refl_trace) == len(wavelengths):
        cols[f"Reflection @ {t_refl:.3f}s"] = refl_trace
    if refl_calc_trace is not None and len(refl_calc_trace) == len(wavelengths):
        cols[f"Reflection Calc @ {t_refl_calc:.3f}s"] = refl_calc_trace
    if raw_refl_trace is not None and len(raw_refl_trace) == len(wavelengths):
        cols[f"Reflection Raw @ {t_raw_refl:.3f}s"] = raw_refl_trace

    csv_path = os.path.join(output_dir, file_name + "_Spectra.csv")
    pd.DataFrame(cols).to_csv(csv_path, index=False)
    return csv_path


def _build_summary_row(file_name, json_path, plot_path, spectra_csv_path):
    wavelengths = np.array(DSO.wavelengths, dtype=float)

    t_pl, pl_trace = _latest_trace(DSO.ddPL)
    t_abs, abs_trace = _latest_trace(DSO.ddAbsR)
    t_refl, refl_trace = _latest_trace(DSO.ddR)

    pl_peak_nm = np.nan
    pl_peak_count = np.nan
    pl_area = np.nan
    pl_mean_600_900 = np.nan
    if pl_trace is not None and len(pl_trace) == len(wavelengths) and len(wavelengths) > 0:
        idx = int(np.argmax(pl_trace))
        pl_peak_nm = float(wavelengths[idx])
        pl_peak_count = float(pl_trace[idx])
        pl_area = float(np.trapz(pl_trace, wavelengths))
        band_mask = (wavelengths >= 600.0) & (wavelengths <= 900.0)
        if np.any(band_mask):
            pl_mean_600_900 = float(np.mean(pl_trace[band_mask]))

    abs_at_475 = _interp_at_nm(wavelengths, abs_trace, 475.0)
    abs_at_532 = _interp_at_nm(wavelengths, abs_trace, 532.0)
    abs_mean_550_800 = np.nan
    if abs_trace is not None and len(abs_trace) == len(wavelengths):
        band_mask = (wavelengths >= 550.0) & (wavelengths <= 800.0)
        if np.any(band_mask):
            abs_mean_550_800 = float(np.mean(abs_trace[band_mask]))

    refl_at_532 = _interp_at_nm(wavelengths, refl_trace, 532.0)

    row = {
        "Run Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "File Name": file_name,
        "JSON Path": json_path,
        "Plot Path": plot_path,
        "Spectra CSV Path": spectra_csv_path or "",
        "PL Time (s)": t_pl if t_pl is not None else np.nan,
        "Abs Time (s)": t_abs if t_abs is not None else np.nan,
        "Refl Time (s)": t_refl if t_refl is not None else np.nan,
        "PL Peak Wavelength (nm)": pl_peak_nm,
        "PL Peak Count (a.u.)": pl_peak_count,
        "PL Area (a.u.*nm)": pl_area,
        "PL Mean 600-900nm (a.u.)": pl_mean_600_900,
        "Abs @475nm (a.u.)": abs_at_475,
        "Abs @532nm (a.u.)": abs_at_532,
        "Abs Mean 550-800nm (a.u.)": abs_mean_550_800,
        "Reflection @532nm": refl_at_532,
        "Reflective Baseline Max": _safe_max(DSO.ddBaseR.get("Reflective Baseline", [])),
        "Dark Baseline Max": _safe_max(DSO.ddBaseR.get("Black Baseline", [])),
        "PL Baseline Max": _safe_max(DSO.ddBasePL.get("PL Baseline", [])),
        "RPM": CALIBRATION_RPM,
        "PL Integration (us)": CAL_SAMPLE_RATE_PL_US,
        "Refl Integration (us)": CAL_SAMPLE_RATE_REFL_US,
        "PL DataRate (s)": DSO.dataRatePL,
        "Refl DataRate (s)": DSO.dataRateReflc,
        "PL Dwell (s)": PL_DWELL_S,
        "Refl Dwell (s)": REFLECTION_DWELL_S,
        "Avg Scans": N_AVG_SCANS,
        "LED Power (%)": CAL_REFLECTION_LED_POWER_PERCENT,
        "Wavelength Min (nm)": CAL_WAVELENGTH_MIN_NM,
        "Wavelength Max (nm)": CAL_WAVELENGTH_MAX_NM,
        "Baseline Spinup (s)": CAL_BASELINE_SPINUP_S,
        "Baseline Settle (s)": CAL_BASELINE_LIGHT_SETTLE_S,
        "Baseline Sample Count": CAL_BASELINE_SAMPLE_COUNT,
        "Dark Discard Count": CAL_DARK_DISCARD_COUNT,
    }
    return row


def _append_summary_csv(output_dir, row):
    summary_csv_path = os.path.join(output_dir, "Spectroscopy_Calibration_Summary.csv")
    summary_df = pd.DataFrame([row])
    summary_df.to_csv(
        summary_csv_path,
        mode="a",
        header=not os.path.exists(summary_csv_path),
        index=False,
    )
    return summary_csv_path


def _save_quick_plot(output_dir, file_name):
    """Save a 2-panel calibration plot: final PL line and final reflection line."""
    wavelengths = np.array(DSO.wavelengths, dtype=float)
    t_pl, pl_trace = _latest_trace(DSO.ddPL)
    t_refl, refl_trace = _latest_reflection_unclipped()
    if refl_trace is None:
        t_refl, refl_trace = _latest_trace(DSO.ddR)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    fig.suptitle("Calibration Snapshot: PL + Reflection", fontsize=11)

    if pl_trace is not None and len(pl_trace) == len(wavelengths):
        axes[0].plot(wavelengths, pl_trace, color="tab:orange")
        axes[0].set_title(f"PL (single) at t={t_pl:.2f} s")
        axes[0].set_xlabel("Wavelength (nm)")
        axes[0].set_ylabel("PL Count (a.u.)")
    else:
        axes[0].text(0.5, 0.5, "NO PL DATA", ha="center", va="center")
        axes[0].axis("off")

    if refl_trace is not None and len(refl_trace) == len(wavelengths):
        axes[1].plot(wavelengths, refl_trace, color="tab:blue")
        axes[1].set_title(f"Reflection (calc, unclipped) at t={t_refl:.2f} s")
        axes[1].set_xlabel("Wavelength (nm)")
        axes[1].set_ylabel("Reflection (R)")
    else:
        axes[1].text(0.5, 0.5, "NO REFLECTION DATA", ha="center", va="center")
        axes[1].axis("off")

    plot_path = os.path.join(output_dir, file_name + "_CalibrationPlot.jpeg")
    fig.savefig(plot_path, dpi=120)
    plt.close(fig)
    return plot_path


def run_spectroscopy_calibration():
    """
    Two-phase spectroscopy calibration flow:
    1) Clear substrate baseline run (continuous spinner through all baseline phases).
    2) Manual substrate swap, then one single dual (Reflection+PL) measurement.
    Saves V9-structure JSON, a 2-panel PL/Reflection JPEG, and calibration CSV outputs.
    """
    os.makedirs(CALIBRATION_OUTPUT_DIR, exist_ok=True)
    file_name = _make_file_name()
    original_turn_on_rflc_led = None

    print("\n=== Spectroscopy Calibration Start ===")
    print(f"Output folder: {CALIBRATION_OUTPUT_DIR}")
    print(f"Running file: {__file__}")
    print("Quick plot mode: Reflection R from raw counts + baselines (unclipped).")
    time_start = time.time()

    try:
        # Apply all spectroscopy settings from this file before any acquisition.
        original_turn_on_rflc_led = _apply_calibration_config()
        _print_active_config()

        print("Place a CLEAR substrate on chuck, then press Enter to start baseline sequence.")
        input()

        # Initialize data/log containers
        DSC.init_List()
        DSO.create_Dataframes()

        # Phase 1: baselines on clear substrate with continuous spinning.
        print("\n[Phase 1] Baselines on clear substrate")
        DSO.reflc_Baseline(CALIBRATION_RPM, keep_spinner_on=True)
        time.sleep(BASELINE_PHASE_GAP_S)
        DSO.pl_Baseline(CALIBRATION_RPM, spinner_already_on=True)

        print("\nBaseline sequence complete.")
        print("Remove clear substrate, place fabricated film substrate, then press Enter to resume.")
        input()

        # Phase 2: single dual measurement on fabricated substrate.
        print("\n[Phase 2] Single dual measurement on fabricated substrate")
        DSC.setSpinner(CALIBRATION_RPM, time_start)
        time.sleep(SPINUP_AFTER_SWAP_S)

        collect_start = time.time()

        # Reflection leg
        DSC.plOFF()
        DSC.turnON_rflc_led()
        time.sleep(REFLECTION_DWELL_S)
        DSO.insitu_reflc_Measurement(collect_start, n_avg=N_AVG_SCANS)
        DSC.turnOff_rflc_led()

        # PL leg
        DSC.plON()
        time.sleep(PL_DWELL_S)
        DSO.insitu_pl_Measurement(collect_start, n_avg=N_AVG_SCANS)
        DSC.plOFF()

        DSC.stopSpinner(time_start)
        time.sleep(2.0)

        # Save JSON using V9 save structure.
        tags = {
            "Experiment Name": file_name,
            "RPM": CALIBRATION_RPM,
            "Spin Time": 0,
            "Perovskite Volume": 0,
            "Anti-Solvent Rate": 0,
            "Anti-Solvent Volume": 0,
            "Anti-Solvent Drip Time": 0,
            "Measurement": 3,
            "Calibration Mode": "Spectroscopy Calibration",
            "Calibration Config": {
                "PL Integration (us)": CAL_SAMPLE_RATE_PL_US,
                "Refl Integration (us)": CAL_SAMPLE_RATE_REFL_US,
                "PL DataRate (s)": CAL_DATA_RATE_PL_S,
                "Refl DataRate (s)": CAL_DATA_RATE_REFL_S,
                "PL Dwell (s)": PL_DWELL_S,
                "Refl Dwell (s)": REFLECTION_DWELL_S,
                "Avg Scans": N_AVG_SCANS,
                "LED Power (%)": CAL_REFLECTION_LED_POWER_PERCENT,
                "Wavelength Min (nm)": CAL_WAVELENGTH_MIN_NM,
                "Wavelength Max (nm)": CAL_WAVELENGTH_MAX_NM,
                "Baseline Spinup (s)": CAL_BASELINE_SPINUP_S,
                "Baseline Settle (s)": CAL_BASELINE_LIGHT_SETTLE_S,
                "Baseline Sample Count": CAL_BASELINE_SAMPLE_COUNT,
                "Dark Discard Count": CAL_DARK_DISCARD_COUNT,
            },
        }

        df_log = pd.DataFrame(
            {
                "Actions": pd.Series(DSC.sequenceName),
                "Action Times": pd.Series(DSC.sequenceTime),
                "Inputs": pd.Series(["Calibration RPM", "Avg Scans", "PL dwell (s)", "Refl dwell (s)"]),
                "Values": pd.Series([CALIBRATION_RPM, N_AVG_SCANS, PL_DWELL_S, REFLECTION_DWELL_S]),
            }
        )
        dd_log = df_log.to_dict(orient="list")

        Save_Data.save_Data(CALIBRATION_OUTPUT_DIR, file_name, 3, df_log, dd_log, tags)
        json_path = os.path.join(CALIBRATION_OUTPUT_DIR, file_name + ".json")

        plot_path = _save_quick_plot(CALIBRATION_OUTPUT_DIR, file_name)
        spectra_csv_path = _save_spectral_csv(CALIBRATION_OUTPUT_DIR, file_name)
        summary_row = _build_summary_row(file_name, json_path, plot_path, spectra_csv_path)
        summary_csv_path = _append_summary_csv(CALIBRATION_OUTPUT_DIR, summary_row)

        print("\n=== Spectroscopy Calibration Complete ===")
        print(f"JSON: {json_path}")
        print(f"Plot: {plot_path}")
        print(f"Spectra CSV: {spectra_csv_path}")
        print(f"Summary CSV: {summary_csv_path}")

    except Exception as exc:
        print(f"\n[Calibration Error] {exc}")
        traceback.print_exc()
        raise

    finally:
        if original_turn_on_rflc_led is not None:
            DSC.turnON_rflc_led = original_turn_on_rflc_led

        # Hard safety shutdown for lights/spinner
        try:
            DSC.turnOff_rflc_led()
        except Exception:
            pass
        try:
            DSC.plOFF()
        except Exception:
            pass
        try:
            DSC.stopSpinner(time_start)
        except Exception:
            pass


if __name__ == "__main__":
    run_spectroscopy_calibration()
