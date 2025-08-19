from app.extensions import db, login_manager
from datetime import datetime
from flask import current_app
from flask_login import UserMixin, AnonymousUserMixin
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature, BadSignature, BadPayload
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import orm, Enum as SaEnum
from flask_babel import _
import enum
import uuid


class Product(db.Model):
    __tablename__ = 'products'
    __table_args__ = (
        db.Index('ix_product_user_id', 'user_id'),
        db.Index('ix_product_last_checked', 'last_checked'),
        db.UniqueConstraint('user_id', 'url', name='uq_user_product_url'),
    )

    id = db.Column(db.Integer, primary_key=True)
    comparison_group_id = db.Column(db.String(36), default=lambda: str(uuid.uuid4()), nullable=True, index=True)
    product_identifier = db.Column(db.String(255), index=True, nullable=True)
    url = db.Column(db.String(500), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    target_price = db.Column(db.Numeric(10, 2), nullable=False)
    price_drop_alert_threshold = db.Column(db.Numeric(10, 2), nullable=True)
    price_increase_alert_threshold = db.Column(db.Numeric(10, 2), nullable=True)
    price_history = db.relationship('PriceHistory', back_populates='product', lazy='dynamic', cascade="all, delete-orphan")
    notification_methods = db.Column(db.ARRAY(db.String(20)), nullable=False)
    target_price_notified = db.Column(db.Boolean, default=False)
    check_frequency = db.Column(db.Integer, nullable=False)
    current_price = db.Column(db.Numeric(10, 2))
    last_checked = db.Column(db.DateTime)
    is_comparison_only = db.Column(db.Boolean, default=False, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', back_populates='products')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def generate_identifier(self):
        import re
        import hashlib
        if self.name:
            normalized_name = re.sub(r'[\W_]+', '', self.name.lower())
            self.product_identifier = hashlib.md5(normalized_name.encode()).hexdigest()[:20]

    def get_marketplace_name(self):
        from urllib.parse import urlparse
        domain = urlparse(self.url).netloc.lower()

        marketplace_map = {
            'amazon.com': 'Amazon',
            'amazon.co.uk': 'Amazon UK',
            'ebay.com': 'eBay',
            'aliexpress.com': 'AliExpress',
            'wildberries.ru': 'Wildberries',
            'ozon.ru': 'Ozon',
        }

        for key, value in marketplace_map.items():
            if key in domain:
                return value
        return domain.replace('www.', '').capitalize()

    def get_favicon_url(self):
        from urllib.parse import urlparse
        domain = urlparse(self.url).netloc
        return f"https://www.google.com/s2/favicons?domain={domain}"

    def __repr__(self):
        return f'<Product {self.name}>'

class Permission:
    ADMIN = 16
    CREATE_PRODUCT = 32
    EDIT_OWN_PRODUCT = 64
    DELETE_OWN_PRODUCT = 128
    VIEW_ALL_PRODUCTS = 256
    MANAGE_USERS = 512
    MANAGE_SETTINGS = 1024 # For administrators to manage global application settings


class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    default = db.Column(db.Boolean, default=False, index=True)
    permissions = db.Column(db.Integer)
    users = db.relationship('User', back_populates='role', lazy='dynamic')

    def __init__(self, **kwargs):
        super(Role, self).__init__(**kwargs)
        if self.permissions is None:
            self.permissions = 0

    @staticmethod
    def insert_roles():
        roles = {
            'User': [
                Permission.CREATE_PRODUCT, Permission.EDIT_OWN_PRODUCT,
                Permission.DELETE_OWN_PRODUCT
            ],
            'Administrator': [
                Permission.CREATE_PRODUCT, Permission.EDIT_OWN_PRODUCT,
                Permission.DELETE_OWN_PRODUCT, Permission.VIEW_ALL_PRODUCTS,
                Permission.MANAGE_USERS, Permission.MANAGE_SETTINGS, Permission.ADMIN
            ],
        }
        default_role = 'User'
        for r in roles:
            role = Role.query.filter_by(name=r).first()
            if role is None:
                role = Role(name=r)
            role.reset_permissions()
            for perm in roles[r]:
                role.add_permission(perm)
            role.default = (role.name == default_role)
            db.session.add(role)
        db.session.commit()

    def add_permission(self, perm):
        if not self.has_permission(perm):
            self.permissions += perm

    def remove_permission(self, perm):
        if self.has_permission(perm):
            self.permissions -= perm

    def reset_permissions(self):
        self.permissions = 0

    def has_permission(self, perm):
        return self.permissions & perm == perm

    def __repr__(self):
        return '<Role %r>' % self.name


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    __table_args__ = (
        db.Index('ix_user_email', 'email', unique=True),
        db.Index('ix_user_verified', 'confirmed'),
    )

    id = db.Column(db.Integer, primary_key = True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique = True, nullable = False)
    password_hash = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    role = db.relationship('Role', back_populates='users')
    language = db.Column(db.String(10), default = 'en')
    confirmed = db.Column(db.Boolean, default = False)
    last_password_change = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default = datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    products = db.relationship('Product', back_populates='user', lazy='dynamic', cascade="all, delete-orphan")
    notifications = db.relationship('UserNotification', back_populates='user', lazy='dynamic',cascade="all, delete-orphan")
    feedback = db.relationship('Feedback', back_populates='user', lazy='dynamic', cascade="all, delete-orphan")
    enable_price_drop_notifications = db.Column(db.Boolean, default=True, nullable=False)
    enable_target_price_reached_notifications = db.Column(db.Boolean, default=True, nullable=False)
    enable_email_notifications = db.Column(db.Boolean, nullable=False, default=True)
    telegram_chat_id = db.Column(db.String(50), unique=True, nullable=True)
    telegram_linking_token = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    telegram_state = db.Column(db.String(50), nullable=True)
    temp_data = db.Column(db.JSON, nullable=True)

    def __repr__(self):
        return f'<User {self.email}>'

    def ping(self):
        self.last_seen = datetime.utcnow()
        db.session.add(self)

    def _get_token_serializer(self):
        return URLSafeTimedSerializer(
            current_app.config['SECRET_KEY'],
            salt=current_app.config['SECURITY_PASSWORD_SALT']
        )
    def generate_confirmation_token(self):
        s = self._get_token_serializer()
        return s.dumps({'confirm': self.id})

    @staticmethod
    def verify_confirmation_token_and_get_user(token, max_age_seconds=None):
        if max_age_seconds is None:
            max_age_seconds = current_app.config.get('CONFIRMATION_TOKEN_EXPIRY_HOURS', 1) * 3600

        s = URLSafeTimedSerializer(
            current_app.config['SECRET_KEY'],
            salt=current_app.config['SECURITY_PASSWORD_SALT']
        )
        try:
            data = s.loads(token.encode('utf-8'), max_age=max_age_seconds)
        except (SignatureExpired, BadTimeSignature, BadSignature, BadPayload, Exception):
            current_app.logger.warning(f"Attempt to verify invalid or expired confirmation token: {token[:20]}...")
            return None

        user_id = data.get('confirm')
        if not user_id:
            current_app.logger.warning(f"User ID not found in confirmation token payload: {token[:20]}...")
            return None

        return User.query.get(user_id)

    def confirm(self, token, max_age_seconds=None):
        if max_age_seconds is None:
            max_age_seconds = current_app.config.get('CONFIRMATION_TOKEN_EXPIRY_HOURS', 1) * 3600

        s = self._get_token_serializer()
        try:
            data = s.loads(token.encode('utf-8'), max_age=max_age_seconds)
        except (SignatureExpired, BadTimeSignature, BadSignature, BadPayload) as e:
            current_app.logger.warning(
                f"Confirmation token error for user {self.id}, token {token[:20]}...: {type(e).__name__}")
            return False
        except Exception as e:
            current_app.logger.error(
                f"Unexpected error during token deserialization for user {self.id}, token {token[:20]}...: {str(e)}",
                exc_info=True)
            return False

        if data.get('confirm') != self.id:
            current_app.logger.warning(f"Token ID mismatch for user {self.id} in confirmation token.")
            return False

        if self.confirmed:
            return True

        self.confirmed = True
        self.is_active = True
        try:
            db.session.add(self)
            db.session.commit()

            from flask_login import logout_user
            logout_user()

            from flask_login import login_user
            login_user(self)
        except Exception as e:
            current_app.logger.error(f"Database error after confirming user {self.id}: {str(e)}", exc_info=True)
            db.session.rollback()
            return False
        return True

    def generate_reset_token(self):
        s = self._get_token_serializer()
        return s.dumps({'reset': self.id})

    @staticmethod
    def reset_password(token, new_password, max_age=3600): # max_age for loading
        # Static method needs to create its own serializer instance
        s = URLSafeTimedSerializer(
            current_app.config['SECRET_KEY'],
            salt=current_app.config['SECURITY_PASSWORD_SALT']
        )
        try:
            data = s.loads(token.encode('utf-8'), max_age=max_age)
        except SignatureExpired:
            current_app.logger.warning(f"Password reset token expired: {token[:15]}...")
            return None
        except BadTimeSignature:
            current_app.logger.warning(f"Password reset token has bad time signature: {token[:15]}...")
            return None
        except BadSignature:
            current_app.logger.warning(f"Password reset token has bad signature: {token[:15]}...")
            return None
        except BadPayload:
            current_app.logger.warning(f"Password reset token payload is corrupted: {token[:15]}...")
            return None
        except Exception as e:
            current_app.logger.error(
                f"Unexpected error during password reset token deserialization {token[:15]}...: {str(e)}",
                exc_info=True)
            return None

        user_id = data.get('reset')
        if not user_id:
            current_app.logger.warning(f"User ID not found in password reset token payload: {token[:15]}...")
            return None

        user = User.query.get(user_id)
        if user is None:
            current_app.logger.warning(f"User with ID {user_id} not found for password reset.")
            return None

        user.password = new_password
        try:
            db.session.add(user)
        except Exception as e:
            current_app.logger.error(f"Database error while resetting password for user {user.id}: {str(e)}",
                                     exc_info=True)
            db.session.rollback()
            return None
        return user

    @staticmethod
    def verify_password_reset_token(token, max_age=3600):
        s = URLSafeTimedSerializer(
            current_app.config['SECRET_KEY'],
            salt=current_app.config['SECURITY_PASSWORD_SALT']
        )
        try:
            data = s.loads(token.encode('utf-8'), max_age=max_age)
        except (SignatureExpired, BadTimeSignature, BadSignature, BadPayload):
            return None
        return User.query.get(data.get('reset'))

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_email_change_token(self, new_email):
        s = self._get_token_serializer()
        return s.dumps({'change_email': self.id, 'new_email': new_email})

    def change_email(self, token, max_age=3600):  # max_age for loading
        s = self._get_token_serializer()
        try:
            data = s.loads(token.encode('utf-8'), max_age=max_age)
        except Exception:
            return False
        if data.get('change_email') != self.id:
            return False
        new_email = data.get('new_email')
        if new_email is None or User.query.filter_by(email=new_email).first() is not None:
            return False
        self.email = new_email
        db.session.add(self)
        return True

    def can(self, perm):
        return self.role is not None and self.role.has_permission(perm)


    @property
    def is_administrator(self):
        return self.can(Permission.ADMIN)

    def generate_auth_token(self, expiration):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'],
            salt=current_app.config['SECURITY_PASSWORD_SALT'])
        return s.dumps({'id': self.id})

    @staticmethod
    def verify_auth_token(token):
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token)
        except SignatureExpired:
            return None  # valid token, but expired
        except BadSignature:
            return None  # invalid token
        except Exception: # Catch other potential errors from loads
            return None
        user = User.query.get(data['id'])
        return user

class AnonymousUser(AnonymousUserMixin):
    def can(self, permissions):
        return False

    @property
    def is_administrator(self):
        return False

login_manager.anonymous_user = AnonymousUser

class FeedbackCategory(enum.Enum):
    BUG = "bug_report"
    SUGGESTION = "suggestion"
    PRAISE = "praise"
    OTHER = "other"

    def __str__(self):
        if self == FeedbackCategory.BUG:
            return _("Bug Report")
        elif self == FeedbackCategory.SUGGESTION:
            return _("Suggestion")
        elif self == FeedbackCategory.PRAISE:
            return _("Praise")
        return _("Other")

class Feedback(db.Model):
    __tablename__ = 'feedback'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(SaEnum(FeedbackCategory), nullable=False, default=FeedbackCategory.OTHER)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    page_url = db.Column(db.String(500), nullable=True)

    user = db.relationship('User', back_populates='feedback')

    def __repr__(self):
        return f'<Feedback {self.id} by User {self.user_id} - {self.category.value}>'


class PriceHistory(db.Model):
    __tablename__ = 'price_history'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    # currency = db.Column(db.String(3))
    product = db.relationship('Product', back_populates='price_history')



class UserNotification(db.Model):
    __tablename__ = 'user_notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), nullable=True)
    type = db.Column(db.String(50), index=True) # 'price_drop', 'target_reached', 'price_increase', 'savings_report', 'system_message'
    message = db.Column(db.Text, nullable=True)
    short_message = db.Column(db.String(255))
    data = db.Column(db.JSON) # {'old_price': 100, 'new_price': 80, 'currency': '$'}
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', back_populates='notifications')
    product = db.relationship('Product')

    def __repr__(self):
        return f'<UserNotification {self.id} for User {self.user_id} - Type: {self.type}>'

    def get_style_info(self):
        if self.type == 'target_reached':
            return {'icon': 'fas fa-bullseye', 'color_class': 'notification-success', 'action_text': _('View Product')}
        elif self.type == 'price_drop':
            return {'icon': 'fas fa-arrow-down', 'color_class': 'notification-info', 'action_text': _('View Product')}
        elif self.type == 'price_increase':
            return {'icon': 'fas fa-arrow-up', 'color_class': 'notification-warning', 'action_text': _('Check Product')}
        elif self.type == 'system_message':
            return {'icon': 'fas fa-info-circle', 'color_class': 'notification-system', 'action_text': None}
        return {'icon': 'fas fa-bell', 'color_class': 'notification-default', 'action_text': _('Details')}

class Log(db.Model):
    __tablename__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    level = db.Column(db.String(50), index=True)
    message = db.Column(db.Text)
    module = db.Column(db.String(100))
    func_name = db.Column(db.String(100))
    ip_address = db.Column(db.String(45))

    def __repr__(self):
        return f'<Log {self.id} [{self.level}] {self.message[:50]}>'

class AdminLog(db.Model):
    __tablename__ = 'admin_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    admin_username = db.Column(db.String(80), nullable=False)
    action = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)

    admin = db.relationship('User', backref=db.backref('admin_logs', lazy='dynamic'))

    def __repr__(self):
        return f'<AdminLog {self.id} by {self.admin_username}: {self.action}>'

@login_manager.user_loader
def load_user(user_id):
    import time
    current_app.logger.info(f"Loading user {user_id}")
    start = time.time()
    user = User.query.get(int(user_id))
    current_app.logger.info(f"User {user_id} loaded in {time.time() - start} seconds")
    return user

