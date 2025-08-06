import os

# Gunicorn configuration
bind = "0.0.0.0:5000"
workers = 1
timeout = 120
loglevel = "debug"

# Logging configuration for Gunicorn
accesslog = "/app/logs/gunicorn_access.log"
errorlog = "/app/logs/gunicorn_error.log"

def post_fork(server, worker):
    # Ensure log directory exists
    log_dir = '/app/logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Create log files with appropriate permissions if they don't exist
    for log_file in ['gunicorn_access.log', 'gunicorn_error.log', 'smartprice.log']:
        log_path = os.path.join(log_dir, log_file)
        if not os.path.exists(log_path):
            open(log_path, 'a').close()
            os.chmod(log_path, 0o666)

    # Log worker fork event
    worker.log.info("Worker %s forked.", worker.pid)