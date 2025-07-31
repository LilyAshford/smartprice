import os
from app import create_app
from app.celery_worker import make_celery

flask_app = create_app(os.getenv('FLASK_CONFIG') or 'default')

celery = make_celery(flask_app)