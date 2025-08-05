import logging
from logging.handlers import RotatingFileHandler
import os

# Bind to all interfaces on port 5000 to match Nginx upstream
bind = "0.0.0.0:5000"

workers = 1
timeout = 120
loglevel = 'debug'

# Logging configuration
accesslog = "/app/logs/gunicorn_access.log"
errorlog = "/app/logs/gunicorn_error.log"
loglevel = "debug"

def post_fork(server, worker):
    log_dir = '/app/logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    for log_file in ['gunicorn_access.log', 'gunicorn_error.log', 'smartprice.log']:
        log_path = os.path.join(log_dir, log_file)
        if not os.path.exists(log_path):
            open(log_path, 'a').close()
            os.chmod(log_path, 0o666)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'smartprice.log'),
        maxBytes=1024000,
        backupCount=10,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] in %(module)s.%(funcName)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )
    file_handler.setFormatter(formatter)

    flask_logger = logging.getLogger('flask.app')
    flask_logger.addHandler(file_handler)

    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)

    worker.log.info("Log handler set up for worker %s", worker.pid)