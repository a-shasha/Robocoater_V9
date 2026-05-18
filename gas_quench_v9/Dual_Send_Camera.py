print("Dual Send Camera")




import time
import threading
import cv2







#### IMPORTANT NOTICE: ALI
# Video capture/preview is disabled to avoid conflicts during long campaigns.
# If re-enabled in the future, ensure a per-use open/close pattern to avoid stale handles.
# def opencv_camera_feed():
#    ...
# def start_opencv_feed():
#    ...
# def cap_Video(...):
#    ...








# captures single image
def cap_Picture(fileFolder, fileName):
   """Capture a single cropped image with a fresh camera handle."""
   file = fileFolder + '/' + fileName + ".jpg"


   def _snap():
       cam = cv2.VideoCapture(0)
       ok, frame = cam.read()
       cam.release()
       return ok, frame


   ok, frame = _snap()
   if not ok or frame is None:
       # Retry once after a brief pause
       time.sleep(0.5)
       ok, frame = _snap()


   if not ok or frame is None:
       print(f"ERROR: Failed to capture image for {fileName}. Camera may be disconnected or in use.")
       return


   # Cropping dimensions (adjusted from test_camera)
   top, bottom, left, right = 70, 370, 120, 460
   frame = frame[top:bottom, left:right]


   # Enforce final size expected by the classifier (275x275x3 = 226,875 features)
   frame = cv2.resize(frame, (275, 275), interpolation=cv2.INTER_LINEAR)


   if not cv2.imwrite(filename=file, img=frame):
       print(f"ERROR: Failed to write image file for {fileName}. Check path: {file}")
   time.sleep(0.2)




# --- TEST CODE ---
# This code runs automatically when the file is imported, causing a crash.
# It has been commented out to fix the error.




# cap_Picture("C:\\Users\\Admin\\Desktop\\RoboCoater-Data\\TestCamera",'A test_crop')
# live_feed_thread = start_opencv_feed(





