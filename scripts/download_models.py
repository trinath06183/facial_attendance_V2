import os
from pathlib import Path
import urllib.request
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
ML_DIR = BASE_DIR / 'ml_models'

MODELS = {
    'face_detection_yunet_2023mar.onnx': 'https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx',
    'face_recognition_sface_2021dec.onnx': 'https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx'
}

def download_models():
    ML_DIR.mkdir(exist_ok=True)
    print(f"Checking for models in {ML_DIR} ...")
    
    for filename, url in MODELS.items():
        filepath = ML_DIR / filename
        if not filepath.exists():
            print(f"Downloading {filename} (approx 2-3MB)...")
            try:
                urllib.request.urlretrieve(url, filepath)
                print(f"  ✓ Saved to {filepath}")
            except Exception as e:
                print(f"  ✗ Failed to download {filename}: {e}")
                sys.exit(1)
        else:
            print(f"  ✓ {filename} already exists.")
            
    print("\nModels are ready. You can now use the recognition pipeline.")

if __name__ == '__main__':
    download_models()
