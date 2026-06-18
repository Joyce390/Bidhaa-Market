from flask_mail import Message
from flask import current_app
from market.__init__ import mail  # ✅ Import mail properly

def send_reset_email(email, reset_url):
    """Send password reset email with a secure link."""
    msg = Message('Password Reset Request', recipients=[email])
    msg.body = f'''To reset your password, visit the following link:
{reset_url}

If you did not make this request, please ignore this email.
'''
    mail.send(msg)
