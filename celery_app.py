import os
from celery.schedules import crontab
from app import create_app
from app.celery_worker import make_celery

flask_app = create_app(os.getenv('FLASK_CONFIG') or 'default')
celery = make_celery(flask_app)

# Configure Celery beat schedule
celery.conf.update(flask_app.config['CELERY'])