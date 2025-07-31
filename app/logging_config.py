import logging
from app.models import AdminLog
from logging.handlers import RotatingFileHandler
from flask import request, has_request_context
from app.extensions import db
from app.models import Log
import os


class SQLAlchemyLogHandler(logging.Handler):
    def emit(self, record):
        ip_addr = request.remote_addr if has_request_context() else 'no-request'

        log_entry = Log(
            level=record.levelname,
            message=self.format(record),
            module=record.module,
            func_name=record.funcName,
            ip_address=ip_addr
        )
        try:
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"CRITICAL: Failed to log to database: {e}")


class NoDbLogDuplicatesFilter(logging.Filter):
    """
    This filter will be applied to the file handler.
    It prevents the log from being written to a file if the log has the special flag 'db_only'.
    """

    def filter(self, record):
        return not getattr(record, 'db_only', False)


class AdminLogDatabaseHandler(logging.Handler):
    def emit(self, record):
        admin_user = getattr(record, 'admin_user', None)
        if not admin_user:
            return

        details = getattr(record, 'details', None)

        log_entry = AdminLog(
            admin_id=admin_user.id,
            admin_username=admin_user.username,
            action=record.getMessage(),
            details=details
        )
        try:
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"CRITICAL: Failed to write ADMIN ACTION to database: {e}")


def configure_logging(app):
    from flask.logging import default_handler
    app.logger.removeHandler(default_handler)

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] in %(module)s.%(funcName)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )

    if not os.path.exists('logs'):
        os.makedirs('logs', exist_ok=True)

    file_handler = RotatingFileHandler(
        'logs/smartprice.log', maxBytes=1024000, backupCount=10, encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    file_handler.addFilter(NoDbLogDuplicatesFilter())

    db_handler = SQLAlchemyLogHandler()
    db_handler.setLevel(logging.INFO)
    db_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    app.logger.addHandler(file_handler)
    app.logger.addHandler(db_handler)
    app.logger.addHandler(console_handler)

    app.logger.setLevel(logging.INFO)

    for logger_name in ('werkzeug', 'gunicorn', 'celery'):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)


def configure_admin_logging(app):
    admin_logger = logging.getLogger('admin_actions')
    admin_logger.setLevel(logging.INFO)

    admin_logger.propagate = False

    admin_logger.addHandler(AdminLogDatabaseHandler())

    app.admin_logger = admin_logger