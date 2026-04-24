"""
biometric/exceptions.py
custom exceptions for the biometric pipeline.
"""


class BiometricError(Exception):
    """base class for all biometric pipeline errors."""


class ConsentRequired(BiometricError):
    """raised when biometric processing is attempted without user consent."""


class InvalidTransition(BiometricError):
    """raised when a state machine transition is illegal."""


class QRDecodeError(BiometricError):
    """raised when a qr payload cannot be decoded or validated."""


class FaceNotFoundError(BiometricError):
    """raised when no face is detected in a frame."""


class LivenessFailedError(BiometricError):
    """raised when passive liveness check fails (possible photo attack)."""


class NetworkExhaustedError(BiometricError):
    """raised when all retry attempts for a network call are exhausted."""


class CacheExpiredError(BiometricError):
    """raised when cached data has exceeded its ttl and no network is available."""


class StudentNotFoundError(BiometricError):
    """raised when a student identifier cannot be resolved."""
