from pathlib import Path
import os
from datetime import timedelta

import dj_database_url
from dotenv import load_dotenv

# Charge les variables d'environnement depuis le fichier .env
load_dotenv()

# ================================================================
# 1. CHEMINS ET SÉCURITÉ
# ================================================================
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY',"django-insecure-ton-secret-key-ici")
DEBUG = os.environ.get('DJANGO_DEBUG', "True") == 'True'
ALLOWED_HOSTS = ['*']


# ================================================================
# 2. APPLICATIONS
# ================================================================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'cloudinary',
    'django.contrib.staticfiles',
    
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    
    # Your app
    'shops.apps.ShopsConfig',
]


# ================================================================
# 3. MIDDLEWARE
# ================================================================
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware', # Doit être tout en haut
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = '_config.urls'


# ================================================================
# 4. TEMPLATES
# ================================================================
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

WSGI_APPLICATION = '_config.wsgi.application'


# ================================================================
# 5. BASE DE DONNÉES
# ================================================================
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Mode Production / Postgres (Render, Railway, etc.)
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            ssl_require=True
        )
    }
else:
    # Mode Développement Local / SQLite (si DATABASE_URL est absent du .env)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# ================================================================
# 6. AUTHENTIFICATION & MOTS DE PASSE
# ================================================================
AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Douala'
USE_I18N = True
USE_TZ = True


# ================================================================
# 7. FICHIERS STATIQUES ET MÉDIAS
# ================================================================
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ================================================================
# 8. CORS (Sécurité Frontend React)
# ================================================================
CORS_ALLOW_ALL_ORIGINS = True 
# En production, remplace ceci par :
# CORS_ALLOWED_ORIGINS = ["https://mboa237.com", "https://www.mboa237.com"]


# ================================================================
# 9. DJANGO REST FRAMEWORK (DRF)
# ================================================================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "shops.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
}


# ================================================================
# 10. SIMPLE JWT (Tokens)
# ================================================================
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}


# ================================================================
# 11. CLOUDINARY (Stockage des images)
# ================================================================
import cloudinary
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.environ.get("CLOUDINARY_CLOUD_NAME"),
    'API_KEY': os.environ.get("CLOUDINARY_API_KEY"),
    'API_SECRET': os.environ.get("CLOUDINARY_API_SECRET"),
}
# Attention: Assure-toi d'avoir installé : pip install django-cloudinary-storage
STORAGES = {
    "default": {
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        # ⚠️ Si tu veux aussi héberger tes fichiers CSS/JS Django sur Cloudinary (en production) :
        # "BACKEND": "cloudinary_storage.storage.StaticHashedCloudinaryStorage",
    },
}
WHITENOISE_MAX_AGE = 31536000
# ================================================================
# 12. NOTCHPAY & ABONNEMENTS (Variables conservées intactes)
# ================================================================
# Tu avais demandé de ne pas toucher à ces variables
NOTCHPAY_PRIVATE_KEY = os.environ.get('NOTCHPAY_PRIVATE_KEY', "")
NOTCHPAY_PUBLIC_KEY = os.getenv("NOTCHPAY_PUBLIC_KEY", "")
NOTCHPAY_GRANT_KEY = os.getenv("NOTCHPAY_GRANT_KEY", "")
NOTCHPAY_WEBHOOK_HASH = os.getenv("NOTCHPAY_WEBHOOK_HASH", "")

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Prix des plans (en XAF)
SUBSCRIPTION_PRICES = {
    "monthly": 2500,
    "yearly": 25000,
}

# Montant forcé en mode test (minimum NotchPay XAF = 100)
TEST_MODE_AMOUNT = 100