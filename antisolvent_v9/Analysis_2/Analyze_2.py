from .Film_Classification_2 import classify_Film
from .UVvis_Analysis_2 import correct_UVvis, UVvis_video, track_abs, selected_abs
from .Plot_Data_2 import plot_Data
from .PL_Analysis_2_video import correct_PL, analyze_PL_FWHM, analyze_PL_Difference, selected_PL
import json

def analyze_Data(file_folder, file_name):
    """
    This is the robust analysis pipeline for the self-driving system.
    """
    print("--- Starting Full Analysis Pipeline ---")
    
    try:
        master_dict = json.load(open(f'{file_folder}/{file_name}.json'))
        analysis_file_name = f'{file_name}_analyzed'
        with open(f'{file_folder}/{analysis_file_name}.json', 'w') as outfile:
            json.dump(master_dict, outfile)

        print("Step 1: Classifying film...")
        classify_Film(file_folder, file_name, analysis_file_name)

        print("Step 2: Analyzing PL data...")
        correct_PL(file_folder, analysis_file_name)
        analyze_PL_FWHM(file_folder, analysis_file_name, False)
        analyze_PL_Difference(file_folder, analysis_file_name, False)
        selected_PL(file_folder, analysis_file_name)

        print("Step 3: Analyzing UV-vis data...")
        correct_UVvis(file_folder, analysis_file_name)
        track_abs(file_folder, analysis_file_name)
        selected_abs(file_folder, analysis_file_name)

        print("Step 4: Plotting data...")
        plot_Data(file_folder, analysis_file_name)
        
        print("--- Analysis Pipeline Complete ---")

    except FileNotFoundError:
        print(f"ERROR: Could not find JSON file to analyze: {file_folder}/{file_name}.json")
    except Exception as e:
        print(f"An error occurred during the analysis pipeline: {e}")


