import click
import requests
from flask import current_app
import uuid


def register_commands(app):
    @app.cli.group()
    def telegram():
        """Telegram bot commands"""
        pass

    @telegram.command()
    def set_webhook():
        """Sets the Telegram webhook with a secret token."""
        WEBHOOK_HOST = current_app.config.get('SERVER_NAME')

        token = current_app.config.get('TELEGRAM_BOT_TOKEN')
        secret_token = current_app.config.get('TELEGRAM_SECRET_TOKEN', str(uuid.uuid4()))

        webhook_url = f"https://{WEBHOOK_HOST}/telegram/webhook"
        telegram_api_url = f"https://api.telegram.org/bot{token}/setWebhook"

        try:
            response = requests.post(
                telegram_api_url,
                data={'url': webhook_url, 'secret_token': secret_token}
            )
            response.raise_for_status()
            result = response.json()
            if result.get('ok'):
                print(f"✅ Webhook set successfully to: {webhook_url}")
                print(f"🔒 Your secret token: {secret_token}")
            else:
                print(f"❌ Failed to set webhook. Error: {result.get('description')}")
        except requests.RequestException as e:
            print(f"Error connecting to Telegram API: {e}")
