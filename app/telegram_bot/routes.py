# routes.py
# Flask routes for handling Telegram webhook requests.

from flask import Blueprint, request, current_app, jsonify
from app.tasks import process_telegram_update

# Define the Telegram bot blueprint
bp = Blueprint('telegram_bot', __name__)

# Webhook endpoint for receiving Telegram updates
@bp.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """
    Handles incoming Telegram webhook requests, verifies the secret token,
    and delegates processing to a Celery task for asynchronous handling.
    """
    # Verify the secret token from the request header
    secret_token = current_app.config.get('TELEGRAM_SECRET_TOKEN')
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != secret_token:
        current_app.logger.warning("Invalid secret token received.")
        return "Forbidden", 403

    # Retrieve the update data
    update_data = request.get_json()
    current_app.logger.info(f"Update received, queueing for processing...")

    # Queue the update for processing in Celery and respond immediately
    try:
        process_telegram_update.delay(update_data)
    except Exception as e:
        # Log error if Celery is unavailable, but don't crash the application
        current_app.logger.error(f"Failed to send task to Celery: {e}", exc_info=True)
        # Return 500 to allow Telegram to retry
        return "Internal Server Error", 500

    # Return success response to Telegram
    return jsonify(success=True)