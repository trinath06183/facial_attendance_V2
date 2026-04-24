"""apps/audit/admin.py — django admin for auditlog."""

from django.contrib import admin
from django.utils.html import format_html
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        'timestamp_ist', 'event_type', 'auth_method',
        'actor_username', 'actor_role', 'ip_address',
        'browser', 'os', 'checksum_valid',
    )
    list_filter = ('event_type', 'auth_method', 'actor_role')
    search_fields = ('actor_username', 'actor_user_id', 'ip_address', 'user_agent')
    readonly_fields = [f.name for f in AuditLog._meta.get_fields() if hasattr(f, 'name')]
    ordering = ('-timestamp',)
    date_hierarchy = 'timestamp'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # only superusers can delete log entries
        return request.user.is_superuser

    def timestamp_ist(self, obj):
        from django.utils import timezone
        ist = timezone.localtime(obj.timestamp)
        return ist.strftime('%d %b %Y %H:%M:%S IST')
    timestamp_ist.short_description = 'Timestamp (IST)'
    timestamp_ist.admin_order_field = 'timestamp'

    def checksum_valid(self, obj):
        ok = obj.verify_checksum()
        icon = '✅' if ok else '❌'
        label = 'Valid' if ok else 'TAMPERED'
        color = 'green' if ok else 'red'
        return format_html('<span style="color:{};">{} {}</span>', color, icon, label)
    checksum_valid.short_description = 'Integrity'
