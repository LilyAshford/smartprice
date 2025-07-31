import os
from . import create_app
from .extensions import celery

config_name = os.getenv('FLASK_CONFIG', 'default')
app = create_app(config_name)

app.app_context().push()