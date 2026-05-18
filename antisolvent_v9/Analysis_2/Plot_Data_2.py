import pandas as pd
import numpy as np
from numpy import ma

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import ticker, cm

import matplotlib.gridspec as gridspec
import matplotlib.style
from matplotlib.ticker import MultipleLocator, AutoMinorLocator
import cv2

from scipy.signal import savgol_filter
from scipy.ndimage.filters import gaussian_filter1d

import json

import os

def plot_Data(fileFolder, fileName):
	master_dict = json.load(open(fileFolder+'/'+fileName+'.json'))

	dripTime = master_dict['Parameters']['Drip Time']
	dripRate = master_dict['Parameters']['Drip Rate']
	dripVol = master_dict['Parameters']['Drip Volume']
	drip_duration = (dripVol / dripRate) * 0.06


	## Plot general figure
	fig = plt.figure(figsize=(22, 8))
	gs = gridspec.GridSpec(4, 5, figure=fig)
	right_cell = gs[0:4, 3:5]
	stack = gridspec.GridSpecFromSubplotSpec(4, 1, right_cell, hspace=0.0)

	# create sub plots as grid
	plt1 = plt.subplot(gs[1:3, 0])
	plt2a = plt.subplot(gs[0:2, 1])
	plt2b = plt.subplot(gs[2:4, 1])
	plt3a = plt.subplot(gs[0:2, 2])
	plt3b = plt.subplot(gs[2:4, 2])
	plt4a = plt.subplot(stack[0, 0])
	plt4b = plt.subplot(stack[1, 0])
	plt4c = plt.subplot(stack[2, 0])
	plt4d = plt.subplot(stack[3, 0])

	titleFig = ('Drip Time: {:.2f} Seconds   Rate: {:.2f} MM   Volume {:.2f} uL   Drip Duration {:.2f} Seconds').format(dripTime, dripRate, dripVol, drip_duration)
	fig.suptitle(titleFig, fontsize=18)


	### PL
	select_pl = master_dict['PL Selected']['Spectra']
	pl_corrected = master_dict['PL Corrected']['Spectra']
	pl_wavelength = master_dict['PL Corrected']['Wavelength']
	pl_energies = master_dict['PL Corrected']['Energy']

	### Absorbance
	slected_abs = master_dict['Absorbance Selected']['Spectra']
	abs_corrected = master_dict['Absorbance Corrected']['Spectra']
	abs_wavelength = master_dict['Absorbance Corrected']['Wavelength']
	abs_times = [float(key) for key in abs_corrected.keys()]

	# all values are calculated starting 5 seconds before drip time
	time_after = 30

	PL_FWHM_time_AD = master_dict['PL FWHM Analsys AD']['PL Time AD']
	maxPLFWHM_Time_Index = PL_FWHM_time_AD.index(min(PL_FWHM_time_AD, key=lambda x: abs(x - (dripTime + time_after))))

	PL_Peak = master_dict['PL FWHM Analsys AD']['Peak eV AD'][:maxPLFWHM_Time_Index]
	PL_Blue_Peak = master_dict['PL FWHM Analsys AD']['FWHM Blue AD'][:maxPLFWHM_Time_Index]
	PL_Red_Peak = master_dict['PL FWHM Analsys AD']['FWHM Red AD'][:maxPLFWHM_Time_Index]
	PL_FWHM = master_dict['PL FWHM Analsys AD']['FWHM AD'][:maxPLFWHM_Time_Index]
	PL_FWHM_Area = master_dict['PL FWHM Analsys AD']['FWHM Area AD'][:maxPLFWHM_Time_Index]
	PL_Peak_Intesnity = master_dict['PL FWHM Analsys AD']['Peak Intensity AD'][:maxPLFWHM_Time_Index]


	PL_Norm_time_AD = master_dict['PL Redshift Analysis']['AD Time']
	maxPLNorm_Time_Index = PL_Norm_time_AD.index(min(PL_Norm_time_AD, key=lambda x: abs(float(x) - (dripTime + time_after))))

	PL_Norm_Diff  = master_dict['PL Redshift Analysis']['AD Redshift Area'][:maxPLNorm_Time_Index] # calculated starting at drip time

	minAbs_Time_Index = abs_times.index(min(abs_times, key=lambda x: abs(x - (dripTime - 5))))
	maxAbs_Time_Index = abs_times.index(min(abs_times, key=lambda x: abs(x - (dripTime + time_after))))

	abs_710 = master_dict['Absorbance Tracked All']['710'][minAbs_Time_Index:maxAbs_Time_Index]	# values are calculated for the entire spin coating duration
	abs_532 = master_dict['Absorbance Tracked All']['532'][minAbs_Time_Index:maxAbs_Time_Index]


	# print(len(master_dict['PL FWHM Analsys AD']['PL Time AD']), len(master_dict['PL FWHM Analsys AD']['Peak eV AD']), '\n',
	# 	  len(master_dict['PL FWHM Analsys AD']['FWHM Blue AD']), len(master_dict['PL FWHM Analsys AD']['FWHM AD']), '\n',
	# 		len(PL_Peak), len(abs_710), len(PL_Norm_Diff))
	#
	# print(len(PL_FWHM_time_AD), len(PL_Norm_time_AD), '\n',
	# 	  len(abs_times[minAbs_Time_Index:maxAbs_Time_Index]), len(PL_FWHM_time_AD[:maxPLFWHM_Time_Index]), len(PL_Norm_time_AD[:maxPLNorm_Time_Index]))

	pl_axis_times = np.linspace(-5, time_after, len(PL_FWHM_time_AD[:maxPLFWHM_Time_Index]))
	abs_axis_times = np.linspace(-5, time_after, len(abs_times[minAbs_Time_Index:maxAbs_Time_Index]))



	## Plot image of film
	image_name = master_dict['Film Ranking']['Image Name']
	image_rank = 'Film Rank ' + master_dict['Film Ranking']['Rank']

	# film_image = plt.imread(fileFolder + '/images/' +image_name.split('/')[-1])
	film_image = plt.imread(fileFolder + '/images/' + image_name)

	# Img = cv2.imread(fileFolder+'/'+imageName)
	# film_Img = cv2.cvtColor(Img, cv2.COLOR_BGR2RGB)

	plt1.imshow(film_image)
	plt1.set_yticklabels([])
	plt1.set_xticklabels([])
	plt1.set_xticks([])
	plt1.set_yticks([])
	plt.setp(plt1.spines.values(), color=None)
	plt1.set_xlabel(image_rank, fontsize = 18)
	# plt1.axis('off')



	## Select PL
	for key in select_pl.keys():
		# plt2a.scatter(pl_energies, select_pl[key], s=1, alpha=0.5, label=None)
		plt2a.plot(pl_energies, (savgol_filter(select_pl[key], 15, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(),
				   label= ('{:.2f}').format(float(key)))

	plt2a.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=True)
	plt2a.legend(prop={'size': 7}, title="Times (s)")
	plt2a.set_title("PL at Selected Times")
	# plt2a.set_xlabel("Wavelength (nm)")
	plt2a.set_xlabel("PL Energy (eV)")
	plt2a.set_ylabel("PL Inensity (a.u.)")


	## In Situ PL Heat Map
	df_pl_corrected = pd.DataFrame.from_dict(pl_corrected)
	pl_times = [float(key) for key in pl_corrected.keys()]


	X, Y = np.meshgrid(pl_times, pl_energies)
	Z = np.array(df_pl_corrected)
	levels = np.linspace(Z.min(), Z.max(), 256)
	contourPlot = plt3a.contourf(X, Y, Z, levels=levels, cmap=cm.rainbow)
	cpBar = fig.colorbar(contourPlot, ax=plt3a)
	cpBar.ax.tick_params(size=0)
	plt3a.set_title("PL Over Time")
	plt3a.set_xlabel('Time (seconds)')
	plt3a.set_ylabel('PL Energy (eV)')
	cpBar.ax.set_ylabel('PL Intensity (a.u.)')


	## Select Absorbance
	for key in slected_abs.keys():
		# plt2b.scatter(abs_wavelength, slected_abs[key], s=1, alpha=0.5, label=None)
		# plt2b.plot(abs_wavelength, (savgol_filter(slected_abs[key], 21, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), label= ('{:.2f}').format(float(key)))
		plt2b.plot(abs_wavelength, (gaussian_filter1d(slected_abs[key], sigma=4)), label= ('{:.2f}').format(float(key)))

	plt2b.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=True)
	plt2b.legend(prop={'size': 7}, title="Times (s)")
	plt2b.set_title('Absorbance at Selected Times')
	plt2b.set_xlabel("Wavelength (nm)")
	plt2b.set_ylabel("Absorbance (a.u.)")

	## In Situ Absorbance Heat Map
	df_abs_corrected = pd.DataFrame.from_dict(abs_corrected)
	X, Y = np.meshgrid(abs_times, abs_wavelength)
	Z = np.array(df_abs_corrected)
	levels = np.linspace(Z.min(), Z.max(), 256)
	contourPlot = plt3b.contourf(X, Y, Z, levels=levels, cmap=cm.rainbow)
	cpBar = fig.colorbar(contourPlot, ax=plt3b)
	cpBar.ax.tick_params(size=0)
	plt3b.set_title('Absorbance Over Time')
	plt3b.set_xlabel('Time (seconds)')
	plt3b.set_ylabel('Wavelengths (nm)')
	cpBar.ax.set_ylabel('Absorbance (a.u.)')



	y_label_size = 9

	plt4a.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=True, labelbottom=False)
	plt4b.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=False, labelbottom=False)
	plt4c.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=False, labelbottom=False)
	plt4d.tick_params(which='both', axis='both', direction='in', bottom=True, top=True, left=True, right=False)

	## plot formatting
	plt4a.xaxis.set_minor_locator(AutoMinorLocator())
	plt4b.xaxis.set_minor_locator(AutoMinorLocator())
	plt4c.xaxis.set_minor_locator(AutoMinorLocator())
	plt4d.xaxis.set_minor_locator(AutoMinorLocator())


## Top: PL band energy tracked
	plt4a.set_ylabel('PL Peak (eV)', fontsize=y_label_size)

	# PL Peak
	plt4a.scatter(pl_axis_times, PL_Peak, s=10, alpha=0.5, color='k')
	plt4a.plot(pl_axis_times, (savgol_filter(PL_Peak, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='k', zorder=10)

	# PL Blue FWHM Peak
	plt4a.scatter(pl_axis_times, PL_Blue_Peak, s=10, alpha=0.3, color='b')
	plt4a.plot(pl_axis_times, (savgol_filter(PL_Blue_Peak, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='b')

	# PL Red FWHM Peak
	plt4a.scatter(pl_axis_times, PL_Red_Peak, s=10, alpha=0.3, color='r')
	plt4a.plot(pl_axis_times, (savgol_filter(PL_Red_Peak, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='r')

	# PL Difference ## right y axis
	plt4a_R = plt4a.twinx()
	plt4a_R.set_ylabel('PL Confinement Area (a.u.)', color='tab:gray', fontsize=y_label_size)
	plt4a_R.scatter(pl_axis_times, PL_Norm_Diff, s=10, alpha=0.15, color='tab:gray')
	# ax_0_R.plot(pl_axis_times, (savgol_filter(PL_Norm_Diff, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='tab:gray')
	plt4a_R.fill_between(pl_axis_times, (savgol_filter(PL_Norm_Diff, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), alpha=0.3, color='tab:gray')
	plt4a_R.tick_params(axis='y', color='tab:gray', labelcolor='tab:gray')


## FWHM Plots
	plt4b.set_ylabel('FWHM (eV)', fontsize=y_label_size)
	plt4b.scatter(pl_axis_times, PL_FWHM, s=10, alpha=0.7, color='k', zorder=10)
	plt4b.plot(pl_axis_times, (savgol_filter(PL_FWHM, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='k', zorder=10)

	plt4b_R = plt4b.twinx()
	plt4b_R.set_ylabel('Edge to Peak Width (eV)', color='tab:gray', fontsize=y_label_size)
	plt4b_R.tick_params(axis='y', color='tab:gray', labelcolor='tab:gray')

	blue_symetric = np.array(PL_Blue_Peak) - np.array(PL_Peak)
	plt4b_R.scatter(pl_axis_times, blue_symetric, s=10, color='lightgray', zorder=0)
	plt4b_R.plot(pl_axis_times, (savgol_filter(blue_symetric, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='b')

	red_symetric = np.array(PL_Peak) - np.array(PL_Red_Peak)
	plt4b_R.scatter(pl_axis_times, red_symetric, s=10, alpha=0.7, color='gray', zorder=0)
	plt4b_R.plot(pl_axis_times, (savgol_filter(red_symetric, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='r')


## PL Arera and Intesnity Plots
	plt4c.set_ylabel('PL Peak Intensity (a.u.)', fontsize=y_label_size)
	plt4c.scatter(pl_axis_times, PL_Peak_Intesnity, s=10, alpha=0.5, color='k')
	plt4c.plot(pl_axis_times, (savgol_filter(PL_Peak_Intesnity, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='k')

	plt4c_R = plt4c.twinx()
	plt4c_R.set_ylabel('FWHM Area (a.u.)', color='tab:gray', fontsize=y_label_size)
	plt4c_R.tick_params(axis='y', color='tab:gray', labelcolor='tab:gray')
	plt4c_R.scatter(pl_axis_times, PL_FWHM_Area, s=10, alpha=0.15, color='tab:gray')
	# ax_2_R.plot(pl_axis_times, (savgol_filter(PL_FWHM_Area, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='tab:gray')
	plt4c_R.fill_between(pl_axis_times, (savgol_filter(PL_FWHM_Area, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), alpha=0.3, color='tab:gray')

## Bottom: OD of 710 and 532 nm
	plt4d.set_ylabel('O.D. at  710 nm (a.u.)', fontsize=y_label_size)
	plt4d.scatter(abs_axis_times, abs_710, s=10, alpha=0.5, color='k')
	plt4d.plot(abs_axis_times, (savgol_filter(abs_710, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='k')

	plt4d_R = plt4d.twinx()
	plt4d_R.set_ylabel('O.D. at 532 nm (a.u.)', color='tab:gray', fontsize=y_label_size)
	plt4d_R.tick_params(axis='y', color='tab:gray', labelcolor='tab:gray')
	plt4d_R.scatter(abs_axis_times, abs_532, s=10, alpha=0.5, color='tab:gray')
	plt4d_R.plot(abs_axis_times, (savgol_filter(abs_532, 5, 2, deriv=0, delta=1.0, axis=-1, mode='interp', cval=0.0)).tolist(), color='tab:gray')

# ## Set Axis Range
# 	plt4a.set_ylim(1.55, 1.9)
# 	plt4b.set_ylim(0.001, 0.19)
# 	plt4c.set_ylim(1, 60000)
# 	plt4d.set_ylim(0, 0.4)
#
# 	plt4a_R.set_ylim(1, 250)
# 	plt4b_R.set_ylim(.001, 0.1)
# 	plt4c_R.set_ylim(1, 5000)
# 	plt4d_R.set_ylim(0, 1.2)
#
# 	## Set Axis Range
# 	plt4a.set_ylim(1.55, 1.85)
# 	plt4b.set_ylim(0, 0.19)
# 	plt4c.set_ylim(0, 60000)
# 	plt4d.set_ylim(0, 0.4)
#
# 	plt4a_R.set_ylim(0, 250)
# 	plt4b_R.set_ylim(0, 0.1)
# 	plt4c_R.set_ylim(0, 5000)
# 	plt4d_R.set_ylim(0, 1.2)

	plt4a_R.tick_params(direction='in', right=True)
	plt4b_R.tick_params(direction='in', right=True)
	plt4c_R.tick_params(direction='in', right=True)
	plt4d_R.tick_params(direction='in', right=True)

	plt4d.set_xlabel('Time (seconds) with respect to drip')

	plt.tight_layout()
	plt.savefig(fileFolder + '/Snapshots/' + fileName + '_Analyzed.jpeg', dpi=600)
	# plt.show()
	# plt.close()


# f = '/Users/nathanwoodward/Library/CloudStorage/GoogleDrive-nwoodwa@ncsu.edu/Shared drives/MSE-Amassian Group/Spinner/Self-Driving/1717/1.5mol 1717/24 Feb 2024/SD'
# # plot_Data(f, '1717CB_0_analyzed')
#
# ## to generate list of files
# file_List = []
# for file in os.listdir(f):
# 	# print(file)
# 	if file.endswith('analyzed.json'):
# 		file_List.append(file[:-5])	# print without the .json
#
# print(file_List)
#
# # plot_Data(f, file_List[0])
# for file in file_List:
# 	plot_Data(f, file)
# 	input("continue")
