"""
biometric/config.py
All tuneable constants for the biometric pipeline, loaded from Django settings
with sensible defaults. Import this module instead of reading settings directly.
"""
from django.conf import settings


# ── Face Recognition ───────────────────────────────────────────────────────
# Cosine similarity threshold for a positive face match (0.0 – 1.0).
FACE_MATCH_THRESHOLD: float = getattr(settings, "FACE_MATCH_THRESHOLD", 0.45)

# Maximum consecutive mismatch attempts before giving up and requesting
# manual verification.
FACE_MAX_ATTEMPTS: int = getattr(settings, "FACE_MAX_ATTEMPTS", 8)

# Minimum Euclidean distance between two consecutive frame embeddings required
# to pass passive liveness (rejects identical static photos).
LIVENESS_MIN_DISTANCE: float = getattr(settings, "LIVENESS_MIN_DISTANCE", 0.01)

# Minimum YuNet detection confidence to accept a face bounding box.
DETECTION_MIN_CONFIDENCE: float = 0.75

# Laplacian variance below this value → frame is too blurry, skip it.
BLUR_VARIANCE_THRESHOLD: float = 60.0

# ── Video Capture ──────────────────────────────────────────────────────────
# OS camera device index (0 = first webcam).
VIDEO_DEVICE_INDEX: int = getattr(settings, "VIDEO_DEVICE_INDEX", 0)

# Target capture frame rate.
TARGET_FPS: int = getattr(settings, "TARGET_FPS", 20)

# Max frames allowed in the async queue before backpressure kicks in
# (oldest frame dropped when full).
FRAME_QUEUE_MAX_DEPTH: int = 5

# ── Network / DataFetcher ──────────────────────────────────────────────────
# Backoff delay schedule in seconds for DataFetcher retries.
BACKOFF_DELAYS: list[float] = [0.5, 1.0, 2.0, 4.0]

# Timeout in seconds for a single HTTP request attempt.
REQUEST_TIMEOUT_S: float = 5.0

# ── Offline Cache ──────────────────────────────────────────────────────────
# How long a cached profile is considered fresh (seconds).
CACHE_TTL_SECONDS: int = getattr(settings, "CACHE_TTL_SECONDS", 1800)  # 30 min

# Maximum number of student profiles kept in the in-process LRU cache.
CACHE_MAX_ENTRIES: int = getattr(settings, "CACHE_MAX_ENTRIES", 100)

# ── Audit Logging ──────────────────────────────────────────────────────────
# Structured log file path (relative to BASE_DIR). Rotated externally.
AUDIT_LOG_FILE: str = getattr(settings, "AUDIT_LOG_FILE", "logs/biometric_audit.jsonl")
