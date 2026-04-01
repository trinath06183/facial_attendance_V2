from .models import AuditLog

def audit(request, action, target_resource, resource_id='', metadata=None):
    if metadata is None:
        metadata = {}
    elif isinstance(metadata, str):
        metadata = {'notes': metadata}
    
    actor = request.user if hasattr(request, 'user') and request.user.is_authenticated else None
    ip = request.META.get('REMOTE_ADDR')
    # Use headers provided by the client (or reverse proxy) as proxy device fingerprint
    ua = request.META.get('HTTP_USER_AGENT', '')
    
    AuditLog.objects.create(
        actor=actor,
        action=action,
        target_resource=target_resource,
        resource_id=resource_id,
        ip_address=ip,
        device_fingerprint=ua[:255],
        metadata=metadata
    )
