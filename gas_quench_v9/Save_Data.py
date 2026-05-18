print('Saving Data (V9_GQ)')

# --- Corrected relative import for isolated pipeline ---
from . import Dual_Send_OceanFlame as DSO
# ---

import json
import os


def save_Data(fileFolder, fileName, measType, dfLog, ddLog, tags):
    """Finalize spectroscopy buffers and save one complete raw experiment JSON."""
    # Action: convert the live spectroscopy dictionaries into their final saved form.
    DSO.finalize_DataFrames()

    print('Saving Data...')
    masterFile = os.path.join(fileFolder, fileName)

    master_Dict = {}
    master_Dict['Log'] = ddLog
    master_Dict['Tags'] = tags

    # Action: save the two gas-quench process parameters in explicit engineering units.
    gq_time = float(tags.get('Gas Quench Start Time', 0.0))
    gq_duration = float(tags.get('Gas Quench Duration', 0.0))
    master_Dict['Parameters'] = {
        'Gas Quench Time': gq_time,
        'Gas Quench Duration': gq_duration,
        'Parameter Names': ['Gas Quench Time', 'Gas Quench Duration'],
    }

    if measType in [1, 2, 3]:
        wavelength = DSO.wavelengths
        master_Dict["Wavelengths"] = wavelength
        master_Dict["Energies"] = [1239.9 / W for W in wavelength]

    # Action: save reflection-derived data products for reflection or dual runs.
    if measType in [1, 3]:
        master_Dict['Reflection'] = DSO.ddR
        master_Dict['Absorbance'] = DSO.ddAbsR
        master_Dict['Reflection Spectral Count'] = DSO.ddRawR
        master_Dict['Reflection Baseline'] = DSO.ddBaseR

    # Action: save PL-derived data products for PL or dual runs.
    if measType in [2, 3]:
        master_Dict['PL Measurement'] = DSO.ddPL
        master_Dict['PL Spectral Count'] = DSO.ddRawPL
        master_Dict['PL Baseline'] = DSO.ddBasePL

    # Action: write the final raw JSON package for this experiment.
    with open(masterFile + '.json', 'w') as outfile:
        json.dump(master_Dict, outfile, default=str)

    print('JSON Saved')
