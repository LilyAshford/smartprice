from flask import current_app, url_for
from flask_babel import force_locale, _
from app.mail_services import send_email

def get_tracking_url(product_id=None):
    """Generate the URL for the tracked products page, optionally highlighting a specific product."""
    app = current_app._get_current_object()
    try:
        with app.app_context():
            if product_id:
                return url_for('profile.tracked_products', highlight=product_id, _external=True)
            return url_for('profile.tracked_products', _external=True)
    except RuntimeError:
        # Fallback for contexts where request is unavailable (e.g., Celery tasks)
        base_url = f"{app.config['PREFERRED_URL_SCHEME']}://{app.config['SERVER_NAME']}/profile/tracked-products"
        if product_id:
            return f"{base_url}?highlight={product_id}"
        return base_url

def send_price_alert_email(user, product, old_price, new_price, alert_type="target_reached"):
    """Send a price alert email to the user."""
    app = current_app._get_current_object()
    if not user.email or not user.enable_email_notifications:
        app.logger.info(f"Email notifications disabled or no email for user {user.id}. Skipping price alert.")
        return False

    if old_price is None:
        app.logger.error(f"Cannot send price alert - old_price is None for product {product.id}")
        return False

    locale = user.language if user and user.language else app.config.get('BABEL_DEFAULT_LOCALE', 'en')

    template_data = {
        'user': user,
        'product': product,
        'old_price': float(old_price) if old_price else None,
        'new_price': float(new_price) if new_price else None,
        'product_url': product.url,
        'tracking_dashboard_url': get_tracking_url(product.id),
    }

    try:
        with force_locale(locale):
            if alert_type == "target_reached":
                subject = _('🎯 Price Alert! "%(name)s" reached your target price!', name=product.name)
                template_name = 'email/notifications/target_price_reached'
            elif alert_type == "price_drop":
                subject = _('📉 Price Drop for "%(name)s"!', name=product.name)
                template_name = 'email/notifications/price_drop'
            else:
                subject = _('📈 Price Increase for "%(name)s"!', name=product.name)
                template_name = 'email/notifications/price_increase'
                template_data['target_price'] = float(product.target_price) if product.target_price else None

        send_email(
            to=user.email,
            subject=subject,
            template=template_name,
            locale=locale,
            **template_data
        )

        app.logger.info(f"Price alert email for user {user.id} queued successfully.")
        return True
    except Exception as e:
        app.logger.error(f"Failed to queue price alert email for user {user.id}: {str(e)}", exc_info=True)
        return False