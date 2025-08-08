# routes.py
# This module defines Flask routes for product-related functionality,
# including adding products, viewing product history, and handling confirmed product additions.

from flask import Blueprint, render_template, redirect, url_for, flash, current_app, jsonify, request, Response, session
from flask_login import login_required, current_user
from flask_babel import _
from app.models import Product, PriceHistory
from datetime import datetime, timedelta
from sqlalchemy.exc import DataError
from app.products.services import clean_price
import posthog

from app.extensions import db
from app.models import Product
from .forms import ProductForm
from .services import add_product, add_product_service
from app.utils.scrapers import extract_product_name, extract_product_data

# Initialize the products blueprint
bp = Blueprint('products', __name__)

@bp.before_request
def set_default_language():
    if 'lang' not in session:
        session['lang'] = 'en'

@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    """
    Handles the main product tracking page, allowing users to add new products and view their tracked products.

    Returns:
        Response: Rendered template with product form and list of user's products.
    """
    from app.tasks import check_price_for_product
    form = ProductForm()
    current_app.logger.debug(f"Rendering index page with language: {session.get('lang', 'en')}")
    product_data_for_modal = {}

    if form.validate_on_submit():
        try:
            # Extract product data from the provided URL
            scraped_data_raw = extract_product_data(form.product_url.data)

            scraped_data = {}
            if isinstance(scraped_data_raw, dict):
                scraped_data = scraped_data_raw
            elif isinstance(scraped_data_raw, tuple) and len(scraped_data_raw) > 0 and isinstance(scraped_data_raw[0], dict):
                scraped_data = scraped_data_raw[0]
            elif scraped_data_raw is None:
                current_app.logger.error(f"Scraper returned None for URL: {form.product_url.data}")
                flash(_('Could not extract any data from the product page.'), 'error')
                return render_template('index.html', form=form, title=_('Add a Product'), product_data=product_data_for_modal)
            else:
                current_app.logger.error(f"Scraper returned unexpected type: {type(scraped_data_raw)} for url: {form.product_url.data}")
                flash(_('Could not parse product page due to an internal error.'), 'error')
                return render_template('index.html', form=form, title=_('Add a Product'), product_data=product_data_for_modal)

            is_error = False
            if not isinstance(scraped_data, dict) or scraped_data.get('error'):
                is_error = True

            if is_error:
                current_app.logger.warning(f"Parser failed for URL {form.product_url.data}. Returned data: {scraped_data}")
                flash(_('Could not parse product page. Please check the URL and/or try one more time.'), 'error')
                return render_template('index.html', form=form, title=_('Add a Product'), product_data=product_data_for_modal)

            product_name = form.product_name.data or scraped_data.get('name') or "Unknown Product"
            if 'wildberries.' in form.product_url.data:
                flash(_('Heads up! Note on Wildberries prices: The price in our app may differ slightly (5-7%) from Wildberries\' website. This happens because Wildberries shows discounted prices (e.g., for WB Wallet or SBP payments), while we display the actual price from their system — what you’d pay without extra discounts.'), 'wildberries')
            initial_price_str = scraped_data.get('price')
            cleaned_price = clean_price(initial_price_str)

            if cleaned_price is None:
                current_app.logger.warning(f"Unable to parse price from raw value: {initial_price_str}")
                flash(_('Could not determine a valid price from the product page.'), 'error')
                return render_template('index.html', form=form, title=_('Add a Product'), product_data=product_data_for_modal)

            notification_methods = form.notification_methods.data
            if 'email' in form.notification_methods.data and not current_user.enable_email_notifications:
                product_data_for_modal = {
                    'url': form.product_url.data,
                    'name': product_name,
                    'target_price': form.target_price.data,
                    'notification_methods': form.notification_methods.data,
                    'check_frequency': form.check_frequency.data,
                    'price_drop_alert_threshold': form.price_drop_alert_threshold.data,
                    'price_increase_alert_threshold': form.price_increase_alert_threshold.data,
                    'current_price': cleaned_price
                }
                return render_template('index.html', form=form, show_email_confirm_modal=True, product_data=product_data_for_modal)

            product_data = {
                'url': form.product_url.data,
                'name': product_name,
                'target_price': float(form.target_price.data),
                'user_id': current_user.id,
                'notification_methods': form.notification_methods.data,
                'check_frequency': int(form.check_frequency.data),
                'current_price': cleaned_price,
                'price_drop_alert_threshold': form.price_drop_alert_threshold.data,
                'price_increase_alert_threshold': form.price_increase_alert_threshold.data,
            }

            try:
                current_app.logger.info(f"Attempting to add product: {product_data['name']}")
                product = add_product_service(product_data, current_user)

                if product is None:
                    return redirect(url_for('products.index'))

                posthog.capture(str(current_user.id), 'product_added',
                                {'product_id': product.id, 'product_name': product.name})

                if product.url.startswith('mock://'):
                    check_price_for_product.delay(product.id)
                    flash(_('Mock product added. A test notification has been queued! Check your notifications in a minute.'), 'info')
                else:
                    flash(_('Product "%(name)s" added for tracking! We will notify you when the price drops below %(price)s', name=product.name, price=product.target_price), 'success')
                return redirect(url_for('products.index'))

            except DataError as e:
                current_app.logger.error(f"Database error while adding product: {e}")
                db.session.rollback()
                flash(_('Sorry, we could not save the product at this time. Please try again later.'), 'error')
            except Exception as e:
                current_app.logger.error(f"An unexpected error occurred: {e}")
                db.session.rollback()
                flash(_('An unexpected error occurred. Please try again.'), 'error')

        except Exception as e:
            current_app.logger.error(f"Error adding product: {str(e)}", exc_info=True)
            flash(_('Error adding product: %(error)s', error=str(e)), 'error')

    products = Product.query.filter_by(user_id=current_user.id).order_by(Product.created_at.desc()).all()
    return render_template('index.html', form=form, products=products, title=_('Track New Product'), product_data=product_data_for_modal)

@bp.route('/<int:product_id>/history')
@login_required
def product_history(product_id):
    """
    Displays the price history for a specific product.

    Args:
        product_id (int): The ID of the product to display history for.

    Returns:
        Response: Rendered template with product history and metrics.
    """
    product = Product.query.get_or_404(product_id)
    if product.user_id != current_user.id:
        flash('You do not have permission to view this product.', 'error')
        return redirect(url_for('profile.index'))

    history_records = PriceHistory.query.filter_by(product_id=product.id).order_by(PriceHistory.timestamp.asc()).all()

    # Prepare chart data for visualization
    chart_data = {
        "labels": [h.timestamp.strftime('%d.%m.%Y %H:%M') for h in history_records],
        "prices": [float(h.price) for h in history_records]
    }

    initial_price = history_records[0].price if history_records else product.target_price
    price_difference = product.current_price - initial_price if product.current_price and initial_price else 0
    price_difference_percent = (price_difference / initial_price * 100) if initial_price else 0

    # Calculate product metrics
    metrics = {
        "current_price": product.current_price,
        "initial_price": initial_price,
        "price_difference": price_difference,
        "price_difference_percent": f"{price_difference_percent:.1f}",
        "min_price": min([h.price for h in history_records]) if history_records else None,
        "max_price": max([h.price for h in history_records]) if history_records else None,
        "change_count": len(history_records) - 1,
        "last_checked": product.last_checked,
    }

    # Prepare check interval information
    check_info = {
        "interval": product.check_frequency,
        "last_checked": product.last_checked,
        "next_check": (
                    product.last_checked + timedelta(hours=product.check_frequency)) if product.last_checked else None
    }

    # Prepare history table data
    history_for_table = []
    for i, record in enumerate(history_records):
        diff = None
        if i > 0:
            diff = record.price - history_records[i - 1].price
        history_for_table.append({'record': record, 'diff': diff})
    history_for_table.reverse()

    return render_template('products/product_history.html',
                           title=f"History for {product.name}",
                           product=product,
                           metrics=metrics,
                           check_info=check_info,
                           chart_data=chart_data,
                           history_table=history_for_table)

@bp.route('/add-product-confirmed', methods=['POST'])
@login_required
def add_product_confirmed():
    """
    Handles confirmed product addition, including enabling email notifications if requested.

    Returns:
        Response: JSON response indicating success or failure.
    """
    data = request.get_json()
    product_data = data.get('product_data')
    enable_email = data.get('enable_email')

    if enable_email:
        current_user.enable_email_notifications = True
        db.session.add(current_user)
        db.session.commit()
        flash(_('Email notifications have been enabled for your account.'), 'info')
    else:
        if 'email' in product_data.get('notification_methods', []):
            product_data['notification_methods'].remove('email')

    if not product_data.get('notification_methods'):
        return jsonify({'status': 'error', 'message': _('At least one notification method is required.')}), 400

    try:
        current_app.logger.info(f"Received product_data: {product_data}, enable_email: {enable_email}")
        product = add_product_service(product_data, current_user)
        if product is None:
            return jsonify({'status': 'error', 'message': _('Failed to add product. Possibly it\'s already tracked or missing required fields.')}), 400

        return jsonify({
            'status': 'success',
            'message': _('Product "%(name)s" added for tracking!', name=product.name),
            'redirect_url': url_for('profile.tracked_products')
        })
    except Exception as e:
        current_app.logger.error(f"Exception in add_product_confirmed: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': _('Unexpected server error. Please try again later.')}), 500

@bp.route('/enable_email_notifications', methods=['POST'])
@login_required
def enable_email_notifications():
    """
    Enables email notifications for the current user.

    Returns:
        Response: JSON response indicating success or failure.
    """
    data = request.get_json()
    enable = data.get('enable', False)
    if enable:
        current_user.enable_email_notifications = True
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False})