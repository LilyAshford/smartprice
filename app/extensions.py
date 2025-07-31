from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_babel import Babel
from flask_mail import Mail
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_httpauth import HTTPBasicAuth
from celery import Celery
import os

auth = HTTPBasicAuth()
babel = Babel()
mail = Mail()
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'
celery = Celery(__name__, include=['app.tasks'])

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

def init_limiter(app):
    redis_url = f"redis://:{app.config.get('REDIS_PASSWORD', 'Lillian2030')}@{app.config.get('REDIS_HOST', 'redis')}:{app.config.get('REDIS_PORT', '6379')}/0"
    limiter.init_app(app)
    limiter.storage_uri = redis_url

def init_auth(app):
    login_manager.init_app(app)
    from app.auth.routes import bp
    from .models import load_user
    app.register_blueprint(bp)