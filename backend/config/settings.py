from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from corsheaders.defaults import default_headers, default_methods


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me-before-sharing")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "*")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "apps.accounts",
    "apps.grading",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {}
}


def database_config_from_url(database_url: str) -> dict:
    parsed = urlparse(database_url)
    if parsed.scheme == "sqlite":
        sqlite_path = parsed.path or "/db.sqlite3"
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": sqlite_path,
        }
    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": parsed.port or "",
            "CONN_MAX_AGE": 600,
        }
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")


DATABASES["default"] = database_config_from_url(
    os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'app.db'}")
)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", str(BASE_DIR / "storage"))).resolve()
UPLOADS_ROOT = STORAGE_ROOT / "uploads"
ARTIFACTS_ROOT = STORAGE_ROOT / "artifacts"
for path in (STORAGE_ROOT, UPLOADS_ROOT, ARTIFACTS_ROOT, BASE_DIR / "data"):
    path.mkdir(parents=True, exist_ok=True)

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_OPENAI_ALLOWED_DEPLOYMENT = "gpt-5.4-mini"
AZURE_OPENAI_INPUT_USD_PER_1M_TOKENS = (
    float(os.getenv("AZURE_OPENAI_INPUT_USD_PER_1M_TOKENS", ""))
    if os.getenv("AZURE_OPENAI_INPUT_USD_PER_1M_TOKENS")
    else None
)
AZURE_OPENAI_OUTPUT_USD_PER_1M_TOKENS = (
    float(os.getenv("AZURE_OPENAI_OUTPUT_USD_PER_1M_TOKENS", ""))
    if os.getenv("AZURE_OPENAI_OUTPUT_USD_PER_1M_TOKENS")
    else None
)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-before-sharing")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24)))

DEFAULT_QUESTION_MAX_MARKS = float(os.getenv("DEFAULT_QUESTION_MAX_MARKS", "5.0"))
HARD_TIMEOUT_SECONDS = int(os.getenv("HARD_TIMEOUT_SECONDS", "120"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "110"))
PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "200"))
PDF_MAX_PAGE_DIMENSION = int(os.getenv("PDF_MAX_PAGE_DIMENSION", "1800"))
PDF_MAX_ZOOMED_DIMENSION = int(os.getenv("PDF_MAX_ZOOMED_DIMENSION", "1800"))
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
INSPECTION_BATCH_SIZE = int(os.getenv("INSPECTION_BATCH_SIZE", "5"))
MAX_IMAGES_PER_REQUEST = int(os.getenv("MAX_IMAGES_PER_REQUEST", "10"))
ALLOW_MOCK_GRADING = env_bool("ALLOW_MOCK_GRADING", False)
GRADING_INLINE_MODE = env_bool("GRADING_INLINE_MODE", False)

APP_NAME = "Agentic AI Exam Grader"
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", False)
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)
CORS_ALLOW_HEADERS = list(default_headers)
CORS_ALLOW_METHODS = list(default_methods)
CORS_URLS_REGEX = r"^/api(?:/.*)?$"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "common.auth.BearerTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.api.api_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Zanista Exam Grader API",
    "DESCRIPTION": "Authenticated API for exam grading, grading history, and PDF export.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
    "SECURITY": [{"BearerAuth": []}],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("LOG_LEVEL", "INFO"),
    },
}
