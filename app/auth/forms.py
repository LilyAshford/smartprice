# forms.py
# This module defines Flask-WTF forms for user authentication and registration,
# including validation rules for input fields.

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, ValidationError, Email, EqualTo, Regexp
from app.models import User
from flask_babel import Babel, lazy_gettext as _l
import re
from app.utils.validators import NotificationValidators, UserValidators

class LoginForm(FlaskForm):
    """
    Form for user login with email or username and password.
    """
    email_or_username = StringField(_l('Email or Username'), validators=[
        DataRequired()
    ])
    password = PasswordField(_l('Password'), validators=[
        DataRequired()
    ])
    remember = BooleanField(_l('Remember Me'))
    submit = SubmitField(_l('Sign In'))

class EmailForm(FlaskForm):
    """
    Form for submitting an email address, used for resending confirmation emails.
    """
    email = StringField(_l('Email'), validators=[DataRequired(), Email()])
    submit = SubmitField(_l('Send'))

class RegistrationForm(FlaskForm):
    """
    Form for user registration with username, email, and password fields.
    """
    username = StringField(_l('Username'),
        validators=[
            DataRequired(),
            Length(3, 20, message="Please provide a valid name"),
            Regexp(
                r'^[^\W_][\w\-. ]*$',
                flags=re.UNICODE,
                message=_l("Username may contain international characters, numbers, dots, underscores and hyphens")
            ),
            UserValidators.validate_username
        ]
    )
    email = StringField(_l('Email'), validators=[
        DataRequired(),
        Email(),
        UserValidators.validate_email
    ])
    password = PasswordField(_l('Password'), validators=[
        DataRequired(),
        Length(min=8, message=_l('Password must be at least 8 characters')),
        UserValidators.validate_password_strength
    ])
    password2 = PasswordField(_l('Repeat Password'), validators=[
        DataRequired(),
        EqualTo('password', message=_l('Passwords must match'))
    ])
    submit = SubmitField(_l('Register'))

class PasswordResetRequestForm(FlaskForm):
    """
    Form for requesting a password reset via email.
    """
    email = StringField(_l('Email'), validators=[
        DataRequired(),
        Email()
    ])
    submit = SubmitField(_l('Request Password Reset'))

class PasswordResetForm(FlaskForm):
    """
    Form for resetting a user's password.
    """
    password = PasswordField(_l('New Password'), validators=[
        DataRequired(),
        Length(min=8, message=_l('Password must be at least 8 characters')),
        UserValidators.validate_password_strength
    ])
    password2 = PasswordField(_l('Repeat Password'), validators=[
        DataRequired(),
        EqualTo('password', message=_l('Passwords must match'))
    ])
    submit = SubmitField(_l('Reset Password'))

class ResendVerificationForm(FlaskForm):
    """
    Form for resending a verification email.
    """
    submit = SubmitField(_l('Resend Verification Email'))

class ChangePasswordForm(FlaskForm):
    """
    Form for changing a user's password.
    """
    old_password = PasswordField('Old password', validators=[DataRequired()])
    password = PasswordField('New password', validators=[
        DataRequired(), EqualTo('password2', message='Passwords must match.')])
    password2 = PasswordField('Confirm new password',
                              validators=[DataRequired()])
    submit = SubmitField('Update Password')

class ChangeEmailForm(FlaskForm):
    """
    Form for changing a user's email address.

    Methods:
        validate_email: Custom validator to check if the new email is already registered.
    """
    email = StringField('New Email', validators=[DataRequired(), Length(1, 64),
                                                 Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Update Email Address')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data.lower()).first():
            raise ValidationError('Email already registered.')


