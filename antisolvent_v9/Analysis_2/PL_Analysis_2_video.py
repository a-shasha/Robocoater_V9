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



def correct_PL(file_folder, file_name):
	'''
	Selects PL, wavelegth, and energy for range of interest
	Takes PL data corrects for any slant and any negative PL.
	Also Normalizes corrected PL
	'''

	# lower and upper wavelength of expected  PL peak
	minWavelength_pl = 600
	maxWavelength_pl = 900


	master_dict = json.load(open(file_folder+'/'+file_name+'.json'))
	pl_all = master_dict['PL Measurement'] # dict of times with lists of PL measurements
	wavelengths = master_dict["Wavelengths"]


	minIndex_pl = wavelengths.index(min(wavelengths, key=lambda x: abs(x-minWavelength_pl)))
	maxIndex_pl = wavelengths.index(min(wavelengths, key=lambda x: abs(x-maxWavelength_pl)))
	pl_wavelengths = wavelengths[minIndex_pl:maxIndex_pl]
	pl_energies = [1239.9/W for W in pl_wavelengths]

	pl_corrected = {}
	for key in pl_all.keys():
		pl_measure = np.array(pl_all[key][minIndex_pl:maxIndex_pl])

		## correct for any slant
		left_avg = mean(pl_measure[:50])
		right_avg = mean(pl_measure[-50:])
		base_slope = (right_avg - left_avg) / len(pl_energies)
		y_base = [base_slope*i + pl_measure[0] for i in range(len(pl_energies))]
		base_corrected = [pl_measure[i]-y_base[i] for i in range(len(pl_energies))]

		## correct for any negative pl
		lowestCount = min(savgol_filter(base_corrected, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0) )
		if lowestCount < 0:		# if negative, then add that value to all counts; otherwise stay's same
			Corrected_PL = [(x - lowestCount) for x in base_corrected]
		else:
			Corrected_PL = base_corrected


		pl_corrected[key] = Corrected_PL



	pl_normalized = {}
	for key in pl_corrected.keys():
		minPL = min(pl_corrected[key])
		maxPL = max(pl_corrected[key])
		pl_normalized[key] = [(x - minPL)/(maxPL - minPL) for x in pl_corrected[key]]



	master_dict['PL Corrected'] =  {'Spectra': pl_corrected,
									'Normalized Spectra': pl_normalized,
									'Wavelength': pl_wavelengths,
									'Energy': pl_energies}

	with open(file_folder+'/'+file_name+'.json', 'w') as outfile:
		json.dump(master_dict, outfile)



def analyze_PL_FWHM(file_folder, file_name, video):
	'''Makes video of confinement area'''

	master_dict = json.load(open(file_folder+'/'+file_name+'.json'))	# open saved data

	dripTime = master_dict['Parameters']['Drip Time']

	PL_corrected = master_dict['PL Corrected']['Spectra']
	pl_energies = master_dict['PL Corrected']['Energy']

	x_label = 'Energy (ev)'
	y_label = 'Intensity (a.u.)'
	y_min = -500
	y_max = max([max(value) for key, value in PL_corrected.items()])      # max count of PL count


	# arbitrary name and number to save jpeg
	nameNo = 0
	intermediate_name = 'nameGraph'

## All time points
	time_list = []      # time measurements
	peak_ev_list = []
	peak_intensity_list = []
	fwhm_list = []      # half,  50%
	fwhm_blue_peak_list = []     # higher eV, right side
	fwhm_red_peak_list = []
	fwhm_area_list = []
	fwqm_list = []      # quarter, 25%
	fwqm_blue_peak_list = []
	fwqm_red_peak_list = []
	fwqm_area_list = []


## After drip time points
	time_list_AD = []      # time measurements
	peak_ev_list_AD = []
	peak_intensity_list_AD = []
	fwhm_list_AD = []      # half,  50%
	fwhm_blue_peak_list_AD = []     # higher eV, right side
	fwhm_red_peak_list_AD = []
	fwhm_area_list_AD = []
	fwqm_list_AD = []      # quarter, 25%
	fwqm_blue_peak_list_AD = []
	fwqm_red_peak_list_AD = []
	fwqm_area_list_AD = []

	img_list = []
	failed_list = []

	for key in PL_corrected.keys():
		plt.clf()
		plt.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=True)

		measurment = np.array(PL_corrected[key])
		smoothed = (savgol_filter(measurment, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist()

		## Try to find peak and full width half max for all measurements
		try:
			## get max Peak Location
			max_y = max(measurment)
			prom = max_y*.075
			peaks, peak_properties = find_peaks(smoothed, prominence=prom)   # returns list of index of the peaks
			peak_energy = round(pl_energies[peaks[0]], 3)
			# print(peaks, peak_energy)

			# get FWHM Value
			fwhm_width, fwhm_height, fwhm_left, fwhm_right  = peak_widths(smoothed, peaks, rel_height=0.5)  # each is an nd.array
			# print(fwhm_width, fwhm_height, fwhm_left, fwhm_right)       # width between indexes, actual height, left index, right index
			fwhm_height = round(fwhm_height[0])         # indexs are exact, decimal values; need to round to match plotted data
			fwhm_left = round(fwhm_left[0])             # values are with respect to origianl index (ie wavelength)
			fwhm_right = round(fwhm_right[0])           # left = blue, right = red

			# fwhm_width_nm = x_wavelengths[round(fwhm_right[0])] - x_wavelengths[round(fwhm_left[0])]
			fwhm_width_energy = round((pl_energies[fwhm_left] - pl_energies[fwhm_right]), 3)

			# print(fwhm_height, pl_energies[fwhm_left], pl_energies[fwhm_right], fwhm_width_energy)

			## get FWQM Value
			fwqm_width, fwqm_height, fwqm_left, fwqm_right  = peak_widths(smoothed, peaks, rel_height=0.75)  # each is an nd.array
			fwqm_left = round(fwqm_left[0])
			fwqm_right = round(fwqm_right[0])
			fwqm_height = round(fwqm_height[0])

			fwqm_width_energy = round((pl_energies[fwqm_left] - pl_energies[fwqm_right]), 3)
			# print(fwqm_height, pl_energies[fwqm_left], pl_energies[fwqm_right], fwqm_width_energy)

			## Calculate area
			FWHM_flipped_energies = np.flip(pl_energies[fwhm_left:fwhm_right])
			FWHM_Area = simpson(measurment[fwhm_left:fwhm_right], FWHM_flipped_energies)

			FWQM_flipped_energies = np.flip(pl_energies[fwqm_left:fwqm_right])
			FWQM_Area = simpson(measurment[fwqm_left:fwqm_right], FWQM_flipped_energies)

			if video == True:
				## Peak
				plt.scatter(pl_energies[peaks[0]], measurment[peaks[0]], marker='X', color='r', zorder=10)    # peak finder   # zorder, higher number =  on top

				## FWHM
				plt.scatter([pl_energies[fwhm_left], pl_energies[fwhm_right]],
							 [fwhm_height, fwhm_height],
							marker='X', color='r', zorder=10)
				plt.hlines(fwhm_height, pl_energies[fwhm_right], pl_energies[fwhm_left], color="r")     # y, xmin, xmax # FWHM

				## FWQM
				plt.scatter([pl_energies[fwqm_left], pl_energies[fwqm_right]],
							[fwqm_height, fwqm_height],
							marker='X', color='r', zorder=10)
				plt.hlines(fwqm_height, pl_energies[fwqm_left], pl_energies[fwqm_right], color="r")     # y, xmin, xmax # FWHM

				plt.plot(pl_energies, smoothed)
				plt.axis([None, None, y_min, y_max])

				plt.xlabel(x_label)
				plt.ylabel(y_label)

				plt.title("Time {:.2f} seconds, Peak {:.2f} eV, FWHM {} ev (Drip @ {})".format(float(key), peak_energy, fwhm_width_energy, round(dripTime, 1)))


				img_save_name = '{}{}{}.png'.format(file_folder, intermediate_name, nameNo)
				plt.savefig(img_save_name)
				img_list.append(img_save_name)
				nameNo += 1          # adds a 1 to each file name so it its read in correct order

			passed = True

		except: # if can't find a peak then plot just PL data
			# print(key)
			passed = False
			failed_list.append(key)


			if video == True:
				plt.clf()
				plt.plot(pl_energies, smoothed, color='b')
				plt.title("Time {:.2f} seconds (Drip @ {})".format(float(key), round(dripTime, 1)))      # plot title is time, which is column name
				plt.axis([None, None, y_min, y_max])
				plt.xlabel(x_label)
				plt.ylabel(y_label)

				img_save_name = '{}{}{}.png'.format(file_folder, intermediate_name, nameNo)
				plt.savefig(img_save_name)
				img_list.append(img_save_name)
				nameNo += 1  # adds a 1 to each file name so it its read in correct order

		# save data only after drip
		if passed == True and float(key) >= (dripTime-5):
			time_list_AD.append(key)
			peak_ev_list_AD.append(pl_energies[peaks[0]])
			peak_intensity_list_AD.append(measurment[peaks[0]])

			fwhm_list_AD.append(fwhm_width_energy)
			fwhm_blue_peak_list_AD.append(pl_energies[fwhm_left])
			fwhm_red_peak_list_AD.append(pl_energies[fwhm_right])
			fwhm_area_list_AD.append(FWHM_Area)

			fwqm_list_AD.append(fwqm_width_energy)
			fwqm_blue_peak_list_AD.append(pl_energies[fwqm_left])
			fwqm_red_peak_list_AD.append(pl_energies[fwqm_right])
			fwqm_area_list_AD.append(FWQM_Area)

		elif passed == False and float(key) >= (dripTime-5):
			time_list_AD.append(key)
			peak_ev_list_AD.append(np.nan)
			peak_intensity_list_AD.append(np.nan)

			fwhm_list_AD.append(np.nan)
			fwhm_blue_peak_list_AD.append(np.nan)
			fwhm_red_peak_list_AD.append(np.nan)
			fwhm_area_list_AD.append(np.nan)

			fwqm_list_AD.append(np.nan)
			fwqm_blue_peak_list_AD.append(np.nan)
			fwqm_red_peak_list_AD.append(np.nan)
			fwqm_area_list_AD.append(np.nan)

	## save all data no matter before or after drip
		if passed == True:
			time_list.append(key)
			peak_ev_list.append(pl_energies[peaks[0]])
			peak_intensity_list.append(measurment[peaks[0]])

			fwhm_list.append(fwhm_width_energy)
			fwhm_blue_peak_list.append(pl_energies[fwhm_left])
			fwhm_red_peak_list.append(pl_energies[fwhm_right])
			fwhm_area_list.append(FWHM_Area)

			fwqm_list.append(fwqm_width_energy)
			fwqm_blue_peak_list.append(pl_energies[fwqm_left])
			fwqm_red_peak_list.append(pl_energies[fwqm_right])
			fwqm_area_list.append(FWQM_Area)

		else:   # save as nan in its place
			time_list.append(key)
			peak_ev_list.append(np.nan)
			peak_intensity_list.append(np.nan)

			fwhm_list.append(np.nan)
			fwhm_blue_peak_list.append(np.nan)
			fwhm_red_peak_list.append(np.nan)
			fwhm_area_list.append(np.nan)

			fwqm_list.append(np.nan)
			fwqm_blue_peak_list.append(np.nan)
			fwqm_red_peak_list.append(np.nan)
			fwqm_area_list.append(np.nan)



	# print(file_name, " Drip Time: ", dripTime, ' ', time_list[0])
	# print(file_name, ' Failed Times: ', failed_list)
	if video == True:
		images = img_list   #[img for img in os.listdir(fileFolder) if img.endswith(".png")]

		frame = cv2.imread(os.path.join(file_folder, images[0]))
		height, width, layers = frame.shape

		# calculate mean time between measurements to set the video to real speed
		plTime = [float(key) for key in PL_corrected.keys()]
		sampleInterval = statistics.mean([(plTime[i+1]-plTime[i]) for i in range(len(plTime)-1)])
		fps = 1/sampleInterval * 1    # times 1x (real) speed

		fourcc = cv2.VideoWriter_fourcc(*'mp4v')
		video_name = file_folder + '/PL Analysis/FWHM Video/' + file_name + '_PL_FWHM_vid.mp4'
		video = cv2.VideoWriter(video_name, fourcc, fps, (width, height))

		for image in images:
			img = os.path.join(file_folder, image)
			video.write(cv2.imread(img))
			os.remove(img)

		cv2.destroyAllWindows()
		video.release()


	# writer = imageio.get_writer('{}/{}.mp4'.format(file_folder, ('/PL Analysis/FWHM Video/' + file_name + '_PL_FWHM_vid'), fps=fps))
	# # for file in glob.glob(os.path.join(path, f'{intermediate_name}*.png')):
	# for name in range(nameNo):
	# 	file = '{}{}{}.png'.format(file_folder, intermediate_name, name)
	# 	im = imageio.imread(file)
	# 	writer.append_data(im)
	# 	# USER INPUT: comment out line below if you want images to remain saved
	# 	os.remove(file)
	#
	# writer.close()

	time_list = [float(t) for t in time_list]       # convert str to float
	time_list_AD = [float(t) for t in time_list_AD]

	## Save results
	master_dict['PL FWHM Analsys AD'] = {'PL Time AD': time_list_AD,
								   'Peak eV AD': peak_ev_list_AD,
								   'Peak Intensity AD': peak_intensity_list_AD,
								   'FWHM AD': fwhm_list_AD,
								   'FWHM Blue AD': fwhm_blue_peak_list_AD,
								   'FWHM Red AD': fwhm_red_peak_list_AD,
								   'FWHM Area AD': fwhm_area_list_AD,
								   'FWQM AD': fwqm_list_AD,
								   'FWQM Blue AD': fwqm_blue_peak_list_AD,
								   'FWQM Red AD': fwqm_red_peak_list_AD,
								   'FWQM Area AD': fwqm_area_list_AD
								   }

	master_dict['PL FWHM Analsys All'] = {'PL Time': time_list,
							   'Peak eV': peak_ev_list,
							   'Peak Intensity': peak_intensity_list,
							   'FWHM': fwhm_list,
							   'FWHM Blue': fwhm_blue_peak_list,
							   'FWHM Red': fwhm_red_peak_list,
							   'FWHM Area': fwhm_area_list,
							   'FWQM': fwqm_list,
							   'FWQM Blue': fwqm_blue_peak_list,
							   'FWQM Red': fwqm_red_peak_list,
							   'FWQM Area': fwqm_area_list
							   }

	with open(file_folder+'/'+file_name+'.json', 'w') as outfile:
		json.dump(master_dict, outfile)



def analyze_PL_Difference(file_folder, file_name, video):
	'''Makes video of normalized PL and its shift and respected area of overlap'''

	master_dict = json.load(open(file_folder+'/'+file_name+'.json'))

	dripTime = master_dict['Parameters']['Drip Time']

	pl_normalized = master_dict['PL Corrected']['Normalized Spectra']
	pl_energies =  master_dict['PL Corrected']['Energy']


	x_label = 'Energy (ev)'
	y_label = 'Intensity (a.u.)'
	y_min = -1
	y_max = 1

	last_PL = pl_normalized[list(pl_normalized.keys())[-1]]
	smoothed_last_PL = (savgol_filter(last_PL, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist()

	# arbitrary name and number to save jpeg
	nameNo = 0
	intermediate_name = 'nameGraph'


	img_list = []
	failed_list = []

	redshift_area_List = []
	redshift_time_List = []
	redshift_area_List_AD = []
	redshift_time_List_AD = []

	for key in pl_normalized.keys():
		plt.clf()
		plt.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=True)

		redshift_time_List.append(key)

		measurment = (pl_normalized[key])
		smoothed = (savgol_filter(measurment, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist()

		if float(key) >= (dripTime-5):
			# find peak and full width half max
			try:
				pl_difference = np.array(measurment) - np.array(last_PL)
				smoothed_pl_difference = (savgol_filter(pl_difference, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist()

				redshift_area = 0
				for i in pl_difference:
					if i>0:
						redshift_area += i

				plt.plot(pl_energies, smoothed, color='b')
				plt.plot(pl_energies, smoothed_last_PL, color='k')
				plt.plot(pl_energies, smoothed_pl_difference, color='r')
				plt.fill_between(pl_energies, smoothed_pl_difference, color='r')

				plt.title("Time {:.2f} seconds, Difference {:.2f} (Drip @ {:.2f})".format(float(key), redshift_area, round(dripTime, 1)))      # plot title is time, which is column name

				redshift_area_List.append(redshift_area)
				redshift_area_List_AD.append(redshift_area)
				redshift_time_List_AD.append(key)


			except: # if can't find a peak then plot just smoothed and noisy PL data
				# print(key)
				failed_list.append(key)

				plt.plot(pl_energies, smoothed, color='b')
				plt.title("Time {:.2f} seconds".format(float(key)))      # plot title is time, which is column name
				redshift_area_List.append(np.nan)
				redshift_area_List_AD.append(np.nan)
				redshift_time_List_AD.append(key)

		else:   # if measurement  happens before drip time
			plt.plot(pl_energies, smoothed, color='b')
			plt.title("Time {:.2f} seconds".format(float(key)))      # plot title is time, which is column name
			redshift_area_List.append(np.nan)



		plt.axis([None, None, y_min, y_max])
		plt.xlabel(x_label)
		plt.ylabel(y_label)

		# plt.show()

		if video == True:
			img_save_name = '{}{}{}.png'.format(file_folder, intermediate_name, nameNo)
			plt.savefig(img_save_name)
			img_list.append(img_save_name)
			nameNo += 1          # adds a 1 to each file name so it its read in correct order


	# print("drip time: ", dripTime, ' ', redshift_time_List_AD[0])
	# print(file_name, ' Failed Times: ', failed_list)

	## Save images
	if video == True:
		images = img_list#[img for img in os.listdir(fileFolder) if img.endswith(".png")]
		# print(images)

		frame = cv2.imread(os.path.join(file_folder, images[0]))
		height, width, layers = frame.shape

		# calculate mean time between measurements to set the video to real speed
		plTime = [float(key) for key in pl_normalized.keys()]
		sampleInterval = statistics.mean([(plTime[i+1]-plTime[i]) for i in range(len(plTime)-1)])
		fps = 1/sampleInterval * 1    # times 1x (real) speed
		# print(sampleInterval)

		fourcc = cv2.VideoWriter_fourcc(*'mp4v')
		video_name = file_folder + '/PL Analysis/Difference Video/' + file_name + '_PL_Norm_vid.mp4'
		video = cv2.VideoWriter(video_name, fourcc, fps, (width, height))

		for image in images:
			img = os.path.join(file_folder, image)
			video.write(cv2.imread(img))
			os.remove(img)

		cv2.destroyAllWindows()
		video.release()


	# Save results
	redshift_time_List = [float(t) for t in redshift_time_List]
	redshift_time_List_AD = [float(t) for t in redshift_time_List_AD]

	master_dict['PL Redshift Analysis'] = {'All Redshift Area': redshift_area_List,
									'All Time': redshift_time_List,
									'AD Redshift Area': redshift_area_List_AD,
									'AD Time': redshift_time_List_AD}


	with open(file_folder+'/'+file_name+'.json', 'w') as outfile:
		json.dump(master_dict, outfile)



def selected_PL(file_folder, file_name):
	master_dict = json.load(open(file_folder+'/'+file_name+'.json'))

	dripTime = master_dict['Parameters']['Drip Time']

	PL_corrected = master_dict['PL Corrected']['Spectra']

	lDripTimes = np.array([-1, 0.25, 1, 2, 4, 8, 15])
	lDripTimes += dripTime


	# exact times, keys, of interest after drip for PL
	select_pl = {}
	select_pl_times = []
	for l in lDripTimes:
		colHeader = min(list(PL_corrected.keys()), key=lambda x: abs(float(x)-float(l)))

		pl_time = ('{:.2f}').format(float(colHeader))

		select_pl_times.append(pl_time)

		select_pl[colHeader] = PL_corrected[colHeader]


	pl_last = list(PL_corrected.keys())[-1]
	pl_last_time = ('{:.2f}').format(float(pl_last))
	select_pl_times.append(pl_last_time)

	select_pl[pl_last] = PL_corrected[pl_last]


	master_dict['PL Selected'] = {'Spectra': select_pl,
								  'Times': select_pl_times}

	with open(file_folder+'/'+file_name+'.json', 'w') as outfile:
		json.dump(master_dict, outfile)




#folder = '/Users/nathanwoodward/Library/CloudStorage/GoogleDrive-nwoodwa@ncsu.edu/Shared drives/MSE-Amassian Group/Spinner/Self-Driving/1717/1.5mol 1717/24 Feb 2024/SD'
#name = '1717CB_10_analyzed'
#analyze_PL_FWHM(folder, name, True)











