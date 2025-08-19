# services.py
# This module contains service functions for managing products in the application,
# including adding, updating, and deleting products, as well as handling price updates
# and cleaning price strings.

from datetime import datetime
from flask import current_app
from sqlalchemy import orm
from app.extensions import db
import re
import aiohttp
from app.utils.cache_utils import SearchResultsCache
from decimal import Decimal, InvalidOperation
from flask_babel import _
from app.models import Product, PriceHistory
from app.utils.scrapers import extract_product_name
from flask import current_app, flash, redirect, url_for
from sqlalchemy.exc import IntegrityError, DataError
from app.tasks import check_price_for_product
from urllib.parse import urlencode, urlparse
from app.utils.helpers import clean_price
from app.utils.scrapers import extract_product_name #parse_ebay_search_results
import hashlib
from ..utils.scrapers import get_cached, set_cached
import json

def add_product(form_data):
    """
    Adds a new product to the database.

    Args:
        form_data (dict): Form data containing product details such as URL, name, target price, etc.

    Returns:
        Product: The newly created product object.

    Raises:
        ValueError: If the product is already tracked or no notification method is selected.
        Exception: For other unexpected errors during product addition.
    """
    try:
        # Check if the product is already being tracked by the user
        existing_product = Product.query.filter_by(
            url=form_data['url'],
            user_id=form_data['user_id']
        ).first()

        if existing_product:
            raise ValueError(_('This product is already being tracked'))

        if not form_data['notification_methods']:
            raise ValueError(_('No notification method selected.'))

        # Begin a nested transaction to ensure data consistency
        with db.session.begin_nested():
            product = Product(
                url=form_data['url'],
                name=form_data['name'],
                target_price=float(form_data['target_price']),
                notification_methods=form_data['notification_methods'],
                check_frequency=int(form_data['check_frequency']),
                user_id=form_data['user_id'],
                current_price=form_data.get('current_price'),
                price_drop_alert_threshold=form_data.get('price_drop_alert_threshold'),
                price_increase_alert_threshold=form_data.get('price_increase_alert_threshold'),
                last_checked=datetime.utcnow() if form_data.get('current_price') else None
            )
        db.session.flush()

        # Record the initial price history
        initial_history = PriceHistory(
            product_id=product.id,
            price=product.current_price,
            timestamp=datetime.utcnow()
        )
        db.session.add(initial_history)

        db.session.commit()
        current_app.logger.info(f"Product added successfully: {product.id}")
        return product
    except Exception as e:
        current_app.logger.error(f"Failed to add product: {str(e)}", exc_info=True)
        raise e

def update_product_price(product_id, new_price):
    """
    Updates the price of a product in the database.

    Args:
        product_id (int): The ID of the product to update.
        new_price (Decimal): The new price to set for the product.

    Returns:
        bool: True if the update was successful, False if the product was not found.

    Raises:
        Exception: If an error occurs during the update process.
    """
    current_app.logger.debug(f"Updating price for product {product_id} to {new_price}")
    product = Product.query.get(product_id)
    if product:
        try:
            product.current_price = new_price
            product.last_checked = datetime.utcnow()
            db.session.commit()
            current_app.logger.info(f"Price updated for product {product_id}")
            return True
        except Exception as e:
            current_app.logger.error(f"Failed to update product price: {str(e)}", exc_info=True)
            db.session.rollback()
            raise e
    current_app.logger.warning(f"Product not found for price update: {product_id}")
    return False

def get_user_products(user_id):
    """
    Retrieves all products tracked by a specific user.

    Args:
        user_id (int): The ID of the user whose products are to be retrieved.

    Returns:
        list: A list of Product objects associated with the user, ordered by creation date.
    """
    current_app.logger.debug(f"Fetching products for user: {user_id}")
    return db.session.query(Product).options(
        orm.joinedload(Product.user)
    ).filter_by(
        user_id=user_id
    ).order_by(
        Product.created_at.desc()
    ).all()

def batch_update_prices(price_updates):
    """
    Updates prices for multiple products in a single transaction.

    Args:
        price_updates (dict): A dictionary mapping product IDs to their new prices.

    Returns:
        bool: True if the batch update was successful, False otherwise.
    """
    try:
        # Begin a nested transaction for batch updates
        with db.session.begin_nested():
            for product_id, new_price in price_updates.items():
                db.session.query(Product).filter_by(id=product_id).update({
                    'current_price': new_price,
                    'last_checked': datetime.utcnow()
                })
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Batch update failed: {str(e)}")
        return False

def get_product_by_id(product_id):
    """
    Retrieves a product by its ID.

    Args:
        product_id (int): The ID of the product to retrieve.

    Returns:
        Product: The Product object if found, None otherwise.
    """
    current_app.logger.debug(f"Fetching product by ID: {product_id}")
    return Product.query.get(product_id)

def delete_product(product_id):
    """
    Deletes a product from the database.

    Args:
        product_id (int): The ID of the product to delete.

    Returns:
        bool: True if the deletion was successful, False if the product was not found.

    Raises:
        Exception: If an error occurs during the deletion process.
    """
    product = Product.query.get(product_id)
    if product:
        try:
            db.session.delete(product)
            db.session.commit()
            current_app.logger.info(f"Product deleted successfully: {product_id}")
            return True
        except Exception as e:
            current_app.logger.error(f"Failed to delete product: {str(e)}", exc_info=True)
            db.session.rollback()
            raise e
    current_app.logger.warning(f"Product not found for deletion: {product_id}")
    return False


def add_product_service(product_data: dict, user):
    """
    Adds a product to the database for a specific user with additional validation and notification handling.

    Args:
        product_data (dict): Dictionary containing product details.
        user (User): The user adding the product.

    Returns:
        Product | None: The added product object, or None if addition fails.
    """
    try:
        # Check for existing product
        existing_product = Product.query.filter_by(
            url=product_data.get('url'),
            user_id=user.id
        ).first()

        if existing_product:
            flash(_('This product is already being tracked.'), 'warning')
            return None

        if not product_data.get('notification_methods'):
            flash(_('At least one notification method is required.'), 'error')
            return None

        # Create new product
        new_product = Product(
            user_id=user.id,
            url=product_data.get('url'),
            name=product_data.get('name', 'Unknown Product'),
            target_price=Decimal(str(product_data.get('target_price', 0))),
            notification_methods=product_data.get('notification_methods', []),
            current_price=Decimal(str(product_data.get('current_price', 0))) if product_data.get('current_price') is not None else None,
            price_drop_alert_threshold=Decimal(str(product_data.get('price_drop_alert_threshold', 0))) if product_data.get('price_drop_alert_threshold') is not None else None,
            price_increase_alert_threshold=Decimal(str(product_data.get('price_increase_alert_threshold', 0))) if product_data.get('price_increase_alert_threshold') is not None else None,
            check_frequency=int(product_data.get('check_frequency', 24)),
            last_checked=datetime.utcnow() if product_data.get('current_price') is not None else None
        )
        new_product.generate_identifier()

        existing_group_product = Product.query.filter(
            Product.user_id == user.id,
            Product.product_identifier == new_product.product_identifier,
            Product.id != new_product.id
        ).first()

        if existing_group_product:
            new_product.comparison_group_id = existing_group_product.comparison_group_id
            flash(_('Found a similar product in your list, grouping them together!'), 'info')

        db.session.add(new_product)
        db.session.flush()

        # Record initial price history
        initial_history = PriceHistory(
            product_id=new_product.id,
            price=new_product.current_price,
            timestamp=datetime.utcnow()
        )
        db.session.add(initial_history)

        # Trigger notification if target price is reached
        if new_product.current_price is not None and new_product.current_price <= new_product.target_price:
            check_price_for_product.delay(new_product.id)

        db.session.commit()
        #flash(_('Product "%(name)s" added for tracking!', name=new_product.name), 'success')
        return new_product

    except IntegrityError:
        db.session.rollback()
        flash(_('There was a database error. It seems this product is already tracked.'), 'error')
        return None
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in add_product_service: {e}", exc_info=True)
        flash(_('An unexpected error occurred while adding the product.'), 'danger')
        return None

def add_product_service_for_tg(product_data, user):
    """
    Adds a product to the database for a given user, tailored for Telegram integration.

    Args:
        product_data (dict): Dictionary containing product details.
        user (User): The user adding the product.

    Returns:
        tuple: A tuple containing the added Product object (or None) and an error message (or None).
    """
    try:
        # Validate required fields
        required_fields = ['url', 'name', 'target_price', 'notification_methods', 'check_frequency']
        missing_fields = [field for field in required_fields if product_data.get(field) is None]
        if missing_fields:
            return None, f"Missing required fields: {', '.join(missing_fields)}."

        # Check if product already exists
        existing_product = Product.query.filter_by(user_id=user.id, url=product_data['url']).first()
        if existing_product:
            return None, "This product is already in your tracking list."

        # Create new product
        product = Product(
            url=product_data['url'],
            name=product_data['name'][:255],
            target_price=Decimal(str(product_data['target_price'])),
            user_id=user.id,
            notification_methods=product_data['notification_methods'],
            check_frequency=int(product_data['check_frequency']),
            current_price=Decimal(str(product_data.get('current_price', 0))) if product_data.get('current_price') else None
        )

        db.session.add(product)
        db.session.commit()
        return product, None

    except DataError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error adding product for user {user.id}: {str(e)}", exc_info=True)
        return None, "Invalid data provided. Please check your input and try again."
    except IntegrityError as e:
        db.session.rollback()
        current_app.logger.error(f"Integrity error adding product for user {user.id}: {str(e)}", exc_info=True)
        return None, "This product is already tracked or the data is invalid."
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unexpected error adding product for user {user.id}: {str(e)}", exc_info=True)
        return None, "An unexpected error occurred. We've logged it and will fix it soon."