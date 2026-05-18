import os

def check_n_make(main_folder, sub_folders):
	if not os.path.exists(main_folder+sub_folders):
			os.makedirs(main_folder+sub_folders)



def create_folders(file_folder):

	## for images that are classified
	check_n_make(file_folder, '/images')

	## Analsysis Plots
	check_n_make(file_folder, '/Snapshots')

	## for PL
	check_n_make(file_folder, '/PL Analysis')
	check_n_make(file_folder, '/PL Analysis/FWHM Video')
	check_n_make(file_folder, '/PL Analysis/Difference Video')
	# check_n_make(file_folder, '/PL Analysis/Confinement Size')

	## for UV-vis
	check_n_make(file_folder, '/UVvis Analysis')
	check_n_make(file_folder, '/UVvis Analysis/Video')


	#check_n_make(file_folder, )


