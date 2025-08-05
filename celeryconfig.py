from celery.schedules import crontab

beat_schedule = {
    'schedule-price-checks-every-hour': {
        'task': 'app.tasks.schedule_price_checks',
        'schedule': crontab(minute=0, hour='*'),
    },
}