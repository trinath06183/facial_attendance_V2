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
import qrcode

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
    """
    Decode raw image bytes to a contiguous uint8 BGR ndarray.
    Raises ValueError if the bytes cannot be decoded or produce a zero-size image.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    except Exception as e:
        raise ValueError(f'Cannot open image: {e}') from e
    # Use thumbnail to maintain aspect ratio; YuNet works well up to ~960 px.
    img.thumbnail((800, 800), Image.Resampling.LANCZOS)
    # np.ascontiguousarray + explicit uint8 prevents the OpenCV assertion
    # "(flags & FIXED_TYPE) != 0" that fires on non-contiguous or mis-typed arrays.
    arr = np.ascontiguousarray(np.array(img, dtype=np.uint8))
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.shape[0] == 0 or arr.shape[1] == 0:
        raise ValueError(f'Decoded image has unexpected shape: {arr.shape}')
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


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


def process_biometric_frame(image_bytes: bytes, stored_vecs: list = None, threshold: float = None) -> dict:
    """
    Simultaneously detects QR payloads and Face bounding boxes from a single frame.
    Returns scaling coordinates relative to 640x480.

    Args:
        image_bytes: Raw JPEG/PNG bytes from the camera.
        stored_vecs:  List of L2-normalised float32 numpy arrays (enrolled face embeddings).
                     Pass None/empty to skip face matching (QR-only phase).
        threshold:   Cosine-similarity threshold for face_match.
                     Defaults to settings.FACE_MATCH_THRESHOLD (or 0.38 if not set).
    """
    _ensure_models()
    logger.info("Processing biometric frame...")

    # Resolve threshold — fall back to 0.65 (the standard SFace cosine threshold)
    if threshold is None:
        threshold = getattr(settings, 'FACE_MATCH_THRESHOLD', 0.65)

    # Decode and validate the frame — a bad/empty frame returns a structured result
    # instead of crashing with an OpenCV assertion error.
    try:
        bgr = _pil_to_bgr(image_bytes)
    except ValueError as e:
        logger.warning(f'Bad frame rejected: {e}')
        return {
            'qr_data':  None, 'qr_box': None,
            'face_box': None, 'face_match': False,
            'face_score': 0.0, 'original_dims': [0, 0],
            'error': 'INVALID_FRAME',
        }

    h, w = bgr.shape[:2]

    result = {
        'qr_data':       None,
        'qr_box':        None,    # [x, y, w, h]
        'face_box':      None,    # [x, y, w, h]
        'face_match':    False,
        'face_score':    0.0,     # live cosine similarity (for UI feedback)
        'original_dims': [w, h]
    }

    # 1. Detect QR Code
    data, bbox, _ = _qr_detector.detectAndDecode(bgr)
    logger.info(f"QR Detect: data={data} bbox_found={bbox is not None}")
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
        # Take the most prominent (highest-confidence) face
        face = faces[0]
        confidence = float(face[-1])

        # Slightly relaxed threshold (0.60) for real-world scanner environments
        if confidence >= 0.60:
            result['face_box'] = [float(face[0]), float(face[1]), float(face[2]), float(face[3])]

            # If we have stored embeddings, run recognition
            if stored_vecs:
                try:
                    aligned = _recognizer.alignCrop(bgr, face)
                    raw_feature = _recognizer.feature(aligned)
                    vec = raw_feature.flatten().astype(np.float32)
                    norm = np.linalg.norm(vec)
                    if norm > 0:
                        vec = vec / norm

                    score = compare_embeddings(vec, stored_vecs)
                    result['face_score'] = round(float(score), 4)
                    if score >= threshold:
                        result['face_match'] = True
                    logger.info(
                        f"Face ID: score={score:.4f} req={threshold:.4f} match={result['face_match']}"
                    )
                except Exception as e:
                    logger.error(f"SFace processing error: {e}")

    return result
