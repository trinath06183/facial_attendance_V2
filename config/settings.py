from decouple import config as default_config, Config, RepositoryEnv
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Robustly load .env file from the project root (Fixes PythonAnywhere WSGI path issues)
env_path = BASE_DIR / '.env'
if env_path.exists():
    config = Config(RepositoryEnv(str(env_path)))
else:
    config = default_config

SECRET_KEY = config('SECRET_KEY', default='dev-secret-key-change-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)
# ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='bn06183.pythonanywhere.com,localhost,127.0.0.1').split(',')
ALLOWED_HOSTS = ['*']
CSRF_TRUSTED_ORIGINS = [
    'https://*.ngrok-free.dev',
    'https://*.ngrok-free.app',
    'https://*.ngrok.app',
    'https://*.ngrok.io'
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Project apps
    'apps.accounts',
    'apps.students',
    'apps.attendance',
    'apps.audit',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'apps.attendance.middleware.AttendanceAutoCloseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.accounts.middleware.InactivityLogoutMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.audit.middleware.AuditMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_USER_MODEL = 'accounts.CustomUser'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Face recognition settings
# SFace cosine-similarity threshold. Official OpenCV default is 0.363.
# 0.38 gives a small safety margin while remaining practical for webcam conditions.
FACE_MATCH_THRESHOLD = config('FACE_MATCH_THRESHOLD', default=0.65, cast=float)
HMAC_SIGNING_KEY = config('HMAC_SIGNING_KEY', default='dev-hmac-key-change-in-production')
ML_MODELS_DIR = BASE_DIR / 'ml_models'

# ── Audit / Logging Settings ─────────────────────────────────────────────────
# Entries older than this many hours are automatically purged.
AUDIT_LOG_RETENTION_HOURS = config('AUDIT_LOG_RETENTION_HOURS', default=48, cast=int)
# Re-use HMAC_SIGNING_KEY for audit checksum — no extra secret needed.

# Message storage
# Safety net: even persistent sessions max out at 3 hours of inactivity.
SESSION_COOKIE_AGE = 10800   # 3 hours in seconds
# ── Session / Browser-close settings ────────────────────────────────────────
# Session cookie is a "browser-session" cookie (no explicit expiry date).
# The browser discards it when all browser windows are closed, which
# automatically invalidates the Django session → auto-logout for all roles.
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
# Safety net: even persistent sessions max out at 8 hours of inactivity.
SESSION_COOKIE_AGE = 86400   # 24 hours in seconds
INACTIVITY_TIMEOUT_SECONDS = 3600

# ── Email Settings for OTP ──────────────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
# Must configure these in .env file!
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL')
