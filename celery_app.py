import os
from celery.schedules import crontab
from app import create_app
from app.celery_worker import make_celery

flask_app = create_app(os.getenv('FLASK_CONFIG') or 'default')
celery = make_celery(flask_app)

# Configure Celery beat schedule
celery.conf.beat_schedule = {
    'schedule-price-checks-every-hour': {
        'task': 'app.tasks.schedule_price_checks',
        'schedule': crontab(minute=0, hour='*'),
    },
}