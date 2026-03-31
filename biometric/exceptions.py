"""
biometric/exceptions.py
Custom exceptions for the biometric pipeline.
"""


class BiometricError(Exception):
    """Base class for all biometric pipeline errors."""


class ConsentRequired(BiometricError):
    """Raised when biometric processing is attempted without user consent."""


class InvalidTransition(BiometricError):
    """Raised when a state machine transition is illegal."""


class QRDecodeError(BiometricError):
    """Raised when a QR payload cannot be decoded or validated."""


class FaceNotFoundError(BiometricError):
    """Raised when no face is detected in a frame."""


class LivenessFailedError(BiometricError):
    """Raised when passive liveness check fails (possible photo attack)."""


class NetworkExhaustedError(BiometricError):
    """Raised when all retry attempts for a network call are exhausted."""


class CacheExpiredError(BiometricError):
    """Raised when cached data has exceeded its TTL and no network is available."""


class StudentNotFoundError(BiometricError):
    """Raised when a student identifier cannot be resolved."""
