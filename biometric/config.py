"""
biometric/config.py
all tuneable constants for the biometric pipeline, loaded from django settings
with sensible defaults. import this module instead of reading settings directly.
"""
from django.conf import settings


#  face recognition 
# cosine similarity threshold for a positive face match (0.0 – 1.0).
FACE_MATCH_THRESHOLD: float = getattr(settings, "FACE_MATCH_THRESHOLD", 0.45)

# maximum consecutive mismatch attempts before giving up and requesting
# manual verification.
FACE_MAX_ATTEMPTS: int = getattr(settings, "FACE_MAX_ATTEMPTS", 8)

# minimum euclidean distance between two consecutive frame embeddings required
# to pass passive liveness (rejects identical static photos).
LIVENESS_MIN_DISTANCE: float = getattr(settings, "LIVENESS_MIN_DISTANCE", 0.01)

# minimum yunet detection confidence to accept a face bounding box.
DETECTION_MIN_CONFIDENCE: float = 0.75

# laplacian variance below this value → frame is too blurry, skip it.
BLUR_VARIANCE_THRESHOLD: float = 60.0

#  video capture 
# os camera device index (0 = first webcam).
VIDEO_DEVICE_INDEX: int = getattr(settings, "VIDEO_DEVICE_INDEX", 0)

# target capture frame rate.
TARGET_FPS: int = getattr(settings, "TARGET_FPS", 20)

# max frames allowed in the async queue before backpressure kicks in
# (oldest frame dropped when full).
FRAME_QUEUE_MAX_DEPTH: int = 5

#  network / datafetcher 
# backoff delay schedule in seconds for datafetcher retries.
BACKOFF_DELAYS: list[float] = [0.5, 1.0, 2.0, 4.0]

# timeout in seconds for a single http request attempt.
REQUEST_TIMEOUT_S: float = 5.0

#  offline cache 
# how long a cached profile is considered fresh (seconds).
CACHE_TTL_SECONDS: int = getattr(settings, "CACHE_TTL_SECONDS", 1800)  # 30 min

# maximum number of student profiles kept in the in-process lru cache.
CACHE_MAX_ENTRIES: int = getattr(settings, "CACHE_MAX_ENTRIES", 100)

#  audit logging 
# structured log file path (relative to base_dir). rotated externally.
AUDIT_LOG_FILE: str = getattr(settings, "AUDIT_LOG_FILE", "logs/biometric_audit.jsonl")
