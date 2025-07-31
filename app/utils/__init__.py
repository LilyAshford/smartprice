from flask import session, redirect, request, url_for, Blueprint, current_app
from flask_babel import refresh

bp = Blueprint('utils', __name__)

@bp.route('/set_language/<lang>')
def set_language(lang):
    available_languages = current_app.config.get('LANGUAGES', ['en'])
    if lang in available_languages:
        session['lang'] = lang
        refresh()
    return redirect(request.referrer or url_for('main.index'))
