from flask_admin.contrib.sqla import ModelView
from flask_admin import AdminIndexView, expose, BaseView
from flask_login import current_user
from flask import redirect, url_for, request, flash
from markupsafe import Markup
from flask_admin.actions import action
from flask_wtf import FlaskForm
from wtforms.widgets import Select as SelectWidget
from app.models import FeedbackCategory, User, Product, Role, Feedback, db, UserNotification, Log, AdminLog
from wtforms.validators import ValidationError
import uuid
from app.tasks import check_price_for_product, send_test_notification
from flask import current_app
from decimal import Decimal
from app.utils.scrapers import extract_product_data, DOMAIN_PARSERS
from wtforms import (StringField, SubmitField, TextAreaField, SelectField, SelectMultipleField, widgets,
                     PasswordField, BooleanField, DecimalField, IntegerField)
from wtforms.validators import DataRequired, Email, URL, Optional, Length
from sqlalchemy import func
from flask_admin.contrib import sqla
from datetime import datetime, timedelta
from flask_babel import _
import logging

admin_logger = logging.getLogger('admin_actions')


class SecuredView:
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_administrator

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('auth.login', next=request.url))


class SecuredModelView(SecuredView, ModelView):
    pass


class SecuredBaseView(SecuredView, BaseView):
    pass


class MyAdminIndexView(SecuredView, AdminIndexView):
    @expose('/')
    def index(self, **kwargs):
        try:
            user_count = db.session.query(func.count(User.id)).scalar()
            product_count = db.session.query(func.count(Product.id)).scalar()
            formatted_date = datetime.utcnow().strftime('%B %d, %Y')
            one_day_ago = datetime.utcnow() - timedelta(days=1)
            notification_count = db.session.query(func.count(UserNotification.id)).filter(
                UserNotification.created_at >= one_day_ago).scalar()
            platform_stats = db.session.query(
                func.substring(Product.url, r'://(?:www\.)?([^/]+)').label('domain'),
                func.count(Product.id).label('count')
            ).group_by('domain').order_by(func.count(Product.id).desc()).all()
            current_app.logger.info(
                f"Rendering admin/index.html with user_count={user_count}, product_count={product_count}")
            return self.render(
                'admin/index.html',
                user_count=user_count,
                product_count=product_count,
                current_date=formatted_date,
                notification_count=notification_count,
                platform_stats=platform_stats,
                unread_feedback_count=0,
                admin_base_template='bootstrap4/admin/base.html'
            )
        except Exception as e:
            current_app.logger.error(f"Error in MyAdminIndexView: {str(e)}")
            return self.render('admin/index.html', error=str(e), admin_base_template='bootstrap4/admin/base.html')


class UserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[Optional(), Length(min=6)])
    role_id = SelectField('Role', coerce=int)
    is_active = SelectField('Active', choices=[(1, 'Yes'), (0, 'No')], coerce=int)
    confirmed = SelectField('Confirmed', choices=[(1, 'Yes'), (0, 'No')], coerce=int)

    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        self.role_id.choices = [(r.id, r.name) for r in Role.query.order_by('name').all()]


class UserAdminView(SecuredModelView):
    form = UserForm
    column_list = ('id', 'username', 'email', 'role', 'is_active', 'confirmed')
    column_searchable_list = ('username', 'email')
    form_columns = ('username', 'email', 'password', 'role_id', 'is_active', 'confirmed')
    column_formatters = {
        'username': lambda v, c, m, p: Markup(f'<a href="/admin/users/details/{m.id}">{m.username}</a>')
    }

    def on_model_change(self, form, model, is_created):
        action = "Created user" if is_created else "Updated user"
        details = (f"User: '{model.username}', Email: '{model.email}', "
                   f"Role: '{Role.query.get(form.role_id.data).name}', Active: {'Yes' if form.is_active.data == 1 else 'No'}")

        admin_logger.info(action, extra={'admin_user': current_user, 'details': details})

        if is_created:
            if not form.password.data:
                raise ValueError("Password is required for new users.")
            model.password = form.password.data
        else:
            if form.password.data:
                model.password = form.password.data

        super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        details = f"Deleted user: '{model.username}' (ID: {model.id})."
        admin_logger.info("Deleted user", extra={'admin_user': current_user, 'details': details})
        super().on_model_delete(model)

    @expose('/details/<int:user_id>')
    def details_view(self, user_id):
        user = User.query.get_or_404(user_id)
        products = Product.query.filter_by(user_id=user.id).all()
        notifications = UserNotification.query.filter_by(user_id=user.id).order_by(
            UserNotification.created_at.desc()).limit(10).all()
        is_admin = user.role.name.lower() == 'admin'

        return self.render('admin/user_details.html',
                           user=user,
                           products=products,
                           notifications=notifications,
                           is_admin=is_admin)


class AdminProductForm(FlaskForm):
    user_id = SelectField('User', coerce=int)
    name = StringField('Name', validators=[DataRequired()])
    url = StringField('URL', validators=[DataRequired(), URL()])
    target_price = DecimalField('Target Price', validators=[DataRequired()])
    check_frequency = IntegerField('Check Frequency (hours)', validators=[DataRequired()])

    notification_methods = StringField('Notification Methods (comma-separated: email, telegram, account)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id.choices = [(u.id, u.username) for u in User.query.order_by('username')]

    def validate_notification_methods(self, field):
        allowed_methods = {'email', 'telegram', 'account'}
        if field.data:
            methods = [method.strip().lower() for method in field.data.split(',')]
            for method in methods:
                if method not in allowed_methods:
                    raise ValidationError(
                        f"Invalid notification method: '{method}'. Allowed values are: email, telegram, account.")


class ProductAdminView(SecuredModelView):
    form = AdminProductForm
    column_list = ('id', 'name', 'user', 'current_price', 'target_price', 'last_checked')
    column_searchable_list = ('name', 'url', 'user.username')
    column_filters = ('user.username', 'last_checked')
    can_view_details = True
    page_size = 20

    form_ajax_refs = {
        'user': {
            'fields': (User.username, User.email),
            'page_size': 10
        }
    }

    form_columns = (
        'name', 'url', 'user', 'target_price',
        'check_frequency', 'notification_methods'
    )

    def on_model_change(self, form, model, is_created):
        action = "Created product" if is_created else "Updated product"
        details = f"Product: '{model.name}', User: '{model.user.username}'"
        admin_logger.info(action, extra={'admin_user': current_user, 'details': details})
        if form.notification_methods.data:
            methods = [method.strip().lower() for method in form.notification_methods.data.split(',')]
            model.notification_methods = methods
        else:
            model.notification_methods = []

        super().on_model_change(form, model, is_created)

    def on_model_delete(self, model):
        details = f"Product: '{model.name}' (ID: {model.id}), User: '{model.user.username}'."
        admin_logger.info("Deleted product", extra={'admin_user': current_user, 'details': details})
        super().on_model_delete(model)


class AdminMessageView(SecuredBaseView):
    @expose('/', methods=['GET', 'POST'])
    def index(self, **kwargs):
        from app.tasks import send_admin_message_task
        form = AdminMessageForm()
        if form.validate_on_submit():
            user = User.query.filter_by(email=form.email.data).first()
            if user:
                details = f"Recipient: {user.username}. Channels: {', '.join(form.channels.data)}. Message: '{form.message.data[:50]}...'"
                admin_logger.info("Sent message to user", extra={'admin_user': current_user, 'details': details})
                for channel in form.channels.data:
                    send_admin_message_task.delay(user.id, channel, form.message.data)
                flash(f"Messages for {user.username} via {', '.join(form.channels.data)} have been queued.", 'success')
            else:
                flash(f"User with email {form.email.data} not found.", 'error')
        return self.render('admin/send_message.html', form=form)


class AdminLogView(SecuredModelView):
    can_create = False
    can_edit = False
    can_delete = True

    column_list = ('timestamp', 'admin_username', 'action', 'details')
    column_searchable_list = ('admin_username', 'action', 'details')
    column_filters = ('admin_username', 'action', 'timestamp')
    column_default_sort = ('timestamp', True)
    page_size = 50

    @action('delete_all', 'Clear All Action Logs', 'Are you sure you want to delete all action logs?')
    def delete_all(self, ids):
        try:
            num_deleted = self.model.query.delete()
            self.session.commit()
            flash(f'All {num_deleted} admin action logs have been deleted.', 'success')
            admin_logger.info("Cleared all admin action logs", extra={'admin_user': current_user})
        except Exception as e:
            self.session.rollback()
            flash(f'Failed to delete logs: {str(e)}', 'error')


class LogAdminView(SecuredModelView):
    can_create = False
    can_edit = False
    can_delete = True
    column_list = ('timestamp', 'level', 'module', 'func_name', 'message')
    column_searchable_list = ('message', 'module', 'func_name', 'level')
    column_filters = ('level', 'module', 'timestamp')
    column_default_sort = ('timestamp', True)
    page_size = 50

    @action('delete_all', 'Delete All Logs', 'Are you sure you want to delete all logs?')
    def delete_all(self, ids):
        try:
            Log.query.delete()
            db.session.commit()
            flash('All logs have been deleted.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to delete logs: {str(e)}', 'error')
            current_app.logger.error(f"Error deleting logs: {str(e)}")


class TestingForm(FlaskForm):
    email = StringField('User Email for Test Notification', validators=[Optional(), Email()],
                        default='lillianashford70@gmail.com')
    submit_test_notification = SubmitField('Send Test Notification')

    product_id = StringField('Product ID for Price Check', validators=[Optional()])
    submit_price_check = SubmitField('Run Real Price Check')

    mock_scenario = SelectField('Mock Scenario', choices=[
        ('price-drop', 'Simulate Price Drop'),
        ('target-reached', 'Simulate Target Reached'),
        ('price-increase', 'Simulate Price Increase'),
        ('no-change', 'Simulate No Change')
    ])
    mock_target_price = DecimalField('Mock Target Price', default=Decimal('100.00'))
    mock_current_price = DecimalField('Mock Current Price', default=Decimal('120.00'))
    submit_mock_check = SubmitField('Run Mock Price Check')

    def validate(self):
        if not super().validate():
            return False

        # Check product_id only when a price check (real or mock) is submitted
        if (self.submit_price_check.data or self.submit_mock_check.data) and not self.product_id.data:
            self.product_id.errors.append('Product ID is required for a price check.')
            return False

        if self.product_id.data:
            try:
                product_id = int(self.product_id.data)
                if not Product.query.get(product_id):
                    self.product_id.errors.append('Product ID does not exist.')
                    return False
            except (ValueError, TypeError):
                self.product_id.errors.append('Product ID must be a valid integer.')
                return False
        return True


class TestingView(SecuredBaseView):
    @expose('/', methods=['GET', 'POST'])
    def index(self):
        form = TestingForm(request.form)

        if request.method == 'POST' and form.validate():
            # A. Test Notification
            if form.submit_test_notification.data:
                if form.email.data:
                    user = User.query.filter_by(email=form.email.data).first()
                    if user:
                        send_test_notification.delay(user.email)
                        flash(f"Test notification task queued for user {user.username}.", "success")
                    else:
                        flash("User not found.", "error")
                else:
                    flash("User Email is required to send a notification.", "warning")
                return redirect(url_for('testing.index'))

            # B. Real Price Check
            if form.submit_price_check.data:
                if form.product_id.data:
                    check_price_for_product.delay(int(form.product_id.data))
                    flash(f"Real price check task queued for product ID {form.product_id.data}.", "info")
                else:
                    flash('Product ID is required for a real price check.', 'warning')
                return redirect(url_for('testing.index'))

            # C. Mock Price Check
            if form.submit_mock_check.data:
                if form.product_id.data:
                    product = Product.query.get(int(form.product_id.data))
                    if product:
                        locale = product.user.language if product.user.language else 'en'
                        check_price_for_product.delay(
                            product_id=int(form.product_id.data),
                            mock_scenario=form.mock_scenario.data,
                            mock_target_price=str(form.mock_target_price.data),
                            mock_current_price=str(form.mock_current_price.data),
                            locale=locale
                        )
                        flash(f"Mock price check task queued for product ID {form.product_id.data}.", "info")
                    else:
                        flash('Product not found.', 'error')
                else:
                    flash('Product ID is required for a mock price check.', 'warning')
                return redirect(url_for('testing.index'))

        return self.render('admin/testing.html', form=form)


class ParserStatusForm(FlaskForm):
    url = StringField('Product URL', validators=[DataRequired(), URL()])
    submit = SubmitField('Test Parser')


class ParserStatusView(SecuredView, BaseView):
    @expose('/', methods=['GET', 'POST'])
    def index(self, **kwargs):
        form = ParserStatusForm()
        result_data = None
        if form.validate_on_submit():
            url_to_test = form.url.data
            flash(f"Started parsing URL: {url_to_test}", 'info')
            result_data_raw = extract_product_data(url_to_test)

            if isinstance(result_data_raw, tuple) and len(result_data_raw) == 2:
                data, has_error = result_data_raw
                result_data = {**data, 'success': not has_error}
            elif isinstance(result_data_raw, dict):
                result_data = result_data_raw
            else:
                result_data = {'success': False, 'error': 'Unexpected parser output', 'details': str(result_data_raw)}
        elif request.method == 'POST':
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f"Error in '{getattr(form, field).label.text}': {error}", 'error')
        available_parsers = list(DOMAIN_PARSERS.keys())
        return self.render(
            'admin/parser_status.html',
            form=form,
            available_parsers=available_parsers,
            result_data=result_data
        )


class AdminMessageForm(FlaskForm):
    email = StringField('User Email', validators=[DataRequired(), Email()])
    channels = SelectMultipleField(
        'Channels',
        choices=[('email', 'Email'), ('telegram', 'Telegram'), ('account', 'Account Notification')],
        widget=widgets.ListWidget(prefix_label=False),
        option_widget=widgets.CheckboxInput()
    )
    message = TextAreaField('Message', validators=[DataRequired()])
    submit = SubmitField('Send Message')


class FeedbackForm(FlaskForm):
    user = SelectField('User', coerce=int, validators=[DataRequired()], widget=SelectWidget())
    category = SelectField('Category', choices=[(e.value, e.name) for e in FeedbackCategory],
                           validators=[DataRequired()], widget=SelectWidget())
    message = TextAreaField('Message', validators=[DataRequired()])
    page_url = StringField('Page URL', validators=[Optional()])

    def __init__(self, *args, **kwargs):
        super(FeedbackForm, self).__init__(*args, **kwargs)
        self.user.choices = [(u.id, u.username) for u in User.query.order_by(User.username).all()]


class FeedbackAdminView(SecuredModelView):
    form = FeedbackForm
    can_create = False
    can_edit = False
    can_delete = True
    can_view_details = True

    column_list = ('user', 'subject', 'message', 'timestamp')
    column_default_sort = ('timestamp', True)
    list_template = 'admin/feedback.html'

    @action('delete_all', 'Delete All Feedback', 'Are you sure you want to delete all feedback?')
    def delete_all(self, ids):
        try:
            Feedback.query.delete()
            db.session.commit()
            flash('All feedback have been deleted.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to delete feedback: {str(e)}', 'error')
            current_app.logger.error(f"Error deleting feedback: {str(e)}")

    def on_model_change(self, form, model, is_created):
        from app.models import User
        model.user = User.query.get(form.user.data)
        model.category = form.category.data
        model.message = form.message.data
        model.is_read = form.is_read.data
        model.page_url = form.page_url.data
        super().on_model_change(form, model, is_created)

    def _get_list_template_args(self, view_args):
        args = super()._get_list_template_args(view_args)
        unread_ids = [item.id for item in args['data'] if not item.is_read]
        if unread_ids:
            try:
                self.model.query.filter(self.model.id.in_(unread_ids)).update({'is_read': True},
                                                                              synchronize_session=False)
                self.session.commit()
            except Exception as e:
                self.session.rollback()
                current_app.logger.error(f"Failed to auto-mark feedback as read: {e}")
        return args
