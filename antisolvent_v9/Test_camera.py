"""
Quick camera capture tester for framing/cropping.


Usage (from Self_Driving_V9 folder in holmes_env):
   python test_camera.py --out ./test_frames --index 0


Each run grabs one frame with the current crop settings from Dual_Send_Camera.py
and saves it to the output directory with a timestamped filename.
"""


import argparse
import os
import time
from datetime import datetime
import cv2




DEFAULT_OUT_DIR = r"C:\Users\Admin\Desktop\RoboCoater-Data\TestCamera"


def capture_frame(cam_index: int, out_dir: str):
   os.makedirs(out_dir, exist_ok=True)
   cam = cv2.VideoCapture(cam_index)
   if not cam.isOpened():
       print(f"ERROR: Could not open camera at index {cam_index}")
       return


   ret, frame = cam.read()
   if not ret or frame is None:
       print("ERROR: Failed to read frame from camera.")
       cam.release()
       return


   # Apply the same crop as in Dual_Send_Camera.py (adjust there if needed)
   top, bottom, left, right = 70, 370, 120, 460
   frame_cropped = frame[top:bottom, left:right]
   frame_cropped = cv2.resize(frame_cropped, (275, 275), interpolation=cv2.INTER_LINEAR)


   ts = datetime.now().strftime("%Y%m%d_%H%M%S")
   fname = os.path.join(out_dir, f"camera_test_{ts}.jpg")
   cv2.imwrite(fname, frame_cropped)
   print(f"Saved test frame: {fname}")


   cam.release()




if __name__ == "__main__":
   parser = argparse.ArgumentParser(description="Capture a single test frame for framing/cropping.")
   parser.add_argument(
       "--out",
       type=str,
       default=DEFAULT_OUT_DIR,
       help="Output directory for saved frame.",
   )
   parser.add_argument("--index", type=int, default=0, help="Camera index (default 0).")
   args = parser.parse_args()


   capture_frame(args.index, args.out)





