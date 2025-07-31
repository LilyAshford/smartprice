import click
from flask import current_app
from app.extensions import db
from app.models import User, Role, Permission
from werkzeug.security import generate_password_hash
from datetime import datetime

def register_commands(app):
    @app.cli.command("send-test-notification")
    @click.argument("email")
    @click.argument("notification_type", default="price_drop")
    def send_test_notification_command(email, notification_type):
        if notification_type not in ["price_drop", "target_reached"]:
            click.echo("Invalid notification type.")
            return
        from app.tasks import send_test_notification
        send_test_notification.delay(email, notification_type)
        click.echo(f"Queued test notification for {email}. Check Celery worker logs.")

    @app.cli.command("delete-user")
    @click.argument("email")
    def delete_user_command(email):
        user = User.query.filter_by(email=email).first()
        if user:
            db.session.delete(user)
            db.session.commit()
            click.echo(f"User {email} has been deleted.")
        else:
            click.echo(f"User {email} not found.")

    @app.cli.command("create-admin")
    @click.argument("username")
    @click.argument("email")
    @click.argument("password")
    def create_admin(username, email, password):
        """Create or update a user as an administrator."""
        with current_app.app_context():
            # Ensure roles are inserted
            Role.insert_roles()
            admin_role = Role.query.filter_by(name="Administrator").first()
            if not admin_role:
                click.echo("Error: Administrator role not found!")
                return

            user = User.query.filter_by(email=email).first()
            if user:
                # Update existing user
                user.username = username
                user.password = password  # Uses password setter to hash
                user.role_id = admin_role.id
                user.confirmed = True
                user.is_active = True
                user.last_seen = datetime.utcnow()
            else:
                # Create new user
                user = User(
                    username=username,
                    email=email,
                    password=password,  # Uses password setter to hash
                    role_id=admin_role.id,
                    confirmed=True,
                    is_active=True,
                    created_at=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    enable_price_drop_notifications=True,
                    enable_target_price_reached_notifications=True,
                    enable_email_notifications=True
                )
                db.session.add(user)

            db.session.commit()
            click.echo(f"User {username} ({email}) created/updated as Administrator.")

    @app.cli.command("list-users")
    def list_users_command():
        """List all registered users"""
        users = User.query.order_by(User.created_at.desc()).all()
        if not users:
            click.echo("No users found.")
            return

        click.echo("Registered users:")
        for user in users:
            click.echo(
                f"{user.id}: {user.email} ({user.username}) - {'Admin' if user.is_administrator else 'User'} - Created: {user.created_at}")