"""SMTP transport. Development inbox capture is separate from production delivery."""
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email_validator import validate_email, EmailNotValidError
from fastapi import HTTPException


def normalize_email(value):
    try:
        return validate_email(value, check_deliverability=False, test_environment=True).normalized.casefold()
    except (EmailNotValidError, TypeError) as exc:
        raise ValueError('Enter a valid email address.') from exc


@dataclass(frozen=True)
class MailSettings:
    host: str
    port: int
    security: str
    username: str
    password: str
    sender: str


def mail_settings(environment):
    host = os.getenv('SMTP_HOST', 'localhost' if environment == 'development' else '').strip()
    security = os.getenv('SMTP_SECURITY', 'plain' if environment == 'development' else 'starttls')
    if security not in {'plain', 'starttls', 'ssl'}:
        raise RuntimeError('SMTP_SECURITY must be plain, starttls or ssl.')
    try:
        port = int(os.getenv('SMTP_PORT', '1025' if environment == 'development' else '587'))
        if not 1 <= port <= 65535:
            raise ValueError
        sender = normalize_email(os.getenv('SMTP_FROM', 'no-reply@coachify.test' if environment == 'development' else ''))
    except ValueError as exc:
        raise RuntimeError('Set a valid SMTP_PORT and SMTP_FROM.') from exc
    username, password = os.getenv('SMTP_USERNAME', ''), os.getenv('SMTP_PASSWORD', '')
    if bool(username) != bool(password):
        raise RuntimeError('SMTP_USERNAME and SMTP_PASSWORD must be configured together.')
    if host.casefold() == 'smtp.gmail.com' and (not username or security == 'plain'):
        raise RuntimeError('Gmail requires an App Password, SMTP_USERNAME and encrypted SMTP, including in development.')
    if environment == 'production' and (not host or not username or security == 'plain' or host in {'mailpit', 'localhost', '127.0.0.1'}):
        raise RuntimeError('Production requires an external SMTP host, authentication and encrypted SMTP.')
    return MailSettings(host, port, security, username, password, sender)


class SmtpMailer:
    def __init__(self, settings):
        self.settings = settings

    def send_otp(self, destination, code):
        settings = self.settings
        if not settings.host:
            raise HTTPException(503, 'Email delivery is not configured. Contact your administrator.')
        message = EmailMessage()
        message['From'] = settings.sender
        message['To'] = destination
        message['Subject'] = 'Verify your Coachify account'
        message.set_content(f'Your Coachify verification code is: {code}\n\nThis code expires in 10 minutes. Use the latest email if you requested another code. If you did not request this account, ignore this email.')
        try:
            transport = smtplib.SMTP_SSL if settings.security == 'ssl' else smtplib.SMTP
            options = {'context': ssl.create_default_context()} if settings.security == 'ssl' else {}
            with transport(settings.host, settings.port, timeout=10, **options) as smtp:
                if settings.security == 'starttls':
                    smtp.starttls(context=ssl.create_default_context())
                if settings.username:
                    smtp.login(settings.username, settings.password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise HTTPException(503, 'Verification email could not be sent. Keep your details and retry.') from exc
