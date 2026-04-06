from django.contrib import admin
from django.db import models
from django import forms
from .models import Student, Embedding, QRCodeRecord


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'full_name', 'enrollment_status', 'consent_given')
    list_filter = ('enrollment_status', 'consent_given', 'enrolled_subjects')
    search_fields = ('student_id', 'full_name', 'email')
    readonly_fields = ('created_at', 'updated_at', 'consent_timestamp', 'consent_ip')
    formfield_overrides = {
        models.ManyToManyField: {'widget': forms.CheckboxSelectMultiple},
    }


@admin.register(Embedding)
class EmbeddingAdmin(admin.ModelAdmin):
    list_display = ('student', 'model_name', 'is_active', 'quality_score', 'capture_environment', 'created_at')
    list_filter = ('model_name', 'is_active', 'capture_environment')
    search_fields = ('student__full_name', 'student__student_id')
    readonly_fields = ('embedding_vector', 'created_at')


@admin.register(QRCodeRecord)
class QRCodeRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'is_valid', 'issued_at', 'last_regenerated_at', 'signing_key_version')
    list_filter = ('is_valid', 'signing_key_version')
    search_fields = ('student__full_name', 'student__student_id')
