from django.contrib import admin
from django.db import models
from django import forms
from .models import Room, Section, AttendanceSession, AttendanceRecord


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'capacity')
    search_fields = ('name',)


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('course_code', 'course_name', 'section_identifier')
    search_fields = ('course_code', 'course_name')
    formfield_overrides = {
        models.ManyToManyField: {'widget': forms.CheckboxSelectMultiple},
    }

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "teachers":
            kwargs["queryset"] = db_field.related_model.objects.filter(role='TEACHER')
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ('section', 'room', 'teacher', 'status', 'started_at', 'closed_at')
    list_filter = ('status',)
    search_fields = ('section__course_code', 'teacher__username')
    readonly_fields = ('started_at', 'closed_at')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('session', 'student', 'status', 'verification_method', 'marked_at', 'face_match_score')
    list_filter = ('status', 'verification_method')
    search_fields = ('student__full_name', 'student__student_id', 'session__section__course_code')
    readonly_fields = ('marked_at',)
