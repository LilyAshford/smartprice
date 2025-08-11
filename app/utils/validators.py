import re
import requests
from flask_babel import lazy_gettext as _l
from urllib.parse import urlparse
from app.models import User
from wtforms import ValidationError


class NotificationValidators:
    @staticmethod
    def validate_telegram_token(form, field):
        if 'telegram' in form.notification_methods.data:
            if not field.data:
                raise ValidationError(_l('Telegram token is required'))
            if not re.match(r'^\d{9,10}:[a-zA-Z0-9_-]{35}$', field.data):
                raise ValidationError(_l('Invalid Telegram bot token format'))


class ProductValidators:
    @staticmethod
    def validate_product_url(form, field):
        url = field.data
        if not url:
            raise ValidationError(_l('URL is required.'))

        if url.startswith('mock://'):
            return

        try:
            parsed = urlparse(url)
            if not (parsed.scheme and parsed.netloc):
                raise ValidationError(_l('Invalid URL: missing scheme (e.g., https://) or domain'))

            if parsed.scheme not in ('http', 'https'):
                raise ValidationError(_l('Only http:// and https:// URLs are supported'))

            supported_domains = [
                "amazon.com", "wildberries.ru", "walmart.com", "ebay.com"
            ]
            hostname = parsed.hostname.lower()
            if not any(supported in hostname for supported in supported_domains):
                supported_str = ", ".join(supported_domains)
                raise ValidationError(_l('We currently support: %(supported)s', supported=supported_str))

        except ValueError as e:
            raise ValidationError(_l('Invalid URL format: %(error)s', error=str(e)))



class UserValidators:
    @staticmethod
    def validate_email(self, email):
        user = User.query.filter_by(email=email.data.lower()).first()
        if user is not None:
            raise ValidationError(_l('Please use a different email address.'))

    @staticmethod
    def validate_username(self, username):
        if User.query.filter_by(username=username.data).first():
            raise ValidationError("Username already taken!")

    @staticmethod
    def validate_password_strength(form, field):
        password = field.data
        errors = []
        if not re.search(r'[A-Z]', password):
            errors.append(_l('Password must contain at least one uppercase letter.'))
        if not re.search(r'[a-z]', password):
            errors.append(_l('Password must contain at least one lowercase letter.'))
        if not re.search(r'\d', password):
            errors.append(_l('Password must contain at least one digit.'))

        if errors:
            raise ValidationError(" ".join(str(error) for error in errors))
