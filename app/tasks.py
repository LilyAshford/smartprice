from decimal import Decimal
from datetime import datetime, timedelta
from app.notifications.telegram_notifier import send_telegram_price_alert, send_telegram_message, create_inline_keyboard, escape_markdown_v2
from flask import current_app, url_for
import random
import decimal
from sqlalchemy.exc import IntegrityError
from celery import shared_task
from app.models import db, Product, User, PriceHistory
from app.notifications.account_notifier import create_price_alert_account_notification, create_system_account_notification
from app.notifications.email_notifier import send_price_alert_email
from app.mail_services import send_email
from app.utils.scrapers import extract_product_data, MockParser, run_async_in_sync
from sqlalchemy import func, text
from app.notifications.telegram_notifier import send_telegram_price_alert, send_telegram_message
from urllib.parse import urlparse
import requests
from flask_babel import _, force_locale
from sqlalchemy import or_

# Task to check and update the price of a specific product.
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def check_price_for_product(self, product_id, mock_scenario=None, mock_target_price=None, mock_current_price=None, locale='en'):
    """
    Check the price for a given product and update its status.
    Can use mock data for testing purposes without affecting the database.
    """
    with current_app.app_context():
        product = Product.query.get(product_id)
        if not product:
            current_app.logger.error(f"Product {product_id} not found")
            return

        locale = product.user.language if product.user and product.user.language else locale
        original_target_price = product.target_price
        original_current_price = product.current_price

        try:
            raw_data = None
            is_mock = bool(mock_scenario)
            if is_mock:
                current_app.logger.info(f"Using MOCK data for product {product_id} with scenario: {mock_scenario}")
                mock_product = Product(
                    id=product.id,
                    name=product.name,
                    url=product.url,
                    target_price=Decimal(str(mock_target_price)),
                    current_price=Decimal(str(mock_current_price)),
                    notification_methods=product.notification_methods,
                    user=product.user
                )
                mock_url = f"mock://{mock_scenario}/{product_id}"
                raw_data, _ = run_async_in_sync(MockParser(mock_url).parse())
            else:
                current_app.logger.info(f"Running REAL price check for product {product_id}")
                raw_data = extract_product_data(product.url)

            if isinstance(raw_data, tuple) and len(raw_data) == 2:
                data, has_error = raw_data
            elif isinstance(raw_data, dict):
                data = raw_data
                has_error = not data.get('success', False)
            else:
                current_app.logger.error(f"Unexpected data format from parser for product {product_id}: {raw_data}")
                return

            if is_mock:
                has_error = False

            if has_error:
                current_app.logger.error(
                    f"Error parsing product {product_id}: {data.get('error')}, details: {data.get('details')}")
                return

            new_price_raw = data.get('price')
            if new_price_raw is None:
                current_app.logger.error(f"No price found for product {product_id} in parsed data: {data}")
                return

            new_price = None
            try:
                cleaned_price_str = str(new_price_raw).replace('$', '').replace(',', '').strip()
                if cleaned_price_str:
                    new_price = Decimal(cleaned_price_str)
                else:
                    raise decimal.InvalidOperation("Price string is empty after cleaning.")

            except (ValueError, decimal.InvalidOperation) as e:
                current_app.logger.error(
                    f"Could not convert raw price '{new_price_raw}' to Decimal for product {product_id}. Error: {e}")
                return


            old_price = mock_product.current_price if is_mock else product.current_price

            if is_mock:
                current_app.logger.info(f"Mock price check for product {product_id}: new_price={new_price}")
            else:
                product.current_price = new_price
                product.last_checked = datetime.utcnow()

                price_history = PriceHistory(
                    product_id=product.id,
                    price=new_price,
                    timestamp=datetime.utcnow()
                )
                db.session.add(price_history)

            user = product.user
            if not user:
                current_app.logger.error(f"User not found for product {product_id}")
                return

            alert_types = []
            target_price = mock_product.target_price if is_mock else product.target_price

            if new_price <= target_price and user.enable_target_price_reached_notifications:
                alert_types.append('target_reached')
                if not is_mock:
                    product.target_price_notified = True
            elif old_price and new_price < old_price and user.enable_price_drop_notifications:
                drop_amount = old_price - new_price
                if not product.price_drop_alert_threshold or drop_amount >= product.price_drop_alert_threshold:
                    alert_types.append('price_drop')

            if old_price and new_price > old_price:
                increase_amount = new_price - old_price
                if product.price_increase_alert_threshold and increase_amount >= product.price_increase_alert_threshold:
                    alert_types.append('price_increase')

            if old_price and new_price > target_price and product.target_price_notified:
                product.target_price_notified = False

            for alert_type in alert_types:
                with force_locale(locale):
                    process_notifications(mock_product if is_mock else product, alert_type, old_price, new_price)

            if not is_mock:
                db.session.add(product)
                db.session.commit()
                current_app.logger.info(f"Price updated for product {product_id}: {new_price}")

        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(f"Error updating product {product_id}: {str(exc)}", exc_info=True)
            try:
                current_app.logger.warning(f"Retrying task for product {product_id} due to: {str(exc)}")
                self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                current_app.logger.error(f"Max retries exceeded for product {product_id}")
        finally:
            if is_mock and (product.target_price != original_target_price or product.current_price != original_current_price):
                try:
                    product.target_price = original_target_price
                    product.current_price = original_current_price
                    db.session.add(product)
                    db.session.commit()
                    current_app.logger.info(f"Restored real values for product {product_id} after mock test")
                except Exception as restore_exc:
                    db.session.rollback()
                    current_app.logger.error(
                        f"Failed to restore original values for product {product_id}: {str(restore_exc)}", exc_info=True)


def process_notifications(product, alert_type, old_price, new_price):
    """
    Process notifications for a product based on alert type.
    Args:
        product (Product): Product object (real or mock).
        alert_type (str): Type of alert ('price_drop', 'target_reached', 'price_increase').
        old_price (float): Previous price.
        new_price (float): Current price.
    """
    user = product.user
    if not user:
        current_app.logger.warning(f"No user found for product {product.id}")
        return

    if alert_type == 'target_reached' and not user.enable_target_price_reached_notifications:
        current_app.logger.info(f"Target price notifications disabled for user {user.id}")
        return
    elif alert_type == 'price_drop' and not user.enable_price_drop_notifications:
        current_app.logger.info(f"Price drop notifications disabled for user {user.id}")
        return
    elif alert_type == 'price_increase' and not user.enable_price_notifications:
        current_app.logger.info(f"Price increase notifications disabled for user {user.id}")
        return

    current_app.logger.info(f"Processing '{alert_type}' notifications for user {user.id}, product {product.id}")

    notification_methods = product.notification_methods or ['account']
    if 'account' in notification_methods:
        create_price_alert_account_notification(user, product, old_price, new_price, alert_type)
    if 'email' in notification_methods and user.enable_email_notifications:
        if old_price is None:
            current_app.logger.warning(f"Cannot send email for product {product.id} - old_price is None")
        else:
            send_price_alert_email(user, product, old_price, new_price, alert_type)
    if 'telegram' in notification_methods and user.telegram_chat_id:
        send_telegram_price_alert(user, product, old_price, new_price, alert_type)

# Schedule price checks for products that need updating.
@shared_task
def schedule_price_checks():
    try:
        current_app.logger.info("Scheduling price checks")
        products = Product.query.filter(
            or_(
                Product.last_checked.is_(None),
                Product.last_checked < func.now() - text("INTERVAL '1 hour' * check_frequency")
            )
        ).all()

        current_app.logger.info(f"Found {len(products)} products to check.")
        for product in products:
            check_price_for_product.delay(product.id)

    except Exception as e:
        current_app.logger.error(f"Error scheduling price checks: {e}", exc_info=True)


@shared_task
def send_test_notification(user_email, notification_type='price_drop'):
    """
    Sends a test notification.
    """
    with current_app.app_context():
        try:
            user = User.query.filter_by(email=user_email).first()
            if not user:
                current_app.logger.error(f"User for test notification {user_email} not found")
                return

            locale = user.language if user.language else 'en'
            with force_locale(locale):
                product_template = Product.query.filter_by(user_id=user.id).first()
                if not product_template:
                    product_template = Product(
                        name="Test product",
                        url="http://example.com",
                        target_price=Decimal('1000'),
                        notification_methods=['account', 'email', 'telegram']
                    )

                test_product = Product(
                    id=product_template.id,
                    name=product_template.name,
                    url=product_template.url,
                    target_price=product_template.target_price,
                    notification_methods=product_template.notification_methods,
                    user=user
                )

                current_app.logger.info(f"Sending test '{notification_type}' for user {user.email}")

                base_price = test_product.target_price or Decimal('100')
                old_price = base_price * Decimal('1.2')
                new_price = base_price * Decimal('0.8')

                process_notifications(test_product, notification_type, old_price, new_price)

                current_app.logger.info("Test notification processed successfully (without DB changes).")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error sending test notification to {user_email}: {str(e)}", exc_info=True)

# Send an admin message to a user via the specified channel.
@shared_task
def send_admin_message_task(user_id, channel, message):
    with current_app.app_context():
        user = User.query.get(user_id)
        if not user:
            return

        locale = user.language if user.language else 'en'
        with force_locale(locale):
            if channel == 'email':
                send_email(user.email, 'A message from our admin', 'email/admin_message', message_body=message)
            elif channel == 'telegram' and user.telegram_chat_id:
                send_telegram_message(user.telegram_chat_id, message)
            elif channel == 'account':
                create_system_account_notification(user.id, message)

# Clean up unconfirmed users older than 24 hours.
@shared_task
def cleanup_unconfirmed_users():
    """Deletes unconfirmed users older than 24 hours."""
    try:
        threshold = datetime.utcnow() - timedelta(hours=24)
        users_to_delete = User.query.filter(User.confirmed == False, User.created_at < threshold).all()

        if not users_to_delete:
            current_app.logger.info("Cleanup: No unconfirmed users to delete.")
            return

        count = len(users_to_delete)
        for user in users_to_delete:
            Product.query.filter_by(user_id=user.id).delete(synchronize_session=False)
            db.session.delete(user)

        db.session.commit()
        current_app.logger.info(f"Cleanup: Deleted {count} unconfirmed users.")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error during cleanup of unconfirmed users: {e}", exc_info=True)

# Lists for /coffee and /quote commands
COFFEE_TIPS = [
    "Use freshly roasted beans for the best flavor.",
    "Grind your coffee just before brewing.",
    "Store coffee beans in an airtight container away from light.",
    "Use filtered water for a cleaner taste.",
    "Experiment with different brewing methods (e.g., French press, pour-over).",
    "Keep your coffee equipment clean to avoid bitter flavors.",
    "Try a coarser grind for French press and a finer grind for espresso.",
    "Use a scale to measure coffee and water for consistency.",
    "Brew at the right temperature (195°F to 205°F).",
    "Try adding a pinch of salt to reduce bitterness.",
    "Use a gooseneck kettle for better pour control.",
    "Experiment with different coffee-to-water ratios.",
    "Try cold brew for a smoother, less acidic coffee.",
    "Use a timer to perfect your brewing time.",
    "Try adding spices like cinnamon or cardamom for unique flavors.",
    "Use a burr grinder for a more consistent grind.",
    "Avoid boiling water; it can scorch the coffee.",
    "Try a coffee subscription to explore different beans.",
    "Use a thermal carafe to keep coffee hot without burning.",
    "Experiment with latte art for a fun presentation."
]

QUOTES = [
    "A penny saved is a penny earned. - Benjamin Franklin",
    "Do not save what is left after spending, but spend what is left after saving. - Warren Buffett",
    "Wealth consists not in having great possessions, but in having few wants. - Epictetus",
    "It's not your salary that makes you rich, it's your spending habits. - Charles A. Jaffe",
    "The art is not in making money, but in keeping it. - Proverb",
    "Beware of little expenses; a small leak will sink a great ship. - Benjamin Franklin",
    "The goal isn't more money. The goal is living life on your terms. - Chris Brogan",
    "Financial freedom is available to those who learn about it and work for it. - Robert Kiyosaki",
    "The more you learn, the more you earn. - Warren Buffett",
    "Success is not the key to happiness. Happiness is the key to success. - Albert Schweitzer",
    "The only way to do great work is to love what you do. - Steve Jobs",
    "Don't watch the clock; do what it does. Keep going. - Sam Levenson",
    "The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt",
    "Opportunities don't happen. You create them. - Chris Grosser",
    "The best way to predict the future is to create it. - Peter Drucker",
    "Your time is limited, don’t waste it living someone else’s life. - Steve Jobs",
    "The harder you work for something, the greater you’ll feel when you achieve it. - Unknown",
    "Dream big and dare to fail. - Norman Vaughan",
    "Success usually comes to those who are too busy to be looking for it. - Henry David Thoreau",
    "The stock market is filled with individuals who know the price of everything, but the value of nothing. - Philip Fisher"
]

# Parse a price input string into a float.
def parse_price_input(text):
    """
    Parse a price input to handle formats like '23 300', '23,300', or '23300'.
    Args:
        text (str): The input string to parse.
    Returns:
        float or None: The parsed float value, or None if invalid.
    """
    try:
        import re
        cleaned_text = re.sub(r'[,\s]', '', text)
        return float(cleaned_text)
    except (ValueError, TypeError):
        return None

# Process incoming Telegram updates.
@shared_task
def process_telegram_update(update_data):
    with current_app.app_context():
        if 'callback_query' in update_data:
            handle_callback_query_in_task(update_data['callback_query'])
            return

        if 'message' not in update_data:
            current_app.logger.info("No message in update, skipping")
            return

        message = update_data['message']
        chat_id = str(message['chat']['id'])
        text = message.get('text', '').strip()
        current_app.logger.info(f"Processing message: text={text}, chat_id={chat_id}")

        if text.startswith('/start'):
            parts = text.split(' ', 1)
            if len(parts) == 2 and parts[1].strip():
                token = parts[1].strip()
                current_app.logger.info(f"Attempting to link with token: {token}")
                user = User.query.filter_by(telegram_linking_token=token).first()
                if user:
                    if user.telegram_chat_id:
                        current_app.logger.info(f"User {user.id} already linked to chat {user.telegram_chat_id}")
                        send_telegram_message(chat_id, "This account is already linked to another Telegram chat.")
                    else:
                        try:
                            user.telegram_chat_id = chat_id
                            user.telegram_linking_token = None
                            db.session.commit()
                            current_app.logger.info(f"User {user.id} linked to chat {chat_id}")
                            send_telegram_message(chat_id,
                                                  "Your Telegram account has been successfully linked! Welcome! Use /help for a list of commands. 🎉")
                        except IntegrityError:
                            db.session.rollback()
                            current_app.logger.warning(f"Chat {chat_id} is already linked to another user.")
                            send_telegram_message(chat_id, "This Telegram chat is already linked to another account.")
                    return
                else:
                    current_app.logger.warning(f"Invalid bind token: {token}")
                    send_telegram_message(chat_id,
                                          "Invalid token. Please try to bind again through the site.")
                    return

        user = User.query.filter_by(telegram_chat_id=chat_id).first()
        if not user:
            send_telegram_message(chat_id,
                                  "Please link your Telegram account via the website first. 🔗")
            return

        # Handle commands even when in a state
        if user.telegram_state and text.startswith('/'):
            if text == '/cancel':
                user.telegram_state = None
                user.temp_data = {}
                db.session.commit()
                send_telegram_message(chat_id, "Operation cancelled. How can I assist you now? Use /help for options. 😊")
            else:
                send_telegram_message(chat_id, "You're currently in the middle of an operation. Use /cancel to stop or continue with the current task. ⚠️")
            return

        # Process the message based on state or command
        if user.telegram_state:
            handle_state_message_in_task(user, text, chat_id)
        else:
            handle_command_in_task(user, text, chat_id)

        db.session.commit()

# Handle Telegram callback queries.
def handle_callback_query_in_task(callback_query):
    chat_id = str(callback_query['message']['chat']['id'])
    callback_data = callback_query['data']
    callback_query_id = callback_query['id']
    user = User.query.filter_by(telegram_chat_id=chat_id).first()

    requests.post(
        f"https://api.telegram.org/bot{current_app.config['TELEGRAM_BOT_TOKEN']}/answerCallbackQuery",
        json={'callback_query_id': callback_query_id}
    )

    if not user:
        return

    # Create a local copy of temp_data for safe modifications
    temp_data = user.temp_data.copy() if user.temp_data else {}

    if user.telegram_state == 'awaiting_name_choice':
        if callback_data == 'use_parsed_name':
            scraped_name = temp_data.get('scraped_data', {}).get('name')

            # Verify that a valid name is available
            if scraped_name and scraped_name.strip():
                temp_data['name'] = scraped_name
                user.telegram_state = 'awaiting_target_price'
                send_telegram_message(chat_id,
                                      "Great! Now please enter the target price (e.g., 23300, 23 300, or 23,300). 💰")
            else:
                # Fallback if no valid name is found
                user.telegram_state = 'awaiting_name'
                send_telegram_message(chat_id, "Couldn't retrieve a name. Please enter the product name manually. 📝")

        elif callback_data == 'enter_manual_name':
            user.telegram_state = 'awaiting_name'
            send_telegram_message(chat_id, "Please enter the product name manually. 📝")

    elif user.telegram_state == 'awaiting_check_frequency':
        frequency_map = {'twice_a_day': 12, 'once_a_day': 24, 'every_2_days': 48, 'once_a_week': 168}
        if callback_data in frequency_map:
            temp_data['check_frequency'] = frequency_map[callback_data]

            from app.products.services import add_product_service_for_tg
            product, error = add_product_service_for_tg(temp_data, user)

            if product:
                send_telegram_message(chat_id, f"Product '{product.name}' added successfully! 🎉")
            else:
                current_app.logger.warning(f"Failed to add product for user {user.id}: {error}")
                send_telegram_message(chat_id, f"Failed to add product: {error or 'Unknown error.'} 😔")

            # Reset state after completion
            user.telegram_state = None
            user.temp_data = {}
        else:
            send_telegram_message(chat_id, "Invalid selection. Please try again. 😅")

    # Save changes to user.temp_data
    user.temp_data = temp_data
    db.session.commit()

# Handle Telegram commands.
def handle_command_in_task(user, text, chat_id):
    current_app.logger.info(f"Handling command '{text}' for user {user.id}, chat_id={chat_id}")
    if text == '/start':
        send_telegram_message(chat_id, "Welcome! Use /help to see available commands. 😊")
    elif text == '/help':
        help_message = (
            "Available commands:\n\n"
            "/products - Show your tracked products.\n"
            "/site - Go to your profile on the website.\n"
            "/add - Add a new product to track.\n"
            "/remove - Remove a tracked product.\n"
            "/random - Show a random tracked product.\n"
            "/coffee - Get a coffee break message and tip.\n"
            "/quote - Get a random savings quote.\n"
            "/help - Show this help message."
        )
        send_telegram_message(chat_id, help_message)
    elif text == '/products':
        products = Product.query.filter_by(user_id=user.id).all()
        if not products:
            send_telegram_message(chat_id, "You have no tracked products. 😕")
        else:
            message = "Your tracked products:\n\n"
            for product in products:
                message += (
                    f"ID: {product.id}\n"
                    f"Name: {product.name}\n"
                    f"Current Price: {product.current_price or 'N/A'}\n"
                    f"Target Price: {product.target_price or 'N/A'}\n"
                    f"URL: {product.url}\n\n"
                )
            send_telegram_message(chat_id, message)
    elif text == '/site':
        send_telegram_message(chat_id, "The profile feature is under development. Stay tuned! 🚀")
    elif text == '/add':
        user.telegram_state = 'awaiting_url'
        user.temp_data = {}
        db.session.commit()
        send_telegram_message(chat_id, "Please send the product URL. 🔗")
    elif text == '/remove':
        products = Product.query.filter_by(user_id=user.id).all()
        if not products:
            send_telegram_message(chat_id, "You have no tracked products to remove. 😕")
        else:
            message = "Your tracked products:\n"
            for product in products:
                message += f"- {product.name} (ID: {product.id})\n"
            send_telegram_message(chat_id, message + "\nPlease send the ID of the product to remove. 🗑️")
            user.telegram_state = 'awaiting_remove_id'
            db.session.commit()
    elif text == '/random':
        products = Product.query.filter_by(user_id=user.id).all()
        if not products:
            send_telegram_message(chat_id, "You have no tracked products. 😕")
        else:
            random_product = random.choice(products)
            message = (
                f"Random product:\n"
            f"Name: {random_product.name}\n"
                f"Current Price: {random_product.current_price or 'N/A'}\n"
                f"Target Price: {random_product.target_price or 'N/A'}\n"
                f"URL: {random_product.url}"
            )
            send_telegram_message(chat_id, message)
    elif text == '/coffee':
        tip = random.choice(COFFEE_TIPS)
        message = f"Time for a coffee break! ☕\n\nTip: {tip}"
        send_telegram_message(chat_id, message)
    elif text == '/quote':
        quote = random.choice(QUOTES)
        send_telegram_message(chat_id, quote)
    else:
        # If the message isn't a command, check the state
        if user.telegram_state:
            handle_state_message_in_task(user, text, chat_id)
        else:
            send_telegram_message(chat_id, "Unknown command. Use /help for options. 🤔")

# Handle Telegram state-based messages.
def handle_state_message_in_task(user, text, chat_id):
    current_app.logger.info(
        f"Handling state '{user.telegram_state}' for user {user.id}, input='{text}', temp_data={user.temp_data}")

    temp_data = user.temp_data.copy() if user.temp_data else {}

    if user.telegram_state == 'awaiting_url':
        scraped_data_raw = extract_product_data(text)
        # Handle tuple or dict output from extract_product_data
        if isinstance(scraped_data_raw, tuple) and len(scraped_data_raw) > 0 and isinstance(scraped_data_raw[0], dict):
            scraped_data = scraped_data_raw[0]
        elif isinstance(scraped_data_raw, dict):
            scraped_data = scraped_data_raw
        else:
            send_telegram_message(chat_id, "Could not extract product data. Please check the URL and try again. 🔍")
            user.telegram_state = None
            user.temp_data = {}
            db.session.commit()
            return

        if 'error' in scraped_data:
            send_telegram_message(chat_id, f"Failed to fetch product data: {scraped_data['error']}. Please try again. 😔")
            user.telegram_state = None
            user.temp_data = {}
            db.session.commit()
            return

        # Ensure price is valid
        if not scraped_data.get('price'):
            send_telegram_message(chat_id, "Could not determine a valid price from the product page. Please try again. 😕")
            user.telegram_state = None
            user.temp_data = {}
            db.session.commit()
            return

        temp_data = {'scraped_data': scraped_data, 'url': text}
        user.telegram_state = 'awaiting_name_choice'

        buttons = [[{'text': 'Use extracted name', 'callback_data': 'use_parsed_name'}],
                   [{'text': 'Enter name manually', 'callback_data': 'enter_manual_name'}]]
        reply_markup = create_inline_keyboard(buttons)
        parsed_name = scraped_data.get('name', 'N/A')
        send_telegram_message(chat_id,
                              f"Found product: *{escape_markdown_v2(parsed_name)}*\n\nUse this name or enter your own? 🤔",
                              reply_markup=reply_markup, parse_mode='MarkdownV2')

    elif user.telegram_state == 'awaiting_name':
        if not text.strip():
            send_telegram_message(chat_id,
                                  "Product name cannot be empty. Please enter a valid name. 📝")
            return
        temp_data['name'] = text.strip()
        user.telegram_state = 'awaiting_target_price'
        send_telegram_message(chat_id, "Great! Now enter the target price. 💰")

    elif user.telegram_state == 'awaiting_target_price':
        target_price = parse_price_input(text)
        if target_price is None or target_price <= 0:
            send_telegram_message(chat_id, "Invalid price. Please enter a positive number. 🚫")
            return
        temp_data['target_price'] = target_price
        user.telegram_state = 'awaiting_notification_methods'
        send_telegram_message(chat_id,
                              "Enter notification methods (e.g., Email, Telegram, Account), separated by commas. 📩")

    elif user.telegram_state == 'awaiting_notification_methods':
        methods_input = [m.strip().capitalize() for m in text.split(',') if m.strip()]
        valid_methods = ['Email', 'Telegram', 'Account']

        # Check if all entered methods are valid
        if methods_input and all(m in valid_methods for m in methods_input):
            temp_data['notification_methods'] = methods_input
            user.telegram_state = 'awaiting_check_frequency'

            buttons = [
                [{'text': 'Twice a day', 'callback_data': 'twice_a_day'}],
                [{'text': 'Once a day', 'callback_data': 'once_a_day'}],
                [{'text': 'Every 2 days', 'callback_data': 'every_2_days'}],
                [{'text': 'Once a week', 'callback_data': 'once_a_week'}]
            ]
            reply_markup = create_inline_keyboard(buttons)
            send_telegram_message(chat_id, "How often should we check the price? ⏰", reply_markup=reply_markup)
        else:
            send_telegram_message(chat_id, "Invalid methods. Please use: Email, Telegram, Account. 😅")

    elif user.telegram_state == 'awaiting_remove_id':
        try:
            product_id = int(text)
            product = Product.query.get(product_id)
            if product and product.user_id == user.id:
                db.session.delete(product)
                db.session.commit()
                send_telegram_message(chat_id, "Product removed successfully. ✅")
            else:
                send_telegram_message(chat_id, "Product not found or not yours. 😕")
            user.telegram_state = None
            user.temp_data = {}
            db.session.commit()
        except ValueError:
            send_telegram_message(chat_id, "Invalid ID. Please send a number. 🚫")

    user.temp_data = temp_data
    db.session.commit()