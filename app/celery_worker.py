from celery import Celery
import logging

def make_celery(app):
    logging.info(f"Celery config: {app.config.get('CELERY', {})}")

    celery = Celery(
        app.import_name,
        broker=app.config['CELERY']['broker_url'],
        backend=app.config['CELERY']['result_backend'],
        include=['app.tasks']
    )
    celery.conf.update(app.config['CELERY'])

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    logging.info("Celery initialized successfully")
    return celery

