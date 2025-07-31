from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, SelectField, BooleanField, DecimalField, SelectMultipleField, HiddenField
from wtforms.validators import DataRequired, Length, Email, Regexp, ValidationError, Optional, NumberRange
from wtforms.widgets import CheckboxInput, ListWidget
from app.products.forms import AtLeastOneChecked
from flask_babel import lazy_gettext as _l
from wtforms import TextAreaField
from app.models import User, FeedbackCategory
import re

class UpdateUsernameForm(FlaskForm):
    username = StringField(_l('Username'),
                           validators=[
                               DataRequired(),
                               Length(3, 20, message=_l("Username must be between 3 and 20 characters.")),
                               Regexp(
                                   "^[A-Za-z][A-Za-z0-9_.]*$",
                                   0,
                                   _l("Usernames must start with a letter and have only letters, numbers, dots or underscores"),
                               )
                           ])
    submit_username = SubmitField(_l('Update Username'))

    def __init__(self, original_username, *args, **kwargs):
        super(UpdateUsernameForm, self).__init__(*args, **kwargs)
        self.original_username = original_username

    def validate_username(self, field):
        if field.data != self.original_username and \
           User.query.filter_by(username=field.data).first():
            raise ValidationError(_l('This username is already taken.'))

class NotificationSettingsForm(FlaskForm):
    enable_price_drop_notifications = BooleanField(_l('Enable Price Drop Notifications'))
    enable_target_price_reached_notifications = BooleanField(_l('Enable Target Price Reached Notifications'))
    enable_email_notifications = BooleanField(_l('Enable Email Notifications'))
    submit_notifications = SubmitField(_l('Save Notification Settings'))

class TelegramSetupForm(FlaskForm):
    telegram_chat_id = StringField(_l('Your Telegram Chat ID'), validators=[
        # DataRequired()
        Optional(),
        Length(max=50),
        Regexp(r'^-?\d+$', message=_l('Chat ID must be a number (can be negative for groups).') )
    ])
    submit_telegram = SubmitField(_l('Save Telegram Chat ID'))

    def validate_telegram_chat_id(self, field):
        if field.data and not field.data.strip():
            field.data = None
            return
        if field.data and not re.match(r'^-?\d+$', field.data):
            raise ValidationError(_l('Chat ID must be a number (can be negative for groups).'))


class ChangeDisplayLanguageForm(FlaskForm):
    language = SelectField(_l('Interface Display Language'), choices=[
        ('en', _l('English')),
        ('ru', _l('Russian')),
        ('es', _l('Spanish')),
        ('zh', _l('Chinese'))
    ], validators=[DataRequired()])
    submit_language = SubmitField(_l('Change Interface Language'))


class FeedbackForm(FlaskForm):
    category = SelectField(
        _l('Category'),
        choices=[(cat.value, str(cat)) for cat in FeedbackCategory],
        validators=[DataRequired()]
    )
    message = TextAreaField(
        _l('Your Message'),
        validators=[DataRequired(), Length(min=10, max=4000)],
        render_kw={'rows': 5}
    )
    page_url = HiddenField()
    submit_feedback = SubmitField(_l('Send Feedback'))


class EditProductForm(FlaskForm):
    product_name = StringField(_l('Product Name'), validators=[DataRequired(), Length(max=255)])
    target_price = DecimalField(_l('Target Price'), validators=[DataRequired(), NumberRange(min=0.01)])
    price_drop_alert_threshold = DecimalField(
        _l('Also, notify if price just drops by ($)'),
        description=_l(
            "For example, enter 5 to get a notification for any price drop of $5 or more. Leave it blank to get a notification for any, even the slightest, drop."),
        validators=[Optional(), NumberRange(min=0.01)]
    )
    price_increase_alert_threshold = DecimalField(
        _l('And notify if price increases by ($)'),
        description=_l(
            "Useful if you want to know when the price has returned to its previous level. Leave blank to not receive notifications about increases."),
        validators=[Optional(), NumberRange(min=0.01)]
    )
    notification_methods = SelectMultipleField(
        _l('Notification Methods'),
        choices=[
            ('email', 'Email'),
            ('telegram', 'Telegram'),
            ('account', 'Account')
        ],
        widget=ListWidget(prefix_label=False),
        option_widget=CheckboxInput(),
        validators=[AtLeastOneChecked()]
    )
    check_frequency = SelectField(_l('Check Frequency'), choices=[
        ('12', _l('Twice a day (every 12 hours)')),
        ('24', _l('Once a day (every 24 hours)')),
        ('48', _l('Every 2 days')),
        ('168', _l('Once a week'))
    ], validators=[DataRequired()], coerce=int)

    submit = SubmitField(_l('Update Product'))