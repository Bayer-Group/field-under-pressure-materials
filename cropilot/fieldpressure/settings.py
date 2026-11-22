"""
Django settings for the Field Under Pressure platform.

All environment-specific values come from .env (see .env.example).
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- Core ---

# DEBUG is off unless .env turns it on (.env.example does, for local work): an app reachable from the network
# then never shows Django's debug pages (URL lists, settings, tracebacks).
DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY or (not DEBUG and SECRET_KEY == "dev-only-insecure-key-change-me"):
    import secrets
    import warnings

    if not DEBUG:
        warnings.warn("DJANGO_SECRET_KEY is not set: using a random key for this process (admin logins end on restart).")
    SECRET_KEY = SECRET_KEY if DEBUG and SECRET_KEY else secrets.token_urlsafe(50)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")


# --- Applications ---

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # ArrayField (Field.h3_cells)
    # Third party
    "rest_framework",
    "drf_spectacular",
    # Field Under Pressure components
    "core",  # platform: all models, data import, API (Szymek + Janek)
    "engine",  # decision engine (Bartek)
    "assistant",  # AI assistant (Ola)
    "frontend",  # web app + map (Szymek + Janek, map: Kuba)
    "scenarios",  # demo scenarios and `manage.py scenario` (no models)
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # serves the frontend's static files also with DEBUG off (runserver only serves them with DEBUG on)
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fieldpressure.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "fieldpressure.wsgi.application"


# --- Database (Postgres from docker-compose.yml) ---

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "fieldpressure"),
        "USER": os.environ.get("POSTGRES_USER", "fieldpressure"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "fieldpressure"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5433"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Auth ---

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization ---

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True


# --- Static files ---
# The TypeScript bundle is built into frontend/static/frontend/dist/ (see frontend/package.json).

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
WHITENOISE_USE_FINDERS = True  # straight from the apps' static/ folders: no collectstatic needed for the demo


# --- API (Django REST Framework + drf-spectacular) ---

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # No logins, no tokens, no CSRF (docs/interfaces.md -> General rules). /admin/ keeps Django's own login.
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    # JSON bodies only. Without CSRF, a form on any other site could POST urlencoded data here (e.g. "tak" to a
    # pending observation); a JSON body needs a CORS preflight, which this API never grants.
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # DRF's handler, plus 503 {"detail"} when the Clock row is missing (core.clock.ClockNotSetError).
    "EXCEPTION_HANDLER": "core.api_errors.exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Cropilot API",
    "DESCRIPTION": "Platform API used by the frontend, the map and the assistant.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Readable names for the generated TypeScript types (frontend/src/api/schema.d.ts).
    "ENUM_NAME_OVERRIDES": {
        "ThreatCategory": "core.models.Threat.Category",
        "RiskLevel": "core.serializers.LEVEL_CHOICES",
    },
}


# --- Project paths ---

# Organiser materials (git submodule): guide PDFs, risk spreadsheet, dataset docs.
MATERIALS_DIR = BASE_DIR / "field-under-pressure-materials"

# Downloaded hackathon datasets (kept outside git).
DATA_DIR = (BASE_DIR / os.environ.get("DATA_DIR", "../field-under-pressure-data")).resolve()

# Tests (`manage.py test`): only errors from the app's loggers, no progress bars, so the test output shows the tests.
if sys.argv[1:2] == ["test"]:
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TQDM_DISABLE", "1")
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "root": {"handlers": ["console"], "level": "ERROR"},
        # the API tests send bad requests on purpose
        "loggers": {"django.request": {"level": "CRITICAL", "propagate": False}},
    }
