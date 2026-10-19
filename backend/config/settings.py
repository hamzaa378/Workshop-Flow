import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / '.env')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'UNSAFE-LOCAL-ONLY-CHANGE-ME')
DEBUG = os.environ.get('DJANGO_DEBUG', 'false').lower() == 'true'
if not DEBUG and SECRET_KEY == 'UNSAFE-LOCAL-ONLY-CHANGE-ME':
    raise ValueError('Configure DJANGO_SECRET_KEY in .env before running outside local debug mode.')
ALLOWED_HOSTS = [x.strip() for x in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if x.strip()]
INSTALLED_APPS = ['django.contrib.contenttypes', 'core']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.middleware.common.CommonMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = []
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.mysql',
    'NAME': os.environ.get('MYSQL_DATABASE', 'gdg_workshops'),
    'USER': os.environ.get('MYSQL_USER', 'root'),
    'PASSWORD': os.environ.get('MYSQL_PASSWORD', ''),
    'HOST': os.environ.get('MYSQL_HOST', '127.0.0.1'),
    'PORT': os.environ.get('MYSQL_PORT', '3306'),
    'OPTIONS': {'charset': 'utf8mb4', 'init_command': "SET time_zone='+00:00'"},
    'CONN_MAX_AGE': 60,
}}
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SECURE_CONTENT_TYPE_NOSNIFF = True
