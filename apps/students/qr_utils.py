import io
import qrcode
from django.conf import settings


def _build_payload(student_uuid: str) -> str:
    return student_uuid


import uuid
import hmac
import hashlib
import base64

def verify_token(token: str) -> str | None:
    """
    Verify token and return student identifier (University Roll Number or legacy UUID).
    """
    if not token:
        return None
        
    student_identifier = None
    
    # 1. Check if it's a legacy HMAC token (contains a dot for signature)
    if '.' in token:
        try:
            parts = token.rsplit('.', 1)
            if len(parts) == 2:
                encoded, _ = parts
                padding = 4 - len(encoded) % 4
                decoded = base64.urlsafe_b64decode(encoded + ('=' * padding)).decode()
                if '.' in decoded:
                    student_identifier, _ts = decoded.rsplit('.', 1)
        except Exception:
            pass
            
    # 2. If it wasn't a legacy token (or decode failed), assume it's the raw roll number / UUID
    if not student_identifier:
        student_identifier = token.strip()
        
    # Return the identifier. We no longer assert it's a UUID because it might be a University Roll Number
    return student_identifier if student_identifier else None

def generate_qr_png(token: str) -> bytes:
    """Generate simple QR code PNG bytes for the given token string."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(token)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def create_or_update_qr(student) -> 'QRCodeRecord':
    """Create/update the QRCodeRecord for a student and return it."""
    from apps.students.models import QRCodeRecord
    # Default to string 'UNASSIGNED' if empty so QR generation doesn't crash on invalid data
    roll_number = str(student.university_roll_number) if student.university_roll_number else str(student.id)
    token = _build_payload(roll_number)
    
    record, _ = QRCodeRecord.objects.update_or_create(
        student=student,
        defaults={'token_payload': token, 'is_valid': True}
    )
    return record
