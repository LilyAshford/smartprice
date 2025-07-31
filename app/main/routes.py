from flask import render_template, current_app
from flask_login import current_user
from app.main import bp


@bp.route('/')
@bp.route('/index')
def index():
    show_auth_links = not current_user.is_authenticated

    page_title = current_app.config.get('APP_NAME', 'SmartPrice') + " - " + "Your Smart Shopping Companion"

    return render_template(
        'main/index.html',
        title=page_title,
        show_auth_links=show_auth_links,
    )