from flask import Flask, render_template, request, jsonify, current_app
from config import Config, config
from .admin_views import MyAdminIndexView, LogAdminView
from flask_login import current_user
from flask_migrate import Migrate
import flask_admin
from .extensions import db, mail, babel, init_limiter, init_auth
from flask_bootstrap import Bootstrap4
import os
from app.models import User, Product, Role, Feedback, PriceHistory, UserNotification, Log
from app.admin_views import UserAdminView, ProductAdminView, TestingView, AdminMessageView, ParserStatusView, SecuredModelView, FeedbackAdminView
import click
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
from .logging_config import SQLAlchemyLogHandler, NoDbLogDuplicatesFilter
from werkzeug.middleware.proxy_fix import ProxyFix
import posthog

from app.utils import bp as utils_bp
from app.api import bp as api_bp
from .telegram_bot.routes import bp as telegram_bot_bp
from .extensions import db, login_manager, babel, mail, limiter, auth
from .main.routes import bp as main_bp
from .auth.routes import bp as auth_bp
from .products.routes import bp as products_bp
from .profile.routes import bp as profile_bp

def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden(e):
        if request.accept_mimetypes.accept_json and \
                not request.accept_mimetypes.accept_html:
            response = jsonify({'error': 'forbidden'})
            response.status_code = 403
            return response
        return render_template('errors/403.html'), 403


def get_locale():
    from flask import session, request
    from flask_login import current_user

    lang_from_session = session.get('lang')
    if lang_from_session and lang_from_session in current_app.config['LANGUAGES']:
        return lang_from_session

    try:
        if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
            if current_user.language and current_user.language in current_app.config['LANGUAGES']:
                return current_user.language
    except RuntimeError:
        pass

    if request:
        return request.accept_languages.best_match(current_app.config['LANGUAGES'])

    return current_app.config.get('BABEL_DEFAULT_LOCALE', 'en')


def register_context_processors(app):
    @app.context_processor
    def inject_globals():
        try:
            request.url
            return dict(
                current_lang=get_locale(),
                languages=['en', 'ru', 'es', 'zh']
            )
        except RuntimeError:
            return dict(
                current_lang='en',
                languages=['en', 'ru', 'es', 'zh']
            )

    @app.context_processor
    def inject_unread_notifications_count():
        from app.models import UserNotification
        if not hasattr(current_user, 'is_authenticated') or not current_user.is_authenticated:
            return dict(unread_notifications_count=0)
        unread_notifications_count = 0

        if current_user.is_authenticated:
            try:
                unread_notifications_count = UserNotification.query.filter_by(user_id=current_user.id,
                                                                              is_read=False).count()
            except Exception as e:
                current_app.logger.warning(f"Failed to fetch unread notifications: {e}")


        return {
            'unread_notifications_count': unread_notifications_count,
        }


    @app.shell_context_processor
    def make_shell_context():
        return dict(db=db, User=User, Product=Product, Role=Role, Feedback=Feedback, PriceHistory=PriceHistory, UserNotification=UserNotification)

def create_app(config_name=None):
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )
    cfg = config.get(config_name) or config['default']
    app.config.from_object(cfg)
    cfg.init_app(app)
    posthog.api_key = app.config.get('POSTHOG_API_KEY')
    posthog.host = app.config.get('POSTHOG_HOST')
    from flask_admin import Admin

    admin_templates_path = os.path.join(os.path.dirname(flask_admin.__file__), 'templates')
    app.jinja_loader.searchpath.append(admin_templates_path)

    from app.celery_worker import make_celery
    celery = make_celery(app)
    app.extensions['celery'] = celery

    admin = Admin(
        app,
        name='SmartPrice Admin',
        template_mode='bootstrap4',
        index_view=MyAdminIndexView(name='Dashboard', endpoint='admin')
    )
    from .models import User, Product
    from .models import User, Product, AdminLog
    from .admin_views import AdminLogView
    admin.add_view(UserAdminView(User, db.session, name='Users', endpoint='users'))
    admin.add_view(ProductAdminView(Product, db.session, name='Products', endpoint='product'))
    admin.add_view(FeedbackAdminView(Feedback, db.session, name='Feedback', endpoint='feedback'))
    admin.add_view(TestingView(name='Testing', endpoint='testing'))
    admin.add_view(ParserStatusView(name='Parser Status', endpoint='parser_status'))
    admin.add_view(AdminMessageView(name='Send Message', endpoint='send_message'))
    admin.add_view(LogAdminView(Log, db.session, name='Logs'))
    admin.add_view(AdminLogView(AdminLog, db.session, name='Admin Actions', endpoint='admin_actions'))

    db.init_app(app)
    login_manager.init_app(app)
    Bootstrap4(app)
    babel.init_app(app, locale_selector=get_locale)
    mail.init_app(app)
    #init_limiter(app)
    migrate = Migrate(app, db)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(products_bp, url_prefix='/products')
    app.register_blueprint(profile_bp, url_prefix='/profile')
    app.register_blueprint(utils_bp)
    app.register_blueprint(api_bp, url_prefix='/api/v1')
    app.register_blueprint(telegram_bot_bp)

    from .logging_config import configure_logging, configure_admin_logging
    configure_logging(app)
    configure_admin_logging(app)

    @app.template_filter('datetime')
    def format_datetime(value, format='%Y-%m-%d %H:%M:%S'):
        if value == "now":
            return datetime.now().strftime(format)
        return value.strftime(format)

    from app.telegram_bot.cli import register_commands
    register_commands(app)

    from .utils.translations import translate
    app.cli.add_command(translate)

    register_context_processors(app)
    from . import cli
    cli.register_commands(app)
    register_error_handlers(app)

    from app import tasks

    return app


