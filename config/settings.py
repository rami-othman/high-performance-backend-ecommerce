import os
import socket
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_int(name, default, min_value=None, max_value=None):
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default

    if min_value is not None:
        value = max(value, min_value)
    if max_value is not None:
        value = min(value, max_value)
    return value

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
DEBUG = os.getenv("DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")
SERVER_NAME = os.getenv("SERVER_NAME", socket.gethostname())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "products",
    "cart",
    "orders",
    "payments",
    "reports",
    "performance",
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
    "performance.middleware.PerformanceLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "ecommerce_db"),
        "USER": os.getenv("POSTGRES_USER", "ecommerce_user"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "ecommerce_password"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth": "30/min",
        "cart": "120/min",
        "checkout": "60/min",
        "reports": "20/min",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "High-Performance E-Commerce Backend Engine API",
    "DESCRIPTION": "Django monolith prepared for concurrency, queues, caching, and benchmarking experiments.",
    "VERSION": "0.1.0",
    "SERVE_AUTHENTICATION": [
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
}

CORS_ALLOW_ALL_ORIGINS = DEBUG

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = os.getenv("CELERY_TASK_ALWAYS_EAGER", "False").lower() == "true"

CHECKOUT_MAX_CONCURRENT_REQUESTS = int(os.getenv("CHECKOUT_MAX_CONCURRENT_REQUESTS", "5"))
CHECKOUT_CAPACITY_KEY = os.getenv("CHECKOUT_CAPACITY_KEY", "capacity:checkout:active")
CHECKOUT_CAPACITY_TTL_SECONDS = int(os.getenv("CHECKOUT_CAPACITY_TTL_SECONDS", "30"))
CHECKOUT_CAPACITY_TEST_DELAY_ENABLED = env_bool("CHECKOUT_CAPACITY_TEST_DELAY_ENABLED", DEBUG)
ORDER_ASYNC_TASK_TEST_DELAY_ENABLED = env_bool("ORDER_ASYNC_TASK_TEST_DELAY_ENABLED", DEBUG)
ORDER_ASYNC_TASK_TEST_DELAY_SECONDS = float(os.getenv("ORDER_ASYNC_TASK_TEST_DELAY_SECONDS", "1.0"))
DAILY_SALES_BATCH_CHUNK_SIZE = env_int("DAILY_SALES_BATCH_CHUNK_SIZE", 100, min_value=1, max_value=1000)
DAILY_SALES_BATCH_TEST_ORDER_COUNT = env_int("DAILY_SALES_BATCH_TEST_ORDER_COUNT", 250, min_value=1)
DAILY_SALES_BATCH_TEST_CHUNK_SIZE = env_int(
    "DAILY_SALES_BATCH_TEST_CHUNK_SIZE",
    50,
    min_value=1,
    max_value=1000,
)
LOAD_BALANCER_TEST_REQUESTS = env_int("LOAD_BALANCER_TEST_REQUESTS", 60, min_value=1)
LOAD_BALANCER_TEST_BASE_URL = os.getenv("LOAD_BALANCER_TEST_BASE_URL", "")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("CACHE_URL", REDIS_URL),
    }
}
