# routes.py
# This module defines Flask routes for authentication-related functionality,
# including login, registration, password reset, and email change.

import time
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, current_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from flask_babel import Babel, _, lazy_gettext as _l
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime
import uuid
from sqlalchemy.exc import (
    IntegrityError,
    DataError,
    DatabaseError,
    InterfaceError,
    InvalidRequestError
)
from werkzeug.routing import BuildError

from app.extensions import db, mail, limiter
import posthog
from app.models import User, Role
from markupsafe import Markup
from app.auth.forms import (LoginForm,
                            RegistrationForm,
                            PasswordResetRequestForm,
                            PasswordResetForm,
                            ResendVerificationForm,
                            ChangePasswordForm,
                            ChangeEmailForm,
                            EmailForm)
from app.mail_services import send_email, send_verification_email, send_welcome_email

# Initialize the auth blueprint
bp = Blueprint('auth', __name__)

@bp.before_app_request
def before_request():
    """
    Ensures that unconfirmed users are redirected to the unconfirmed page
    before accessing protected routes.
    """
    if current_user.is_authenticated:
        current_user.ping()
        if not current_user.confirmed \
                and request.endpoint \
                and request.blueprint != 'auth' \
                and request.endpoint != 'static':
            return redirect(url_for('auth.unconfirmed'))

@bp.route('/unconfirmed')
def unconfirmed():
    """
    Displays the unconfirmed account page for users who have not verified their email.

    Returns:
        Response: Rendered template for unconfirmed users.
    """
    if current_user.is_anonymous or current_user.confirmed:
        return redirect(url_for('main.index'))
    return render_template('auth/unconfirmed.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user login with email or username and password.

    Returns:
        Response: Rendered login template or redirect to the appropriate page after successful login.
    """
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))

    form = LoginForm()
    if form.validate_on_submit():
        if '@' in form.email_or_username.data:
            user = User.query.filter_by(email=form.email_or_username.data.lower()).first()
        else:
            user = User.query.filter_by(username=form.email_or_username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            if not user.confirmed:
                resend_url = url_for('auth.resend_confirmation_request')
                flash(Markup(
                    _('Your account has not been confirmed. Please check your email or <a href="%(url)s" class="alert-link">resend the confirmation link</a>.',
                      url=resend_url)), 'warning')
                return redirect(url_for('auth.login'))
            if not user.is_active:
                flash(_('Your account is disabled'), 'error')
                return redirect(url_for('auth.login'))
            login_user(user, remember=form.remember.data)
            try:
                posthog.capture(str(user.id), 'user_logged_in')
                current_app.logger.info("PostHog event 'user_logged_in' captured")
                from datetime import datetime, timedelta
                if user.created_at < datetime.utcnow() - timedelta(days=7):
                    posthog.capture(str(user.id), 'user_active_after_7_days')
                    current_app.logger.info("PostHog event 'user_active_after_7_days' captured")
            except Exception as e:
                current_app.logger.error(f"PostHog error: {str(e)}")
            next_page = request.args.get('next')
            current_app.logger.info(f"User logged in: {user.email}")
            if user.is_administrator:
                return redirect(url_for('admin.index'))
            next_page = request.args.get('next')
            return redirect(next_page or url_for('profile.index'))
        else:
            current_app.logger.warning(f"Failed login attempt for: {form.email_or_username.data}")
            flash(_('Invalid email or password'), 'error')
    return render_template('auth/login.html', form=form, title=_('Login'))

@bp.route('/register', methods=['POST', 'GET'])
@limiter.limit("10 per hour")
def register():
    """
    Handles user registration, creating a new user account and sending a verification email.

    Returns:
        Response: Rendered registration template or redirect to login page after successful registration.
    """
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            existing_user = db.session.query(User).filter_by(email=form.email.data.lower()).first()
            if existing_user:
                db.session.rollback()
                flash(_('Email already registered'), 'error')
                return redirect(url_for('auth.register'))
            hashed_password = generate_password_hash(form.password.data)
            user_role = Role.query.filter_by(name='User').first()
            if not user_role:
                user_role = Role(name='User')
                db.session.add(user_role)
            user = User(
                email=form.email.data.lower(),
                password_hash=hashed_password,
                username=form.username.data,
                role=user_role,
                is_active=False,
            )
            db.session.add(user)
            db.session.commit()
            token = user.generate_confirmation_token()
            send_verification_email(user, token)
            current_app.logger.info(f"New user registered: {user.email}")
            posthog.capture(user.id, 'user_registered', {'email': user.email})
            flash(
                _('Registration successful! A confirmation email has been sent to you. Please check your inbox (and spam folder!) to activate your account.'),
                'info')
            flash(_('Emails can sometimes take a few minutes to arrive. Please be patient.'), 'info')
            return redirect(url_for('auth.login'))

        except InvalidRequestError:
            db.session.rollback()
            flash(_("Something went wrong!"), "error")

        except IntegrityError:
            db.session.rollback()
            flash(_("User already exists!."), "error")

        except DataError:
            db.session.rollback()
            flash(_("Invalid Entry"), "error")

        except InterfaceError:
            db.session.rollback()
            flash(_("Error connecting to the database"), "error")

        except DatabaseError:
            db.session.rollback()
            flash(_("Error connecting to the database"), "error")

        except BuildError:
            db.session.rollback()
            flash(_("An error occurred!"), "error")

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Registration failed: {str(e)}")
            flash(_('Registration failed. Please try again.'), 'error')
    return render_template('auth/register.html', form=form, title=_('Register'))

@bp.route('/resend-confirmation', methods=['GET', 'POST'])
@limiter.limit("3 per minute")
def resend_confirmation_request():
    """
    Allows users to resend a confirmation email for account verification.

    Returns:
        Response: Rendered template or redirect to login page after sending the email.
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = EmailForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            if user.confirmed:
                flash(_('This account is already confirmed. Please log in.'), 'info')
                return redirect(url_for('auth.login'))
            token = user.generate_confirmation_token()
            send_verification_email(user, token)
            flash(_('A new confirmation email has been sent to your email address.'), 'success')
            flash(_('Emails can sometimes take a few minutes to arrive. Please be patient.'), 'info')
            return redirect(url_for('auth.login'))
        else:
            flash(_('No account found with that email address.'), 'warning')
    return render_template('auth/resend_confirmation_request.html', form=form, title=_('Resend Confirmation Email'))

@bp.route('/confirm/<token>')
def confirm(token):
    """
    Confirms a user's account using a verification token.

    Args:
        token (str): The confirmation token sent via email.

    Returns:
        Response: Redirect to appropriate page based on confirmation status.
    """
    logout_user()

    if current_user.is_authenticated and current_user.confirmed:
        flash(_('Your account is already confirmed.'), 'info')
        return redirect(url_for('profile.index'))

    user_to_confirm = User.verify_confirmation_token_and_get_user(token)

    if not user_to_confirm:
        flash(_('The confirmation link is invalid or has expired.'), 'error')
        return render_template('auth/confirmation_invalid.html', title=_('Confirmation Failed'))

    if user_to_confirm.confirmed and user_to_confirm.is_active:
        flash(_('This account is already confirmed. Please log in.'), 'info')
        return redirect(url_for('auth.login'))

    if user_to_confirm.confirm(token):
        try:
            send_welcome_email(current_user)
            posthog.capture(user_to_confirm.id, 'account_confirmed')
            flash(_('You have confirmed your account. A welcome email has been sent. Thanks!'), 'success')
        except Exception as e:
            current_app.logger.error(f"Failed to send welcome email to {user_to_confirm.email}: {e}")
            flash(_('You have confirmed your account. Thanks! You can now log in.'), 'success')
        login_user(user_to_confirm)
        return redirect(url_for('profile.index'))
    else:
        flash(_('Failed to confirm your account. The link might be invalid or an error occurred.'), 'error')
        return render_template('auth/confirmation_invalid.html', title=_('Confirmation Failed'))

@bp.route('/confirm')
def resend_confirmation():
    """
    Resends a confirmation email to the current user.

    Returns:
        Response: Redirect to the main index page after sending the email.
    """
    token = current_user.generate_confirmation_token()
    send_verification_email(current_user, token)
    flash(_('A new confirmation email has been sent. Please check your inbox and spam folder.'), 'info')
    flash(_('Emails can sometimes take a few minutes to arrive. Please be patient.'), 'info')
    return redirect(url_for('main.index'))

@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """
    Allows the current user to change their password.

    Returns:
        Response: Rendered template or redirect to profile page after successful password change.
    """
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if current_user.verify_password(form.old_password.data):
            current_user.password = form.password.data
            db.session.add(current_user)
            db.session.commit()
            flash(_('Your password has been updated.'))
            return redirect(url_for('profile.index'))
        else:
            flash(_('Invalid password.'))
    return render_template("auth/change_password.html", form=form)

@bp.route('/logout')
@login_required
def logout():
    """
    Logs out the current user.

    Returns:
        Response: Redirect to the main index page after logout.
    """
    current_app.logger.info(f"User logged out: {current_user.email}")
    logout_user()
    flash(_('You have been logged out.'), 'info')
    return redirect(url_for('main.index'))

@bp.route('/reset_password_request', methods=['POST', 'GET'])
@limiter.limit("5 per hour")
def reset_password_request():
    """
    Handles password reset requests by sending a reset email to the user.

    Returns:
        Response: Rendered template or redirect to login page after sending the email.
    """
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))

    form = PasswordResetRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            try:
                token = user.generate_reset_token()
                expiry_hours = current_app.config['PASSWORD_RESET_EXPIRATION'] // 3600
                send_email(user.email, 'Reset Your Password',
                           'auth/email/reset_password',
                           user=user, token=token, expiry_hours=expiry_hours)
                flash(_('An email with instructions to reset your password has been sent. Please check your inbox and spam folder.'), 'info')
                flash(_('Emails can sometimes take a few minutes to arrive. Please be patient.'), 'info')
            except Exception as e:
                flash(_('Error sending email. Please try again later.'), 'error')
                current_app.logger.error(f"Password reset email failed for {form.email.data}: {str(e)}")
                return redirect(url_for('auth.login'))
        else:
            current_app.logger.info(f"Password reset requested for non-existent email: {form.email.data}")
            flash(_('If this email exists in our system, you will receive a password reset link'), 'info')
            return render_template('auth/reset_password_request.html', form=form, title=_('Reset Password'))
    return render_template('auth/reset_password_request.html', form=form, title=_('Reset Password'))

@bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """
    Handles password reset using a reset token.

    Args:
        token (str): The password reset token sent via email.

    Returns:
        Response: Rendered template or redirect to appropriate page based on reset status.
    """
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))
    form = PasswordResetForm()

    user = User.verify_password_reset_token(token)
    if not user:
        flash(_('This password reset link is invalid or has expired. Please request a new one.'), 'danger')
        return redirect(url_for('auth.reset_password_request'))

    if form.validate_on_submit():
        if user.reset_password(token, form.password.data):
            db.session.commit()
            flash(_('Your password has been updated! You can now log in.'), 'success')
            return redirect(url_for('auth.login'))
        else:
            flash(_('An unexpected error occurred. Please try again.'), 'danger')
            return redirect(url_for('auth.reset_password_request'))

    return render_template('auth/reset_password.html', title=_('Reset Password'), form=form)

@bp.route('/change_email', methods=['GET', 'POST'])
@login_required
def change_email_request():
    """
    Allows the current user to request an email address change.

    Returns:
        Response: Rendered template or redirect to profile page after sending the confirmation email.
    """
    form = ChangeEmailForm()
    if form.validate_on_submit():
        if current_user.verify_password(form.password.data):
            new_email = form.email.data.lower()
            token = current_user.generate_email_change_token(new_email)
            send_email(new_email, _('Confirm your email address'),
                       'email/change_email',
                       user=current_user, token=token)
            flash(_('An email with instructions to confirm your new email address has been sent to you'), 'info')
            flash(_('Emails can sometimes take a few minutes to arrive. Please be patient.'), 'info')
            return redirect(url_for('profile.index'))
        else:
            flash(_('Invalid email or password.'))
    return render_template("auth/change_email.html", form=form)

@bp.route('/change_email/<token>')
@login_required
def change_email(token):
    """
    Confirms a user's new email address using a token.

    Args:
        token (str): The email change token sent via email.

    Returns:
        Response: Redirect to profile page after successful email change.
    """
    if current_user.change_email(token):
        db.session.commit()
        current_app.logger.info(f"Email reset for user: {current_user.email}")
        flash(_('Your email address has been updated! Please log in with your new email.'), 'success')
        return redirect(url_for('profile.index'))
    else:
        flash(_('Invalid request. Please try again'))
        redirect(url_for('auth.change_email_request'))
    return redirect(url_for('profile.index'))

@bp.route('/google-login')
def google_login():
    """
    Placeholder for Google OAuth login implementation.

    Returns:
        Response: Temporary redirect to registration page.
    """
    # Here will be the implementation of OAuth with Google
    # Temporary redirect to regular registration
    return redirect(url_for('auth.register'))
