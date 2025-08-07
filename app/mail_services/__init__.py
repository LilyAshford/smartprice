from flask_mail import Message
from flask import render_template, current_app
from flask_babel import force_locale, _
from app.extensions import mail
from threading import Thread
import smtplib
import socket

def send_async_email(app, msg):
    """Asynchronous sending of email in a separate thread."""
    with app.app_context():
        try:
            mail.send(msg)
            app.logger.info(f"Email successfully sent to {msg.recipients} with subject '{msg.subject}'")
        except smtplib.SMTPServerDisconnected as e:
            app.logger.error(f"Mail server disconnected while sending email to {msg.recipients}. Error: {str(e)}")
        except smtplib.SMTPConnectError as e:
            app.logger.error(f"Could not connect to mail server for sending email to {msg.recipients}. Error: {str(e)}")
        except smtplib.SMTPAuthenticationError as e:
            app.logger.error(
                f"Mail server authentication failed for sending email to {msg.recipients}. Error: {str(e)}")
        except smtplib.SMTPRecipientsRefused as e:
            app.logger.error(f"All recipient addresses refused for email to {msg.recipients}. Error: {str(e)}")
        except smtplib.SMTPSenderRefused as e:
            app.logger.error(f"Sender address {msg.sender} refused for email to {msg.recipients}. Error: {str(e)}")
        except smtplib.SMTPDataError as e:
            app.logger.error(
                f"Mail server replied with an unexpected error code (data error) for email to {msg.recipients}. Error: {str(e)}")
        except smtplib.SMTPException as e:
            app.logger.error(f"SMTP error when sending email to {msg.recipients}. Error: {str(e)}")
        except socket.gaierror as e:
            app.logger.error(
                f"DNS resolution failed (gaierror) when sending email to {msg.recipients}. Error: {str(e)}")
        except Exception as e:
            app.logger.error(f"An unexpected error occurred when sending email to {msg.recipients}. Error: {str(e)}",
                             exc_info=True)

def send_verification_email(user, token):
    """Sends email to verify account."""
    app = current_app._get_current_object()
    try:
        locale = user.language if user.language else 'en'
        with force_locale(locale):
            subject = _('Verify Your SmartPrice Account')
        send_email(
            to=user.email,
            subject=subject,
            template='email/confirm',
            user=user,
            token=token,
            expiry_hours=app.config.get('CONFIRMATION_TOKEN_EXPIRY_HOURS', 24)
        )
    except Exception as e:
        app.logger.error(f"Failed to initiate verification email sending for {user.email}. Error: {str(e)}",
                         exc_info=True)

def send_welcome_email(user):
    """Sends a welcome email to a new user."""
    locale = user.language if user.language else 'en'
    with force_locale(locale):
        subject = _('Welcome to SmartPrice!')
    send_email(
        to=user.email,
        subject=subject,
        template='email/welcome',
        user=user
    )

def send_admin_feedback_notification(feedback_item):
    """Sends a notification email to admin about new feedback."""
    app = current_app._get_current_object()
    admin_email = app.config.get('MAIL_SENDER')

    if not admin_email:
        app.logger.warning("ADMIN_EMAIL not set in config. Cannot send feedback notification.")
        return

    locale = feedback_item.user.language if feedback_item.user and feedback_item.user.language else 'en'
    with force_locale(locale):
        subject = _('New Feedback Received on SmartPrice')
    send_email(
        to=admin_email,
        subject=subject,
        template='email/admin_feedback_notification',
        feedback_item=feedback_item,
        user_id=feedback_item.user.id if feedback_item.user else None
    )

# def send_email(to, subject, template, **kwargs):
#     """Sends an email with the specified template and subject."""
#     app = current_app._get_current_object()
#     try:
#         sender = app.config.get('MAIL_SENDER')
#         prefix = app.config.get('MAIL_SUBJECT_PREFIX', '')
#
#         if not sender:
#             app.logger.error("MAIL_SENDER is not configured. Cannot send email.")
#             return None
#
#         msg = Message(prefix + ' ' + subject, sender=sender, recipients=[to])
#
#         locale = kwargs.pop('locale', 'en')
#         with force_locale(locale):
#             kwargs['sincerely'] = _('Sincerely,')
#             kwargs['team_name'] = _('The SmartPrice Team')
#             msg.body = render_template(template + '.txt', **kwargs)
#             msg.html = render_template(template + '.html', **kwargs)
#
#         thr = Thread(target=send_async_email, args=[app, msg])
#         thr.start()
#         app.logger.info(f"Email to {to} with subject '{subject}' queued for sending.")
#         return thr
#
#     except Exception as e:
#         app.logger.error(
#             f"Failed to prepare or queue email for {to}, subject '{subject}'. Error: {str(e)}",
#             exc_info=True
#         )
#         return None
def send_email(to, subject, template, **kwargs):
    try:
        app = current_app._get_current_object()
        msg = Message(
            subject=subject,
            sender=app.config.get('MAIL_DEFAULT_SENDER'),
            recipients=[to]
        )
        kwargs['base_url'] = app.config.get('BASE_URL', '')

        msg.body = render_template(template + '.txt', **kwargs)
        msg.html = render_template(template + '.html', **kwargs)

        mail.send(msg)
        app.logger.info(f"Email sent successfully to {to} with subject '{subject}'")
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send email to {to}, subject '{subject}'. Error: {e}", exc_info=True)
        return False