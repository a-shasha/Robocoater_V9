from joblib import load
import cv2
import os
import numpy as np
import json

# IMPORTANT: This path will likely need to be updated for your lab PC.
# It should point to the directory containing the .joblib model file.
ml_model_folder = r"C:\Users\Admin\Documents\Automated-Spin-Coating\In-Situ\Dual\Self_Driving_V9\Analysis_2"
my_model_file = 'randomForest_filmClass_V2.joblib'
my_model = load(os.path.join(ml_model_folder, my_model_file))

img_Ranking = ['Film_I', 'Film_II', 'Film_III', 'Film_IV']
img_Name = ['film_1', 'film_2', 'film_3', 'film_4']
img_Score = {'film_1': 0.0, 'film_2': 0.33, 'film_3': 0.66, 'film_4': 1.0}
img_Score_Name = ['I', 'II', 'III', 'IV']


def classify_Film(file_folder, img_file_name, analysis_file_name):
    master_dict = json.load(open(os.path.join(file_folder, analysis_file_name + '.json')))
    img_file = os.path.join(file_folder, img_file_name + '.jpg')

    try:
        img_bgr = cv2.imread(img_file, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise FileNotFoundError(f"Image file not found or could not be read: {img_file}")
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    except Exception as e:
        print(f"Error reading image file: {e}")
        # Handle error case: assign a default low score
        film_Score = 0.0
        film_Rank = 'Error'
        film_Ranking_Name = 'Error_Reading_Image'
        new_image_name = img_file_name + '_error.jpg'
    else:
        # Image loaded successfully, proceed with classification
        img_data = img.reshape(1, -1)

        # Make prediction using the ML model
        film_prediction = my_model.predict(img_data)[0]
        print(f"ML Model Prediction: {img_Ranking[film_prediction]}")

        # --- MANUAL OVERRIDE REMOVED FOR AUTONOMOUS OPERATION ---
        # The 'film_prediction' from the model is now used directly.
        # ---

        # Rename and move the image file based on its classification
        new_image_name = f"{img_file_name}_{img_Name[film_prediction]}.jpg"
        images_subfolder = os.path.join(file_folder, 'images')
        if not os.path.exists(images_subfolder):
            os.makedirs(images_subfolder)
        new_image_file = os.path.join(images_subfolder, new_image_name)

        # --- FIX for FileExistsError ---
        # Check if the destination file already exists and remove it if it does.
        if os.path.exists(new_image_file):
            os.remove(new_image_file)
        # ---

        # Use os.rename for moving the file
        try:
            os.rename(img_file, new_image_file)
        except OSError as e:
            print(f"Error moving image file: {e}")
            # If rename fails (e.g., across different drives), try copy and delete
            try:
                import shutil
                shutil.copy2(img_file, new_image_file)
                os.remove(img_file)
            except Exception as copy_e:
                print(f"Failed to copy and delete image file: {copy_e}")

        film_Score = img_Score[img_Name[film_prediction]]
        film_Rank = img_Score_Name[film_prediction]
        film_Ranking_Name = img_Ranking[film_prediction]

    # Update the master dictionary with the classification results
    master_dict['Film Ranking'] = {
        'Score': film_Score,
        'Rank': film_Rank,
        'Rank Name': film_Ranking_Name,
        'Image Name': new_image_name
    }

    with open(os.path.join(file_folder, analysis_file_name + '.json'), 'w') as outfile:
        json.dump(master_dict, outfile)



