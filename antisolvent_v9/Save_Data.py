print('Saving Data')




# --- Corrected relative import for isolated pipeline ---
from . import Dual_Send_OceanFlame as DSO
# ---




import pandas as pd
import numpy as np
import json
import os




def save_Data(fileFolder, fileName, measType, dfLog, ddLog, tags):
  # Finalize the DataFrames before saving
  DSO.finalize_DataFrames()




  print('Saving Data...')
  masterFile = os.path.join(fileFolder, fileName)




  ## Save Data as Json
  master_Dict = {}




  master_Dict['Log'] = ddLog
  master_Dict['Tags'] = tags




  # process parameters of interest
  # Added a check to handle cases where rate might not be a string
  drip_rate_raw = tags.get('Anti-Solvent Rate', '0.0')
  if isinstance(drip_rate_raw, str):
      drip_rate_val = drip_rate_raw.replace('MM', '').strip()
  else:
      drip_rate_val = str(drip_rate_raw)




  drip_time = float(tags.get('Anti-Solvent Drip Time', 0.0))
  drip_rate = float(drip_rate_val)
  drip_vol = float(tags.get('Anti-Solvent Volume', 0.0))




  master_Dict['Parameters'] = {'Drip Time': drip_time,
                               'Drip Rate': drip_rate,
                               'Drip Volume': drip_vol}




  if measType in [1, 2, 3]:
      wavelength = DSO.wavelengths
      master_Dict["Wavelengths"] = wavelength
      master_Dict["Energies"] = [1239.9/W for W in wavelength]




  # saves absorbance data
  if measType in [1, 3]:
      master_Dict['Reflection'] = DSO.ddR
      master_Dict['Absorbance'] = DSO.ddAbsR
      master_Dict['Reflection Spectral Count'] = DSO.ddRawR
      master_Dict['Reflection Baseline'] = DSO.ddBaseR




  # saves PL data
  if measType in [2, 3]:
      master_Dict['PL Measurement'] = DSO.ddPL
      master_Dict['PL Spectral Count'] = DSO.ddRawPL
      master_Dict['PL Baseline'] = DSO.ddBasePL




  with open(masterFile + '.json', 'w') as outfile:
      json.dump(master_Dict, outfile, default=str)




  print('JSON Saved')





