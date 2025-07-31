# forms.py
# Defines Flask-WTF forms for product tracking with validation logic.

from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, SelectMultipleField, SelectField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, URL, NumberRange, Length, ValidationError, Email, EqualTo, Optional
from wtforms.widgets import CheckboxInput, ListWidget
from flask_babel import Babel, lazy_gettext as _l
from app.utils.validators import NotificationValidators, ProductValidators

# Custom validator to ensure at least one notification method is selected.
class AtLeastOneChecked:
    def __init__(self, message=None):
        if not message:
            message = _l('You must select at least one notification method')
            self.message = message
    def __call__(self, form, field):
        if not any(field.data):
            raise ValidationError(self.message)

# Form for adding a new product to track.
class ProductForm(FlaskForm):
    product_url = StringField(_l('Product URL'), validators=[
        DataRequired(),
        Length(max=500),
        ProductValidators.validate_product_url
    ])

    product_name = StringField(_l('Product Name (optional)'), validators=[
        Length(max=100)
    ])

    target_price = DecimalField(_l('Target Price ($)'), validators=[
        DataRequired(),
        NumberRange(min=0.01, max=1000000)
    ])

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

    notification_methods = SelectMultipleField(_l('Notification Methods'), choices=[
        ('account', _l('Account notifications')),
        ('email', _l('Email')),
        ('telegram', _l('Telegram'))
    ], validators=[AtLeastOneChecked()],
        option_widget=CheckboxInput(),
        widget=ListWidget(prefix_label=False))

    check_frequency = SelectField(_l('Check Frequency'), choices=[
        ('12', _l('Twice a day (every 12 hours)')),
        ('24', _l('Once a day (every 24 hours)')),
        ('48', _l('Every 2 days')),
        ('168', _l('Once a week'))
    ], validators=[DataRequired()], coerce=int)
    submit = SubmitField(_l('Add Product'))

