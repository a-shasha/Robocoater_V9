import math
import time
import matplotlib.pyplot as plt
import pandas as pd
import random
import matplotlib
import matplotlib.animation as animation
from pandas.core.accessor import register_index_accessor
# import imageio
import glob
import os
import statistics
import numpy as np
import json
from scipy.signal import chirp, find_peaks, peak_widths
from scipy.ndimage import gaussian_filter1d
from scipy.signal import savgol_filter
import cv2
from statistics import mean

from scipy.integrate import simpson

# import imageio


opticalBandedge = 675





def correct_UVvis(file_folder, file_name):
	'''Narrow the UV-vis data to wavelength range of interst '''
	minWavelength_abs = 550
	maxWavelength_abs = 900

	master_dict = json.load(open(file_folder+'/'+file_name+'.json'))
	wavelengths = master_dict['Wavelengths']
	all_absorbance = master_dict['Absorbance']

	minIndex_abs = wavelengths.index(min(wavelengths, key=lambda x: abs(x-minWavelength_abs)))
	maxIndex_abs = wavelengths.index(min(wavelengths, key=lambda x: abs(x-maxWavelength_abs)))
	abs_wavelengths = wavelengths[minIndex_abs:maxIndex_abs]

	abs_corrected = {}
	for key in all_absorbance.keys():

		abs_corrected[key] = all_absorbance[key][minIndex_abs:maxIndex_abs]

	master_dict['Absorbance Corrected'] = {'Wavelength': abs_wavelengths,
										   'Spectra': abs_corrected}

	with open(file_folder+'/'+file_name+'.json', 'w') as outfile:
		json.dump(master_dict, outfile)




def UVvis_video(file_folder, file_name):
	master_dict = json.load(open(file_folder + '/' + file_name + '.json'))  # open saved data

	wavelengths = master_dict['Absorbance Corrected']['Wavelength']
	abs_corrected = master_dict['Absorbance Corrected']['Spectra']

	dripTime = master_dict['Parameters']['Drip Time']

	x_label = 'Wavelength (nm)'
	y_label = 'Absorbance'

	y_max = max([max(value) for key, value in abs_corrected.items()])

	# arbitrary name and number to save jpeg
	nameNo = 0
	intermediate_name = 'nameGraphABS'

	img_list = []
	for key in abs_corrected.keys():
		plt.clf()   # clears plot figure for each loop otherwise the plots stack ontop of the previous
		plt.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=True)

		measurment = abs_corrected[key]

		if min(measurment) > 0:
			y_min = 0
		else:
			y_min = None
		# y_measurment = np.array(measurment) # needs to be nd.array for slicing/putting in single peak

		plt.plot(wavelengths, savgol_filter(measurment, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0))


		indx_710 = wavelengths.index(min(wavelengths, key=lambda x: abs(x-710)))

		plt.scatter(wavelengths[indx_710], measurment[indx_710],
							marker='X', color='r', zorder=10)

		plt.title("Time {:.2f} seconds (Drip @ {})".format(float(key), round(dripTime, 1)))      # plot title is time, which is column name
		plt.axis([None, None, y_min, y_max])
		plt.xlabel(x_label)
		plt.ylabel(y_label)

		img_save_name = '{}{}{}.png'.format(file_folder, intermediate_name, nameNo)
		plt.savefig(img_save_name)
		img_list.append(img_save_name)
		nameNo += 1


	images = img_list	#[img for img in os.listdir(fileFolder) if img.endswith(".png")]

	frame = cv2.imread(os.path.join(file_folder, images[0]))
	height, width, layers = frame.shape

	# calculate mean time between measurements to set the video to real speed
	absTime = [float(key) for key in abs_corrected.keys()]
	sampleInterval = statistics.mean([(absTime[i+1]-absTime[i]) for i in range(len(absTime)-1)])
	fps = 1/sampleInterval * 1    # times 1x (real) speed

	fourcc = cv2.VideoWriter_fourcc(*'mp4v')
	video_name = file_folder + '/UVvis Analysis/Video/' + file_name + '_Abs_vid.mp4'
	video = cv2.VideoWriter(video_name, fourcc, fps, (width, height))

	for image in images:
		img = os.path.join(file_folder, image)
		video.write(cv2.imread(img))
		os.remove(img)

	cv2.destroyAllWindows()
	video.release()


def track_abs_wavelenth(all_abs, abs_time, all_wavelengths, wavelength_of_interst):
	indx_abs = all_wavelengths.index(min(all_wavelengths, key=lambda x: abs(x-wavelength_of_interst)))

	wave_abs = []
	for t in abs_time:
		wave_abs.append(all_abs[str(t)][indx_abs])

	return wave_abs #np.array(wave_abs)


def track_abs(file_folder, file_name):

	master_dict = json.load(open(file_folder+'/'+file_name+'.json'))

	wavelengths = master_dict['Absorbance Corrected']['Wavelength']
	abs_corrected = master_dict['Absorbance Corrected']['Spectra']
	abs_time = list(abs_corrected.keys())

	dripTime = master_dict['Parameters']['Drip Time']
	minTime_Index = abs_time.index(min(abs_time, key=lambda x: abs(float(x)-(dripTime-5))))

	abs_532 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 532)	# for PbI2 peak

	abs_680 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 680)
	abs_690 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 690)
	abs_700 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 700)
	abs_710 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 710)	# most relevant
	abs_720 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 720)
	abs_730 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 730)
	abs_740 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 740)
	abs_750 = track_abs_wavelenth(abs_corrected, abs_time, wavelengths, 750)

	master_dict['Absorbance Tracked All'] = {'All Abs Time': abs_time,
										 '532': abs_532,
										 '680': abs_680,
										 '690': abs_690,
										 '700': abs_700,
										 '710': abs_710,
										 '720': abs_720,
										 '730': abs_730,
										 '740': abs_740,
										 '750': abs_750}

	master_dict['Absorbance Tracked AD'] = {'AD Abs Time': abs_time[minTime_Index:],
										 '532 AD': abs_532[minTime_Index:],
										 '680 AD': abs_680[minTime_Index:],
										 '690 AD': abs_690[minTime_Index:],
										 '700 AD': abs_700[minTime_Index:],
										 '710 AD': abs_710[minTime_Index:],
										 '720 AD': abs_720[minTime_Index:],
										 '730 AD': abs_730[minTime_Index:],
										 '740 AD': abs_740[minTime_Index:],
										 '750 AD': abs_750[minTime_Index:]}

	with open(file_folder+'/'+file_name+'.json', 'w') as outfile:
		json.dump(master_dict, outfile)



def selected_abs(file_folder, file_name):

	master_dict = json.load(open(file_folder+'/'+file_name+'.json'))

	abs_corrected = master_dict['Absorbance Corrected']['Spectra']

	dripTime = master_dict['Parameters']['Drip Time']
	lDripTimes = np.array([-1, 0.25, 1, 2, 4, 8, 15])
	lDripTimes += dripTime

	select_abs = {}
	select_abs_times = []
	for l in lDripTimes:
		colHeader = min(list(abs_corrected.keys()), key=lambda x: abs(float(x)-float(l)))		# key
		abs_time = ('{:.2f}').format(float(colHeader))
		select_abs_times.append(abs_time)

		select_abs[colHeader] = abs_corrected[colHeader]

	abs_last = list(abs_corrected.keys())[-1]
	abs_last_time = ('{:.2f}').format(float(abs_last))
	select_abs_times.append(abs_last_time)

	select_abs[abs_last] = abs_corrected[abs_last]

	master_dict['Absorbance Selected'] = {'Spectra': select_abs,
										  'Times': select_abs_times}

	with open(file_folder+'/'+file_name+'.json', 'w') as outfile:
		json.dump(master_dict, outfile)



#folder = '/Users/nathanwoodward/Library/CloudStorage/GoogleDrive-nwoodwa@ncsu.edu/Shared drives/MSE-Amassian Group/Spinner/Self-Driving/1717/1.5mol 1717/24 Feb 2024/SD'
#name = '1717CB_10_analyzed'
#UVvis_video(folder, name)










