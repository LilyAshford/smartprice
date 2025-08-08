from flask import render_template, redirect, url_for, flash, request, current_app, session, jsonify
from flask_login import login_required, current_user
from app.profile import bp
from .forms import EditProductForm
from app.extensions import limiter
from app.models import UserNotification
from app import db
import posthog
from app.models import User, Permission, Feedback, FeedbackCategory, Product, PriceHistory
from app.profile.forms import (
    UpdateUsernameForm,
    NotificationSettingsForm,
    TelegramSetupForm,
    ChangeDisplayLanguageForm,
    FeedbackForm
)
from app.products.services import get_user_products, delete_product, get_product_by_id
from flask_babel import _
from sqlalchemy.exc import IntegrityError # DataError, InterfaceError, DatabaseError
from app.mail_services import send_verification_email, send_admin_feedback_notification
from sqlalchemy import desc


@bp.before_request
@login_required
def before_request():
    if not current_user.confirmed:
        flash(_('Please confirm your account to access full profile features.'), 'warning')
        return redirect(url_for('auth.unconfirmed'))



@bp.route('/')
@login_required
def index():
    user_products = get_user_products(current_user.id)
    total_products = len(user_products)

    products_with_price_drop = 0
    if user_products:
        products_with_price_drop = sum(
            1 for p in user_products
            if p.current_price is not None and p.target_price is not None and p.current_price < p.target_price
        )

    return render_template(
        'profile/index.html',
        title=_('Your Profile'),
        user_products=user_products,
        total_products=total_products,
        products_with_price_drop=products_with_price_drop
    )


@bp.route('/products')
@login_required
def tracked_products():
    user_products = get_user_products(current_user.id)
    return render_template('profile/tracked_products.html', title=_('My Tracked Products'), products=user_products)

@bp.route('/product/<int:product_id>/delete', methods=['POST'])
@login_required
def delete_tracked_product(product_id):
    product = Product.query.get_or_404(product_id)

    if product is None:
        flash(_('Product not found.'), 'error')
        return redirect(url_for('profile.tracked_products'))

    if product.user_id != current_user.id:
        from flask import abort
        abort(403)

    try:
        if delete_product(product_id):
            posthog.capture(current_user.id, 'product_removed', {'product_id': product_id})
            flash(_('Product "%(name)s" has been successfully deleted.', name=product.name), 'success')
        else:
            flash(_('Failed to delete product.'), 'error')
    except Exception as e:
        current_app.logger.error(f"Error deleting product {product_id}: {e}")
        flash(_('Could not remove the product.'), 'error')

    return redirect(url_for('profile.tracked_products'))


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    username_form = UpdateUsernameForm(original_username=current_user.username, prefix="username_form")
    notification_form = NotificationSettingsForm(prefix="notification_form")
    language_form = ChangeDisplayLanguageForm(prefix="language_form")

    if username_form.submit_username.data and username_form.validate_on_submit():
        if username_form.username.data != current_user.username:
            current_user.username = username_form.username.data
            try:
                db.session.add(current_user)
                db.session.commit()
                flash(_('Your username has been updated!'), 'success')
            except IntegrityError:
                db.session.rollback()
                flash(_('This username is already taken. Please choose another.'), 'error')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error updating username for user {current_user.id}: {str(e)}")
                flash(_('An error occurred while updating your username.'), 'error')
        else:
            flash(_('Username is the same, no changes made.'), 'info')
        return redirect(url_for('profile.settings'))

    if notification_form.submit_notifications.data and notification_form.validate_on_submit():
        current_user.enable_price_drop_notifications = notification_form.enable_price_drop_notifications.data
        current_user.enable_target_price_reached_notifications = notification_form.enable_target_price_reached_notifications.data
        current_user.enable_email_notifications = notification_form.enable_email_notifications.data

        try:
            db.session.add(current_user)
            db.session.commit()
            flash(_('Notification settings saved!'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error saving notification settings for user {current_user.id}: {str(e)}")
            flash(_('An error occurred while saving notification settings.'), 'error')
        return redirect(url_for('profile.settings'))

    if language_form.submit_language.data and language_form.validate_on_submit():
        new_lang = language_form.language.data
        if new_lang in current_app.config.get('LANGUAGES', ['en']):
            session['lang'] = new_lang
            if current_user.is_authenticated:
                current_user.language = new_lang
                try:
                    db.session.add(current_user)
                    db.session.commit()
                    flash(_('Interface language updated and saved to your profile!'), 'success')
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Error saving language for user {current_user.id}: {str(e)}")
                    flash(_('Could not save language preference to profile.'), 'error')
            else:
                flash(_('Interface language updated for this session!'), 'success')
        else:
            flash(_('Invalid language selected.'), 'error')
        return redirect(request.referrer or url_for('profile.settings'))

    if request.method == 'GET':
        username_form.username.data = current_user.username
        notification_form.enable_price_drop_notifications.data = current_user.enable_price_drop_notifications
        notification_form.enable_target_price_reached_notifications.data = current_user.enable_target_price_reached_notifications
        notification_form.enable_email_notifications.data = current_user.enable_email_notifications
        language_form.language.data = session.get('lang', current_user.language or current_app.config.get('BABEL_DEFAULT_LOCALE', 'en'))


    return render_template(
        'profile/settings.html',
        title=_('Account Settings'),
        username_form=username_form,
        notification_form=notification_form,
        language_form=language_form
    )

@bp.route('/telegram_setup', methods=['GET'])
@login_required
def telegram_setup():
    bot_username = current_app.config.get('TELEGRAM_BOT_USERNAME')
    telegram_link = f"https://t.me/{bot_username}?start={current_user.telegram_linking_token}"

    return render_template('profile/telegram_setup.html',
                           title=_('Telegram Notifications Setup'),
                           telegram_link=telegram_link)


@bp.route('/feedback', methods=['POST', 'GET'])
@login_required
@limiter.limit("5 per hour")
def leave_feedback():
    form = FeedbackForm()
    if form.validate_on_submit():
        try:
            feedback_item = Feedback(
                user_id=current_user.id,
                category=FeedbackCategory(form.category.data),
                message=form.message.data,
                page_url=form.page_url.data
            )
            db.session.add(feedback_item)
            db.session.commit()
            flash(_('Thank you for your feedback! We appreciate you helping us improve SmartPrice.'), 'success')
            send_admin_feedback_notification(feedback_item)
            return redirect(url_for('profile.index'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error saving feedback from user {current_user.id}: {str(e)}", exc_info=True)
            flash(_('Sorry, there was an issue submitting your feedback. Please try again later.'), 'error')

    return render_template('profile/leave_feedback.html', title=_('Leave Feedback'), form=form)


@bp.route('/product/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    form = EditProductForm(obj=product)

    if form.validate_on_submit():
        product.name = form.product_name.data
        product.target_price = form.target_price.data
        product.notification_methods = form.notification_methods.data
        product.check_frequency = form.check_frequency.data
        try:
            db.session.add(product)
            db.session.commit()
            flash(_('Product "%(name)s" updated successfully!', name=product.name), 'success')
            return redirect(url_for('profile.tracked_products'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating product {product_id}: {str(e)}")
            flash(_('Error updating product: %(error)s', error=str(e)), 'error')

    if request.method == 'GET':
        form.product_name.data = product.name
        form.target_price.data = product.target_price
        form.notification_methods.data = product.notification_methods
        form.check_frequency.data = product.check_frequency

    return render_template('profile/edit_product.html', form=form, product=product, title=_('Edit Product'))


@bp.route('/notifications')
@login_required
def view_notifications():
    page = request.args.get('page', 1, type=int)
    per_page = 10

    notifications_pagination = current_user.notifications.order_by(
        UserNotification.is_read.asc(),
        UserNotification.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    notifications = notifications_pagination.items

    notifications_query = current_user.notifications.order_by(desc(UserNotification.created_at))
    all_notifications = notifications_query.all()

    total_count = len(all_notifications)
    unread_count = sum(1 for n in all_notifications if not n.is_read)

    return render_template('profile/view_notifications.html',
                           title=_('My Notifications'),
                           notifications=all_notifications,
                           total_count=total_count,
                           unread_count=unread_count,
                           pagination=notifications_pagination)


@bp.route('/notifications/clear', methods=['POST', 'GET'])
@login_required
def clear_all_notifications():
    try:
        UserNotification.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
        flash(_('All notifications have been cleared.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to clear notifications for user {current_user.id}: {e}")
        flash(_('An error occurred while clearing notifications.'), 'error')
    return redirect(url_for('profile.view_notifications'))



@bp.route('/notification/<int:notification_id>/mark_read', methods=['POST', 'GET'])
@login_required
def mark_notification_read(notification_id):
    notification = UserNotification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    if not notification.is_read:
        notification.is_read = True
        try:
            db.session.add(notification)
            db.session.commit()
            flash(_('Notification marked as read.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error marking notification {notification_id} as read: {str(e)}")
            flash(_('Could not mark notification as read.'), 'error')
    return redirect(request.referrer or url_for('profile.view_notifications'))


@bp.route('/notifications/mark_all_read', methods=['POST', 'GET'])
@login_required
def mark_all_notifications_read():
    try:
        updated_count = UserNotification.query.filter_by(user_id=current_user.id, is_read=False) \
            .update({'is_read': True})
        db.session.commit()
        if updated_count > 0:
            flash(_('%(count)s notifications marked as read.', count=updated_count), 'success')
        else:
            flash(_('No unread notifications to mark.'), 'info')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error marking all notifications as read for user {current_user.id}: {str(e)}")
        flash(_('Could not mark all notifications as read.'), 'error')
    return redirect(url_for('profile.view_notifications'))

@bp.route('/toggle-email-notifications', methods=['POST'])
@login_required
def toggle_email_notifications():
    try:
        current_user.enable_email_notifications = True
        db.session.add(current_user)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Email notifications enabled.'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to toggle email notifications for user {current_user.id}: {e}")
        return jsonify({'success': False, 'message': 'An error occurred.'}), 500

