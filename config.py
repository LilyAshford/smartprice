import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ['SECRET_KEY']
    SECURITY_PASSWORD_SALT = os.environ.get('SECURITY_PASSWORD_SALT')
    SERVER_NAME = os.environ.get('SERVER_NAME')
    PREFERRED_URL_SCHEME = os.environ.get('PREFERRED_URL_SCHEME') or 'http'
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() in ['true', '1', 't']
    SESSION_COOKIE_SAMESITE = 'Lax'
    TELEGRAM_SECRET_TOKEN = os.environ.get('TELEGRAM_SECRET_TOKEN')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_recycle': 280}
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', '1', 't']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    TELEGRAM_BOT_USERNAME = os.environ.get('TELEGRAM_BOT_USERNAME')
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    MAIL_SENDER = os.environ.get('MAIL_SENDER_NAME', 'SmartPrice <smartprice68@gmail.com>')
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
    LANGUAGES = ['en', 'ru', 'es', 'zh']
    BABEL_DEFAULT_LOCALE = 'en'
    BABEL_TRANSLATION_DIRECTORIES = 'locales'
    REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
    REDIS_PORT = os.environ.get('REDIS_PORT', '6379')
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')
    REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0"
    RATELIMIT_STORAGE_URI = REDIS_URL


    @staticmethod
    def init_app(app):
        pass

class DevelopmentConfig(Config):
    DEBUG = True
    PREFERRED_URL_SCHEME = 'https'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    REDIS_HOST = os.environ.get('REDIS_HOST', '127.0.0.1')
    REDIS_URL = f"redis://:{os.environ.get('REDIS_PASSWORD')}@{os.environ.get('REDIS_HOST', '127.0.0.1')}:{os.environ.get('REDIS_PORT', '6379')}/0"
    RATELIMIT_STORAGE_URI = REDIS_URL
    CELERY = {
        'broker_url': REDIS_URL,
        'result_backend': REDIS_URL,
        'timezone': 'UTC',
        'task_serializer': 'json',
        'accept_content': ['json'],
        'result_serializer': 'json',
        'beat_schedule': {
            'schedule-price-checks': {
                'task': 'app.tasks.schedule_price_checks',
                'schedule': 3600.0,
            }
        },
    }

class ProductionConfig(DevelopmentConfig):
    DEBUG = True
    DB_HOST = os.environ.get('DB_HOST', 'db')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              f"postgresql://lily:{os.environ.get('POSTGRES_PASSWORD')}@{DB_HOST}:5432/smartprice"
    REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
    REDIS_URL = f"redis://:{os.environ.get('REDIS_PASSWORD')}@{os.environ.get('REDIS_HOST', 'redis')}:{os.environ.get('REDIS_PORT', '6379')}/0"
    RATELIMIT_STORAGE_URI = REDIS_URL
    CELERY = {
        'broker_url': REDIS_URL,
        'result_backend': REDIS_URL,
        'timezone': 'UTC',
        'task_serializer': 'json',
        'accept_content': ['json'],
        'result_serializer': 'json',
        'beat_schedule': {
            'schedule-price-checks': {
                'task': 'app.tasks.schedule_price_checks',
                'schedule': 3600.0,
            },
            'cleanup-unconfirmed-users-daily': {
                'task': 'app.tasks.cleanup_unconfirmed_users',
                'schedule': 86400.0,
            }
        },
    }

class DockerConfig(Config):
    RATELIMIT_STORAGE_URI = os.environ.get('CELERY_BROKER_URL')
    REDIS_HOST = os.environ.get('REDIS_HOST', 'redis')
    REDIS_URL = f"redis://:{os.environ.get('REDIS_PASSWORD')}@{os.environ.get('REDIS_HOST', 'redis')}:{os.environ.get('REDIS_PORT', '6379')}/0"
    CELERY = {
        'broker_url': REDIS_URL,
        'result_backend': REDIS_URL,
        'timezone': 'UTC',
        'task_serializer': 'json',
        'accept_content': ['json'],
        'result_serializer': 'json',
        'beat_schedule': {
            'schedule-price-checks': {
                'task': 'app.tasks.schedule_price_checks',
                'schedule': 3600.0,
            }
        },
    }


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'docker': DockerConfig,
    'default': DevelopmentConfig
}