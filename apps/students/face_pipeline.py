"""
face pipeline using opencv yunet (detection) + sface (recognition).
models are auto-downloaded to ml_models/ on first use.
"""
import os
import io
import hashlib
import urllib.request
import logging
import random
import time
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

LIVENESS_CHALLENGES = ("BLINK", "NOD")


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
    decode raw image bytes to a contiguous uint8 bgr ndarray.
    raises valueerror if the bytes cannot be decoded or produce a zero-size image.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    except Exception as e:
        raise ValueError(f'Cannot open image: {e}') from e
    # use thumbnail to maintain aspect ratio; yunet works well up to ~960 px.
    img.thumbnail((800, 800), Image.Resampling.LANCZOS)
    # np.ascontiguousarray + explicit uint8 prevents the opencv assertion
    # "(flags & fixed_type) != 0" that fires on non-contiguous or mis-typed arrays.
    arr = np.ascontiguousarray(np.array(img, dtype=np.uint8))
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.shape[0] == 0 or arr.shape[1] == 0:
        raise ValueError(f'Decoded image has unexpected shape: {arr.shape}')
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _safe_eye_roi(gray: np.ndarray, center_x: float, center_y: float, half_w: int, half_h: int) -> np.ndarray:
    """returns a clipped grayscale roi around an eye center."""
    h, w = gray.shape[:2]
    x1 = max(0, int(center_x) - half_w)
    y1 = max(0, int(center_y) - half_h)
    x2 = min(w, int(center_x) + half_w)
    y2 = min(h, int(center_y) + half_h)
    if x2 <= x1 or y2 <= y1:
        return np.empty((0, 0), dtype=np.uint8)
    return gray[y1:y2, x1:x2]


def extract_liveness_metrics(bgr: np.ndarray, face: np.ndarray) -> dict | None:
    """
    extract lightweight liveness metrics from yunet landmarks.
    works with built-in opencv outputs (no additional dependencies).
    """
    if face is None or len(face) < 14:
        return None

    face_w = max(float(face[2]), 1.0)
    face_h = max(float(face[3]), 1.0)

    right_eye_x, right_eye_y = float(face[4]), float(face[5])
    left_eye_x, left_eye_y = float(face[6]), float(face[7])
    nose_x, nose_y = float(face[8]), float(face[9])
    mouth_right_x, mouth_right_y = float(face[10]), float(face[11])
    mouth_left_x, mouth_left_y = float(face[12]), float(face[13])

    eye_mid_x = (right_eye_x + left_eye_x) / 2.0
    eye_mid_y = (right_eye_y + left_eye_y) / 2.0
    mouth_mid_y = (mouth_right_y + mouth_left_y) / 2.0

    pitch = (nose_y - eye_mid_y) / face_h
    yaw = (nose_x - eye_mid_x) / face_w
    roll = (right_eye_y - left_eye_y) / face_h
    eye_separation = abs(right_eye_x - left_eye_x) / face_w
    mouth_height = abs(mouth_right_y - mouth_left_y) / face_h
    eye_to_mouth = (mouth_mid_y - eye_mid_y) / face_h

    # "eye texture" proxy for blink: closed eyes often reduce local variance/dark pixels.
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    roi_half_w = max(4, int(face_w * 0.10))
    roi_half_h = max(3, int(face_h * 0.06))

    eye_scores = []
    for cx, cy in ((left_eye_x, left_eye_y), (right_eye_x, right_eye_y)):
        roi = _safe_eye_roi(gray, cx, cy, roi_half_w, roi_half_h)
        if roi.size < 36:
            continue
        std_norm = float(np.std(roi)) / 64.0
        dark_ratio = float(np.mean(roi < 70))
        eye_scores.append((0.7 * std_norm) + (0.3 * dark_ratio))

    if not eye_scores:
        return None

    return {
        "pitch": float(pitch),
        "yaw": float(yaw),
        "roll": float(roll),
        "eye_score": float(sum(eye_scores) / len(eye_scores)),
        "eye_separation": float(eye_separation),
        "eye_to_mouth": float(eye_to_mouth),
        "mouth_height": float(mouth_height),
    }


def create_liveness_state(challenge: str | None = None) -> dict:
    """initialises a serialisable liveness state container for request.session."""
    preferred = str(getattr(settings, "LIVENESS_DEFAULT_CHALLENGE", "BLINK")).upper()
    if challenge not in LIVENESS_CHALLENGES:
        if preferred in LIVENESS_CHALLENGES:
            challenge = preferred
        else:
            challenge = random.choice(LIVENESS_CHALLENGES)
    return {
        "challenge": challenge,
        "passed": False,
        "prompt": "Hold your face steady for liveness calibration...",
        "baseline_frames": 0,
        "frames_after_warmup": 0,
        "baseline_pitch": None,
        "baseline_eye": None,
        "blink_closed_frames": 0,
        "blink_reopen_frames": 0,
        "blink_closed_seen": False,
        "nod_down_seen": False,
        "updated_at": time.time(),
    }


def is_liveness_state_expired(state: dict | None) -> bool:
    """true when a liveness state is stale and should be reset."""
    if not isinstance(state, dict):
        return True
    timeout_s = float(getattr(settings, "LIVENESS_STATE_TIMEOUT_S", 25.0))
    updated_at = float(state.get("updated_at", 0.0) or 0.0)
    return (time.time() - updated_at) > timeout_s


def update_liveness_state(state: dict | None, metrics: dict | None) -> dict:
    """
    updates liveness progress from frame metrics and returns the new state.
    supports random challenge: blink or nod.
    """
    if not isinstance(state, dict):
        state = create_liveness_state()
    elif state.get("challenge") not in LIVENESS_CHALLENGES:
        state["challenge"] = random.choice(LIVENESS_CHALLENGES)

    state["updated_at"] = time.time()
    if state.get("passed"):
        state["prompt"] = "Liveness confirmed."
        return state

    if not metrics:
        state["prompt"] = "Keep your face centered in camera."
        return state

    pitch = float(metrics.get("pitch", 0.0))
    eye_score = float(metrics.get("eye_score", 0.0))

    baseline_frames = int(state.get("baseline_frames", 0))
    baseline_pitch = state.get("baseline_pitch")
    baseline_eye = state.get("baseline_eye")

    if baseline_pitch is None:
        baseline_pitch = pitch
    else:
        baseline_pitch = (0.8 * float(baseline_pitch)) + (0.2 * pitch)

    if baseline_eye is None:
        baseline_eye = eye_score
    else:
        baseline_eye = (0.8 * float(baseline_eye)) + (0.2 * eye_score)

    baseline_frames += 1
    state["baseline_pitch"] = float(baseline_pitch)
    state["baseline_eye"] = float(max(baseline_eye, 1e-6))
    state["baseline_frames"] = baseline_frames

    warmup_frames = int(getattr(settings, "LIVENESS_BASELINE_FRAMES", 6))
    if baseline_frames < warmup_frames:
        state["prompt"] = "Hold still... calibrating liveness."
        return state

    state["frames_after_warmup"] = int(state.get("frames_after_warmup", 0)) + 1
    challenge = state.get("challenge")

    if challenge == "BLINK":
        close_ratio = float(getattr(settings, "LIVENESS_BLINK_DROP_RATIO", 0.92))
        reopen_ratio = float(getattr(settings, "LIVENESS_BLINK_REOPEN_RATIO", 0.98))
        close_needed = int(getattr(settings, "LIVENESS_BLINK_ACTIVE_FRAMES", 2))
        reopen_needed = int(getattr(settings, "LIVENESS_BLINK_REOPEN_FRAMES", 2))
        fallback_frames = int(getattr(settings, "LIVENESS_BLINK_FALLBACK_FRAMES", 45))
        allow_nod_fallback = bool(getattr(settings, "LIVENESS_ALLOW_BLINK_FALLBACK_TO_NOD", False))

        baseline_eye = float(state["baseline_eye"])
        close_threshold = baseline_eye * close_ratio
        reopen_threshold = baseline_eye * reopen_ratio
        closed_seen = bool(state.get("blink_closed_seen"))

        if not closed_seen:
            if eye_score <= close_threshold:
                state["blink_closed_frames"] = int(state.get("blink_closed_frames", 0)) + 1
            else:
                state["blink_closed_frames"] = max(int(state.get("blink_closed_frames", 0)) - 1, 0)

            if int(state.get("blink_closed_frames", 0)) >= close_needed:
                state["blink_closed_seen"] = True
                state["blink_reopen_frames"] = 0
                state["prompt"] = "Great. Now open your eyes."
                return state

            # keep baseline adaptive only in neutral range (reduces false positives).
            neutral_low = baseline_eye * 0.95
            neutral_high = baseline_eye * 1.05
            if neutral_low <= eye_score <= neutral_high:
                state["baseline_eye"] = float((0.98 * baseline_eye) + (0.02 * eye_score))

            state["prompt"] = "Please blink once naturally."
            return state

        if eye_score >= reopen_threshold:
            state["blink_reopen_frames"] = int(state.get("blink_reopen_frames", 0)) + 1
        else:
            state["blink_reopen_frames"] = max(int(state.get("blink_reopen_frames", 0)) - 1, 0)

        if int(state.get("blink_reopen_frames", 0)) >= reopen_needed:
            state["passed"] = True
            state["prompt"] = "Blink detected. Liveness passed."
            return state

        # auto-fallback to nod if blink never triggers in time.
        if (
            allow_nod_fallback
            and fallback_frames > 0
            and int(state.get("frames_after_warmup", 0)) >= fallback_frames
            and not state.get("blink_closed_seen")
        ):
            state["challenge"] = "NOD"
            state["nod_down_seen"] = False
            state["prompt"] = "Blink not detected. Please nod your head once."
            return state

        state["prompt"] = "Blink detected. Please open your eyes fully."
        return state

    # default challenge: nod
    down_delta = float(getattr(settings, "LIVENESS_NOD_DOWN_DELTA", 0.06))
    recover_delta = float(getattr(settings, "LIVENESS_NOD_RECOVER_DELTA", 0.02))
    baseline_pitch = float(state["baseline_pitch"])

    if pitch > baseline_pitch + down_delta:
        state["nod_down_seen"] = True

    if state.get("nod_down_seen") and pitch <= baseline_pitch + recover_delta:
        state["passed"] = True
        state["prompt"] = "Head nod detected. Liveness passed."
        return state

    # adaptive baseline while the user is still neutral.
    if not state.get("nod_down_seen"):
        state["baseline_pitch"] = float((0.96 * baseline_pitch) + (0.04 * pitch))

    state["prompt"] = "Please nod your head once."
    return state


def detect_and_embed(image_bytes: bytes) -> dict:
    """
    run yunet detection + sface embedding on raw image bytes.
    returns dict with keys: success, vector, quality_score, error, image_hash
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
    face_box = [float(face[0]), float(face[1]), float(face[2]), float(face[3])]

    if confidence < 0.75:
        return {'success': False, 'error': 'LOW_CONFIDENCE', 'image_hash': image_hash, 'face_box': face_box}

    # laplacian blur check
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if lap_var < 60:
        return {'success': False, 'error': 'BLUR_DETECTED', 'image_hash': image_hash, 'face_box': face_box}

    aligned = _recognizer.alignCrop(bgr, face)
    raw_feature = _recognizer.feature(aligned)
    vec = raw_feature.flatten().astype(np.float32)
    # l2 normalize
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm

    return {
        'success': True,
        'vector': vec,
        'quality_score': round(confidence, 4),
        'image_hash': image_hash,
        'face_box': face_box,
    }


def compare_embeddings(live_vec: np.ndarray, stored_vecs: list) -> float:
    """
    compute max cosine similarity between live_vec and a list of stored vectors.
    returns a float in [-1, 1]; higher = better match.
    """
    if not stored_vecs:
        return 0.0
    scores = [float(np.dot(live_vec, sv)) for sv in stored_vecs]
    return max(scores)


def passive_liveness_check(frame_vectors: list) -> bool:
    """
    basic liveness: check that at least 2 frames exist and that embeddings
    are temporally consistent (not identical, indicating a real moving face).
    returns true if liveness passes.
    """
    if len(frame_vectors) < 2:
        return False
    # check that frames are not identical (would indicate a static photo)
    for i in range(1, len(frame_vectors)):
        diff = np.linalg.norm(frame_vectors[i] - frame_vectors[i - 1])
        if diff > 0.001:   # some natural variation expected, relaxed for stable webcams
            return True
    return False


def process_biometric_frame(image_bytes: bytes, stored_vecs: list = None, threshold: float = None) -> dict:
    """
    simultaneously detects qr payloads and face bounding boxes from a single frame.
    returns scaling coordinates relative to 640x480.

    args:
        image_bytes: raw jpeg/png bytes from the camera.
        stored_vecs:  list of l2-normalised float32 numpy arrays (enrolled face embeddings).
                     pass none/empty to skip face matching (qr-only phase).
        threshold:   cosine-similarity threshold for face_match.
                     defaults to settings.face_match_threshold (or 0.38 if not set).
    """
    _ensure_models()
    logger.info("Processing biometric frame...")

    # resolve threshold — fall back to 0.65 (the standard sface cosine threshold)
    if threshold is None:
        threshold = getattr(settings, 'FACE_MATCH_THRESHOLD', 0.65)

    # decode and validate the frame — a bad/empty frame returns a structured result
    # instead of crashing with an opencv assertion error.
    try:
        bgr = _pil_to_bgr(image_bytes)
    except ValueError as e:
        logger.warning(f'Bad frame rejected: {e}')
        return {
            'qr_data':  None, 'qr_box': None,
            'face_box': None, 'face_match': False,
            'face_score': 0.0, 'original_dims': [0, 0],
            'liveness_metrics': None,
            'error': 'INVALID_FRAME',
        }

    h, w = bgr.shape[:2]

    result = {
        'qr_data':       None,
        'qr_box':        None,    # [x, y, w, h]
        'face_box':      None,    # [x, y, w, h]
        'face_match':    False,
        'face_score':    0.0,     # live cosine similarity (for ui feedback)
        'original_dims': [w, h],
        'liveness_metrics': None,
    }

    # 1. detect qr code
    data, bbox, _ = _qr_detector.detectAndDecode(bgr)
    logger.info(f"QR Detect: data={data} bbox_found={bbox is not None}")
    if data and bbox is not None and len(bbox) > 0:
        result['qr_data'] = data
        pts = bbox[0]
        x1, y1 = float(min(pts[:, 0])), float(min(pts[:, 1]))
        x2, y2 = float(max(pts[:, 0])), float(max(pts[:, 1]))
        result['qr_box'] = [x1, y1, x2 - x1, y2 - y1]

    # 2. detect face
    _detector.setInputSize((w, h))
    _, faces = _detector.detect(bgr)

    if faces is not None and len(faces) > 0:
        # take the most prominent (highest-confidence) face
        face = faces[0]
        confidence = float(face[-1])

        # slightly relaxed threshold (0.60) for real-world scanner environments
        if confidence >= 0.60:
            result['face_box'] = [float(face[0]), float(face[1]), float(face[2]), float(face[3])]
            result['liveness_metrics'] = extract_liveness_metrics(bgr, face)

            # if we have stored embeddings, run recognition
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
