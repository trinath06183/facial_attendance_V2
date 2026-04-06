from django.contrib import admin
from django.db import models
from django import forms
from .models import Room, AcademicClass, AcademicYear, Subject, AttendanceSession, AttendanceRecord

@admin.register(AcademicClass)
class AcademicClassAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('academic_class', 'year_name')
    list_filter = ('academic_class',)
    search_fields = ('year_name',)

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'academic_year')
    list_filter = ('academic_year__academic_class', 'academic_year')
    search_fields = ('code', 'name')
    formfield_overrides = {
        models.ManyToManyField: {'widget': forms.CheckboxSelectMultiple},
    }

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "teachers":
            kwargs["queryset"] = db_field.related_model.objects.filter(role='TEACHER')
        return super().formfield_for_manytomany(db_field, request, **kwargs)

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'capacity')
    search_fields = ('name',)


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ('subject', 'room', 'teacher', 'status', 'started_at', 'closed_at')
    list_filter = ('status',)
    search_fields = ('subject__code', 'teacher__username')
    readonly_fields = ('started_at', 'closed_at')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('session', 'student', 'status', 'verification_method', 'marked_at', 'face_match_score')
    list_filter = ('status', 'verification_method')
    search_fields = ('student__full_name', 'student__student_id', 'session__subject__code')
    readonly_fields = ('marked_at',)
