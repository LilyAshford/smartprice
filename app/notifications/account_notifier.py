from flask import current_app
from flask_babel import force_locale, _
from app.extensions import db
from app.models import UserNotification, Product, User
from datetime import datetime

def create_account_notification(user_id, type, short_message, message=None, product_id=None, data=None, locale='en'):
    app = current_app._get_current_object()
    try:
        with force_locale(locale):
            notification = UserNotification(
                user_id=user_id,
                type=type,
                short_message=short_message,
                message=message,
                product_id=product_id,
                data=data or {},
                created_at=datetime.utcnow()
            )
            db.session.add(notification)
            db.session.commit()
            app.logger.info(f"Account notification '{type}' created for user {user_id}")
            return notification
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating account notification for user {user_id}: {str(e)}", exc_info=True)
        return None

def create_price_alert_account_notification(user, product, old_price, new_price, alert_type="target_reached"):
    locale = user.language if user.language else 'en'
    with force_locale(locale):
        product_link = f"<a href='{product.url}' target='_blank'>{product.name}</a>"

        price_diff = None
        if old_price and new_price:
            price_diff = float(old_price) - float(new_price)

        data = {
            'old_price': float(old_price) if old_price else None,
            'new_price': float(new_price) if new_price else None,
            'currency': '$',
            'price_diff': round(price_diff, 2) if price_diff is not None else None
        }

        short_message = ""
        message_body = ""

        if alert_type == "target_reached":
            short_message = _('🎯 Price for "%(name)s" reached your target!', name=product.name)
            message_body = _('Current Price: %(new_price)s$. Target: %(target)s$.',
                           new_price=new_price, target=product.target_price)
        elif alert_type == "price_drop":
            short_message = _('📉 Price dropped for "%(name)s" to %(new_price)s$!',
                            name=product.name, new_price=new_price)
            message_body = _('Previous price was %(old_price)s$.', old_price=old_price) if old_price else ""
        else:
            short_message = _('📈 Price increased for "%(name)s" to %(new_price)s$!',
                            name=product.name, new_price=new_price)
            message_body = _('Previous price was %(old_price)s$.', old_price=old_price) if old_price else ""

        full_message = f"{short_message} {message_body}<br>{_('Product:')} {product_link}"

        return create_account_notification(
            user_id=user.id,
            type=alert_type,
            short_message=short_message,
            message=full_message,
            product_id=product.id,
            data=data,
            locale=locale
        )

def create_system_account_notification(user_id, message_details):
    user = User.query.get(user_id)
    if not user:
        return None
    locale = user.language if user.language else 'en'
    with force_locale(locale):
        short_message = _("Message from Admin")
        return create_account_notification(
            user_id=user_id,
            type="system_message",
            short_message=short_message,
            message=message_details,
            locale=locale
        )

def create_savings_report_notification(user_id, savings_amount, period="the last month"):
    user = User.query.get(user_id)
    if not user:
        return None
    locale = user.language if user.language else 'en'
    with force_locale(locale):
        short_msg = _("🎉 Your Savings Report for %(period)s is here!", period=period)
        message = _("You've saved approximately %(amount)s$ with SmartPrice. Keep tracking!", amount=savings_amount)
        return create_account_notification(
            user_id=user_id,
            type="savings_report",
            short_message=short_msg,
            message=message,
            locale=locale
        )