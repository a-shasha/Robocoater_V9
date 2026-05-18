print("Dual Send Flame")

import numpy as np
import pandas as pd
import time

from . import Dual_Send_Commands as DSC

from seabreeze.spectrometers import Spectrometer

# Baseline sequencing guards to prevent source cross-talk between LED and UV.
BASELINE_SPINUP_S = 3.0
BASELINE_LIGHT_SETTLE_S = 0.5
BASELINE_SAMPLE_COUNT = 20
DARK_DISCARD_COUNT = 5

# Dual in-situ scheduling controls
# Continuous dual (Reflection + PL) sampling with fixed cadence.
DUAL_REFLECTION_DWELL_S = 0.05
DUAL_PL_DWELL_S = 0.05
DUAL_AVG_SCANS = 1


# ... (The first part of the file is unchanged) ...


### List of Functions ###
# * represents the main functions to call


## Ocean Insight ##
# get_Wavelengths()         # returns list of wavelengths  (np.array)
# get_Intensities()         # returns list of spectrum counts (np.array)


## Reflection ##
# reflc_Baseline()
# blk_Baseline()
# reflc_Measurement()           # returns reflcPercent, rawMeasRF, absrbMeas
# insitu_reflc_Measurement(insitu_StartTime)
# * run_reflc_InSitu(insitu_StartTime, runtime)
# single_reflc_Measurment()     # return's dfReflection


## Photoluminescense (PL) ##
# pl_Baseline()                  # return's plMeas, rawMeasPL
# insitu_pl_Measurement(insitu_StartTime)
# * run_pl_InSitu(insitu_StartTime, runtime)


## Dual Reflection and PL ##
# * run_dual_InSitu(insitu_StartTime, runtime)


## Dataframes to be saved ##
# Reflection #
# dfBaseR
# dfR
# dfRawR
# dfAbsR


# PL #
# dfBasePL
# dfPL
# dfRawPL


### Ocean Flame Spectrometer get values ###
def get_Wavelengths():
    wavelengths = device.wavelengths()[lower_light_index:upper_light_index]
    return wavelengths


def get_Intensities():
    intensities = device.intensities()[lower_light_index:upper_light_index]
    return intensities


### Data Saving ###
def create_Dataframes():
    global wavelengths
    wavelengths = list(get_Wavelengths())
    # Dictionaries to hold data before DataFrame creation
    global ddBaseR, ddR, ddRawR, ddAbsR, ddBasePL, ddPL, ddRawPL
    ddBaseR, ddR, ddRawR, ddAbsR = {}, {}, {}, {}
    ddBasePL, ddPL, ddRawPL = {}, {}, {}


def finalize_DataFrames():
    """
    This function will be called once at the end of the experiment
    to create the DataFrames from the dictionaries in a single, efficient operation.
    """
    global dfBaseR, dfR, dfRawR, dfAbsR, dfBasePL, dfPL, dfRawPL
    # Add wavelengths at the beginning
    ddR['Wavelengths'] = ddRawR['Wavelengths'] = ddAbsR['Wavelengths'] = wavelengths
    ddPL['Wavelengths'] = ddRawPL['Wavelengths'] = wavelengths
    ddBaseR['Wavelengths'] = ddBasePL['Wavelengths'] = wavelengths

    # Create DataFrames from the dictionaries
    dfR = pd.DataFrame(ddR)
    dfRawR = pd.DataFrame(ddRawR)
    dfAbsR = pd.DataFrame(ddAbsR)
    dfPL = pd.DataFrame(ddPL)
    dfRawPL = pd.DataFrame(ddRawPL)
    dfBaseR = pd.DataFrame(ddBaseR)
    dfBasePL = pd.DataFrame(ddBasePL)

    # Reorder columns to have 'Wavelengths' first
    for df in [dfR, dfRawR, dfAbsR, dfPL, dfRawPL, dfBaseR, dfBasePL]:
        if 'Wavelengths' in df.columns:
            cols = df.columns.tolist()
            cols.insert(0, cols.pop(cols.index('Wavelengths')))
            df = df.reindex(columns=cols)


def build_DF(colName, measR, rawR, absorbR, measPL, rawPL):
    if measR is not None:
        ddR[colName] = measR.tolist()
    if rawR is not None:
        ddRawR[colName] = rawR.tolist()
    if absorbR is not None:
        ddAbsR[colName] = absorbR.tolist()
    if measPL is not None:
        ddPL[colName] = measPL.tolist()
        ddRawPL[colName] = rawPL.tolist()


### Reflection ###
def reflc_Baseline(speed, keep_spinner_on=False, spinner_already_on=False):
    # Hard guard: ensure UV source is off before reflection baseline.
    DSC.plOFF()
    DSC.turnOff_rflc_led()
    time.sleep(BASELINE_LIGHT_SETTLE_S)

    DSC.turnON_rflc_led()
    if not spinner_already_on:
        DSC.setSpinner(speed, time.time())
    device.integration_time_micros(sampleRateReflc)
    if not spinner_already_on:
        time.sleep(BASELINE_SPINUP_S)

    baselineSamples = [get_Intensities() for _ in range(BASELINE_SAMPLE_COUNT)]
    global reflcBase
    reflcBase = np.mean(baselineSamples, axis=0)
    ddBaseR['Reflective Baseline'] = reflcBase.tolist()

    print(max(reflcBase))
    DSC.turnOff_rflc_led()
    time.sleep(BASELINE_LIGHT_SETTLE_S)
    blk_Baseline()
    if not keep_spinner_on:
        DSC.stopSpinner(time.time())


def blk_Baseline():
    global blkBase
    # Measured dark baseline (UV-Vis dark) with reflection LED off
    DSC.plOFF()
    DSC.turnOff_rflc_led()
    device.integration_time_micros(sampleRateReflc)
    time.sleep(BASELINE_LIGHT_SETTLE_S)

    # Drop the first few scans to avoid source turn-off transients.
    for _ in range(DARK_DISCARD_COUNT):
        _ = get_Intensities()

    baselineSamples = [get_Intensities() for _ in range(BASELINE_SAMPLE_COUNT)]
    blkBase = np.mean(baselineSamples, axis=0)
    ddBaseR['Black Baseline'] = blkBase.tolist()


def reflc_Measurment():
    rawMeasRF = get_Intensities()
    # Dark-corrected UV-Vis reflection model:
    # R = (I_sample - I_dark) / (I_ref - I_dark)
    denom = np.array(reflcBase) - np.array(blkBase)
    denom[denom <= 0] = 1e-6
    reflcMeas = (np.array(rawMeasRF) - np.array(blkBase)) / denom
    reflcMeas[reflcMeas >= 1.5] = 1.5
    reflcMeas[reflcMeas <= 0] = 0.00001
    reflcPercent = reflcMeas * 100
    # absorbance = -log10(R)
    absrbMeas = -np.log10(reflcMeas)
    return reflcPercent, rawMeasRF, absrbMeas


def insitu_reflc_Measurement(insitu_StartTime, n_avg=1):
    startTime = time.time() - insitu_StartTime
    device.integration_time_micros(sampleRateReflc)
    reflcPercent_list = []
    rawMeasRF_list = []
    absrbMeas_list = []
    for _ in range(max(1, int(n_avg))):
        reflcPercent, rawMeasRF, absrbMeas = reflc_Measurment()
        reflcPercent_list.append(reflcPercent)
        rawMeasRF_list.append(rawMeasRF)
        absrbMeas_list.append(absrbMeas)
    reflcPercent = np.mean(reflcPercent_list, axis=0)
    rawMeasRF = np.mean(rawMeasRF_list, axis=0)
    absrbMeas = np.mean(absrbMeas_list, axis=0)
    build_DF(startTime, reflcPercent, rawMeasRF, absrbMeas, None, None)
    return time.time() - insitu_StartTime


def run_reflc_InSitu(insitu_StartTime, runtime):
    timer = 0
    DSC.turnON_rflc_led()
    sleepTime = max(0, dataRateReflc - samplingRateReflc - 0.01)
    while (timer <= runtime):
        timer = insitu_reflc_Measurement(insitu_StartTime)
        time.sleep(sleepTime)
    DSC.turnOff_rflc_led()


# ... (PL functions are unchanged) ...


def pl_Baseline(speed, spinner_already_on=False):
    # Hard guard: ensure reflection source is off before UV baseline.
    DSC.turnOff_rflc_led()
    DSC.plOFF()
    time.sleep(BASELINE_LIGHT_SETTLE_S)

    DSC.plON()
    if not spinner_already_on:
        DSC.setSpinner(speed, time.time())
    device.integration_time_micros(sampleRatePL)
    if not spinner_already_on:
        time.sleep(BASELINE_SPINUP_S)
    baselineSamples = [get_Intensities() for _ in range(BASELINE_SAMPLE_COUNT)]
    global plBase
    plBase = np.mean(baselineSamples, axis=0)
    ddBasePL['PL Baseline'] = plBase.tolist()
    DSC.plOFF()
    DSC.stopSpinner(time.time())


def pl_Measurment():
    rawMeasPL = get_Intensities()
    plMeas = rawMeasPL - plBase
    return plMeas, rawMeasPL


def insitu_pl_Measurement(insitu_StartTime, n_avg=1, integration_time_us=None):
    startTime = time.time() - insitu_StartTime
    integration_us = int(sampleRatePL if integration_time_us is None else integration_time_us)
    device.integration_time_micros(integration_us)
    plMeas_list = []
    rawMeasPL_list = []
    for _ in range(max(1, int(n_avg))):
        plMeas, rawMeasPL = pl_Measurment()
        plMeas_list.append(plMeas)
        rawMeasPL_list.append(rawMeasPL)
    plMeas = np.mean(plMeas_list, axis=0)
    rawMeasPL = np.mean(rawMeasPL_list, axis=0)
    build_DF(startTime, None, None, None, plMeas, rawMeasPL)
    return time.time() - insitu_StartTime


def run_pl_InSitu(insitu_StartTime, runtime):
    DSC.plON()
    timer = 0
    sleepTime = max(0, dataRatePL - samplingRatePL - 0.01)
    while timer <= runtime:
        timer = insitu_pl_Measurement(insitu_StartTime)
        time.sleep(sleepTime)
    DSC.plOFF()


### Dual Reflection and PL In-Situ ###
def run_dual_InSitu(insitu_StartTime, runtime):
    timer = 0

    while timer <= runtime:
        # Reflection measurement
        stime = time.time()
        DSC.turnON_rflc_led()
        time.sleep(DUAL_REFLECTION_DWELL_S)
        insitu_reflc_Measurement(insitu_StartTime, n_avg=DUAL_AVG_SCANS)
        DSC.turnOff_rflc_led()

        # --- THIS IS THE FIX ---
        reflc_LED_sleep = dataRateReflc - (time.time() - stime)
        time.sleep(max(0, reflc_LED_sleep))
        # ---

        timer = time.time() - insitu_StartTime
        if timer > runtime:
            break

        # Continuous PL leg every cycle with fixed integration/cadence.
        sstime = time.time()
        DSC.plON()
        time.sleep(DUAL_PL_DWELL_S)
        timer = insitu_pl_Measurement(insitu_StartTime, n_avg=DUAL_AVG_SCANS)
        DSC.plOFF()

        # Keep cadence stable for the PL leg as well.
        pl_LED_sleep = dataRatePL - (time.time() - sstime)
        time.sleep(max(0, pl_LED_sleep))


# ... (Rest of the file is unchanged) ...


### Initialization and User Input ###
lLightNM = 300
uLightNM = 1000

try:
    device = Spectrometer.from_serial_number("FLMS19677")
except Exception as e:
    print(f"Could not connect to spectrometer: {e}")
    device = None  # Handle case where spectrometer is not found

# set integration time,  time that the detector is allowed to collect photons  (like camera aperture)
# in microseconds, 1000us =  1ms or 0.001s
if device:
    sampleRatePL = 100000
    sampleRateReflc = 10000
    device.integration_time_micros(sampleRatePL)

    # dataRate is frequency
    # of collecting measurement insitu
    # in seconds; .1s = every 100ms
    # is independent of loop period, min is .01 s (10ms is flame integration time)
    # This variable is the total time you expect this sequence to take:
    # Turn on light -> Take measurement -> Turn off light
    dataRatePL = 0.3
    dataRateReflc = 0.2

    samplingRatePL = sampleRatePL / 1000000
    samplingRateReflc = sampleRateReflc / 1000000

    if dataRatePL < samplingRatePL: dataRatePL = samplingRatePL
    if dataRateReflc < samplingRateReflc: dataRateReflc = samplingRateReflc

    all_wavelengths = list(device.wavelengths())
    lower_light_index = min(range(len(all_wavelengths)), key=lambda i: abs(all_wavelengths[i] - lLightNM))
    upper_light_index = min(range(len(all_wavelengths)), key=lambda i: abs(all_wavelengths[i] - uLightNM))

    print('Max Intensity: ', max(get_Intensities()))
    DSC.turnOff_rflc_led()


def close_spectrometer():
    if device:
        device.close()
