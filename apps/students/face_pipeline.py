"""
Face pipeline using OpenCV YuNet (detection) + SFace (recognition).
Models are auto-downloaded to ml_models/ on first use.
"""
import os
import io
import hashlib
import urllib.request
import logging
import numpy as np
import cv2
from PIL import Image
from django.conf import settings

logger = logging.getLogger(__name__)

ML_DIR = settings.ML_MODELS_DIR
ML_DIR.mkdir(exist_ok=True)

YUNET_PATH = ML_DIR / 'face_detection_yunet_2023mar.onnx'
SFACE_PATH = ML_DIR / 'face_recognition_sface_2021dec.onnx'

YUNET_URL = (
    'https://github.com/opencv/opencv_zoo/raw/main/models/'
    'face_detection_yunet/face_detection_yunet_2023mar.onnx'
)
SFACE_URL = (
    'https://github.com/opencv/opencv_zoo/raw/main/models/'
    'face_recognition_sface/face_recognition_sface_2021dec.onnx'
)

_detector = None
_recognizer = None
_qr_detector = None


def _ensure_models():
    global _detector, _recognizer, _qr_detector
    if _detector and _recognizer and _qr_detector:
        return

    for path, url in [(YUNET_PATH, YUNET_URL), (SFACE_PATH, SFACE_URL)]:
        if not path.exists():
            logger.info(f"Downloading {path.name} ...")
            urllib.request.urlretrieve(url, path)
            logger.info(f"Downloaded {path.name}")

    _detector = cv2.FaceDetectorYN.create(str(YUNET_PATH), '', (640, 480))
    _recognizer = cv2.FaceRecognizerSF.create(str(SFACE_PATH), '')
    _qr_detector = cv2.QRCodeDetector()


def _pil_to_bgr(image_bytes: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    img = img.resize((640, 480))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def detect_and_embed(image_bytes: bytes) -> dict:
    """
    Run YuNet detection + SFace embedding on raw image bytes.
    Returns dict with keys: success, vector, quality_score, error, image_hash
    """
    _ensure_models()

    image_hash = hashlib.sha256(image_bytes).hexdigest()
    bgr = _pil_to_bgr(image_bytes)
    h, w = bgr.shape[:2]
    _detector.setInputSize((w, h))

    _, faces = _detector.detect(bgr)

    if faces is None or len(faces) == 0:
        return {'success': False, 'error': 'NO_FACE_DETECTED', 'image_hash': image_hash}

    if len(faces) > 1:
        return {'success': False, 'error': 'MULTIPLE_FACES', 'image_hash': image_hash}

    face = faces[0]
    confidence = float(face[-1])

    if confidence < 0.75:
        return {'success': False, 'error': 'LOW_CONFIDENCE', 'image_hash': image_hash}

    # Laplacian blur check
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if lap_var < 60:
        return {'success': False, 'error': 'BLUR_DETECTED', 'image_hash': image_hash}

    aligned = _recognizer.alignCrop(bgr, face)
    raw_feature = _recognizer.feature(aligned)
    vec = raw_feature.flatten().astype(np.float32)
    # L2 normalize
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return {
        'success': True,
        'vector': vec,
        'quality_score': round(confidence, 4),
        'image_hash': image_hash,
    }


def compare_embeddings(live_vec: np.ndarray, stored_vecs: list) -> float:
    """
    Compute max cosine similarity between live_vec and a list of stored vectors.
    Returns a float in [-1, 1]; higher = better match.
    """
    if not stored_vecs:
        return 0.0
    scores = [float(np.dot(live_vec, sv)) for sv in stored_vecs]
    return max(scores)


def passive_liveness_check(frame_vectors: list) -> bool:
    """
    Basic liveness: check that at least 2 frames exist and that embeddings
    are temporally consistent (not identical, indicating a real moving face).
    Returns True if liveness passes.
    """
    if len(frame_vectors) < 2:
        return False
    # Check that frames are not identical (would indicate a static photo)
    for i in range(1, len(frame_vectors)):
        diff = np.linalg.norm(frame_vectors[i] - frame_vectors[i - 1])
        if diff > 0.001:   # some natural variation expected, relaxed for stable webcams
            return True
    return False


def process_biometric_frame(image_bytes: bytes, stored_vecs: list = None) -> dict:
    """
    Simultaneously detects QR payloads and Face bounding boxes from a single frame.
    Returns scaling coordinates relative to 640x480.
    """
    _ensure_models()
    
    bgr = _pil_to_bgr(image_bytes)
    h, w = bgr.shape[:2]
    
    result = {
        'qr_data': None,
        'qr_box': None,    # [x, y, w, h]
        'face_box': None,  # [x, y, w, h]
        'face_match': False,
        'original_dims': [w, h]
    }
    
    # 1. Detect QR Code
    data, bbox, _ = _qr_detector.detectAndDecode(bgr)
    if data and bbox is not None and len(bbox) > 0:
        result['qr_data'] = data
        pts = bbox[0]
        x1, y1 = float(min(pts[:, 0])), float(min(pts[:, 1]))
        x2, y2 = float(max(pts[:, 0])), float(max(pts[:, 1]))
        result['qr_box'] = [x1, y1, x2 - x1, y2 - y1]
        
    # 2. Detect Face
    _detector.setInputSize((w, h))
    _, faces = _detector.detect(bgr)
    
    if faces is not None and len(faces) > 0:
        # Take the most prominent face
        face = faces[0]
        confidence = float(face[-1])
        
        # YuNet bounding box is [x, y, w, h] in the first 4 elements
        if confidence >= 0.70:
            result['face_box'] = [float(face[0]), float(face[1]), float(face[2]), float(face[3])]
            
            # If we already have stored vecs, check for match
            if stored_vecs:
                try:
                    aligned = _recognizer.alignCrop(bgr, face)
                    raw_feature = _recognizer.feature(aligned)
                    vec = raw_feature.flatten().astype(np.float32)
                    norm = np.linalg.norm(vec)
                    if norm > 0:
                        vec = vec / norm
                        
                    score = compare_embeddings(vec, stored_vecs)
                    if score >= 0.75:
                        result['face_match'] = True
                except Exception as e:
                    logger.error(f"SFace processing error: {e}")
                    
    return result
