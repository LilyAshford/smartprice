# __init__.py
# Initializes the products blueprint for the Flask application.

from flask import Blueprint
from .routes import bp

# Register the products blueprint with the Flask app
def init_products(app):
    app.register_blueprint(bp)