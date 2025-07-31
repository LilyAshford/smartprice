import logging
from logging.handlers import RotatingFileHandler
import os

# Bind to all interfaces on port 5000 to match Nginx upstream
bind = "0.0.0.0:5000"

workers = 4

# Timeout to match Nginx proxy timeouts (130s in nginx.conf)
timeout = 130

# Logging configuration
accesslog = "/app/logs/gunicorn_access.log"
errorlog = "/app/logs/gunicorn_error.log"
loglevel = "debug"

def post_fork(server, worker):
    log_dir = '/app/logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'smartprice.log'),
        maxBytes=1024000,
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] in %(module)s.%(funcName)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )
    file_handler.setFormatter(formatter)

    flask_logger = logging.getLogger('flask.app')
    flask_logger.addHandler(file_handler)

    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    worker.log.info("Log handler set up for worker %s", worker.pid)