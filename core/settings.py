import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "dev-secret-key"

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_q",

    # Local apps
    "users",
    "videos",
    "indexing",
    "configs",
    "embedding",

    # swagger-ui
    "drf_spectacular",
    "drf_spectacular_sidecar",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware", 
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "users.middleware.UserLanguageMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

# --- Database ---
if os.getenv("ENV") == "production":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "veeky"),
            "USER": os.getenv("POSTGRES_USER", "veeky"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "veeky"),
            "HOST": os.getenv("POSTGRES_HOST", "db"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "users.User"

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = []  # puoi aggiungere cartelle extra in sviluppo

# Dove Django raccoglie i file statici quando fai "collectstatic"
STATIC_ROOT = BASE_DIR / "staticfiles"

# File upload
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
# Temporary upload storage
TMP_UPLOAD_DIR = BASE_DIR / "tmp" / "uploads"
TMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FILE_UPLOAD_TEMP_DIR = str(TMP_UPLOAD_DIR)

LANGUAGE_CODE = "en-us"  # lingua di default
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("en", "English"),
    ("it", "Italiano"),
]

LOCALE_PATHS = [
    BASE_DIR / "locale",
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.JSONParser',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Veeky API",
    "DESCRIPTION": "API documentation for Veeky backend",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    'COMPONENT_SPLIT_REQUEST': True,
}

Q_CLUSTER = {
    "name": "veeky",
    "workers": 1,
    "recycle": 500,
    "timeout": 300,
    "retry": 600,
    "queue_limit": 50,
    "bulk": 10,
    "orm": "default",
    "sync": os.getenv("DJANGO_Q_SYNC", "False").lower() in {"1", "true", "yes"},
}


CORS_ALLOW_ALL_ORIGINS = True  # only for test
CSRF_TRUSTED_ORIGINS = ['http://localhost:8000'] 



try:
    from core.telemetry import initialize_tracer
    initialize_tracer()
except Exception as telemetry_error:  # pragma: no cover - telemetry init is optional in tests
    import logging
    logging.getLogger("core.telemetry").warning('Failed to initialize telemetry: %s', telemetry_error)

