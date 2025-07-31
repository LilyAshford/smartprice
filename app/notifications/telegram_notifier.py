import requests
from flask import current_app
import json


def send_telegram_message(chat_id: str, message: str, parse_mode: str = None, reply_markup=None):
    """
    Send a message to a Telegram chat.
    Args:
        chat_id (str): The Telegram chat ID.
        message (str): The message to send.
        parse_mode (str, optional): Parse mode for the message (e.g., 'MarkdownV2').
        reply_markup (dict, optional): Inline keyboard or other reply markup.
    """
    current_app.logger.info(f"Attempting to send message to chat_id: {chat_id}")
    token = current_app.config.get('TELEGRAM_BOT_TOKEN')
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            current_app.logger.info(f"SUCCESS: Telegram message sent to chat_id {chat_id}")
        else:
            error_code = response.json().get('error_code')
            error_description = response.json().get('description')
            current_app.logger.error(
                f"FAILURE: Telegram API returned an error for chat_id {chat_id}. Code: {error_code}, Description: '{error_description}'")
    except Exception as e:
        current_app.logger.error(f"Error sending Telegram message to chat_id {chat_id}: {str(e)}")


def send_telegram_price_alert(user, product, old_price, new_price, alert_type="target_reached"):
    app = current_app._get_current_object()
    if not user.telegram_chat_id:
        app.logger.info(f"No Telegram Chat ID for user {user.id}. Skipping price alert.")
        return False

    product_name_safe = escape_markdown_v2(product.name)
    message_text = ""

    if alert_type == "target_reached":
        price = escape_markdown_v2(f"{new_price}$")
        target = escape_markdown_v2(f"{product.target_price}$")
        message_text = (
            f"🎯 *Target Price Reached\\!*\n\n"
            f"Product: *{product_name_safe}*\n"
            f"New Price: *{price}* \\(Target: {target}\\)\n\n"
            f"[View Product]({product.url})"
        )
    elif alert_type == "price_drop":
        price = escape_markdown_v2(f"{new_price}$")
        old = escape_markdown_v2(f"{old_price}$")
        message_text = (
            f"📉 *Price Drop\\!*\n\n"
            f"Product: *{product_name_safe}*\n"
            f"New Price: *{price}* \\(was {old}\\)\n\n"
            f"[View Product]({product.url})"
        )

    if message_text:
        return send_telegram_message(user.telegram_chat_id, message_text, parse_mode='MarkdownV2')
    return False


def create_inline_keyboard(buttons):
    """
    Create an inline keyboard for Telegram.
    Args:
        buttons (list): List of lists, where each inner list contains dicts with 'text' and 'callback_data'.
    Returns:
        dict: Telegram-compatible inline keyboard structure.
    """
    return {'inline_keyboard': buttons}


def escape_markdown_v2(text):
    """
    Escape special characters for Telegram MarkdownV2.
    Args:
        text (str): Text to escape.
    Returns:
        str: Escaped text.
    """
    special_chars = r'_[]()~`>#+-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text