import pytest
import smtplib
import ssl
from app.core.auth import auth_settings
from app.core.mail import mail_settings


def production(monkeypatch):
    for key,value in {'APP_ENV':'production','AUTH_MODE':'email','OTP_HASH_SECRET':'synthetic-test-only-key-which-is-not-a-live-secret',
                      'SMTP_HOST':'smtp.example.test','SMTP_PORT':'587','SMTP_SECURITY':'starttls',
                      'SMTP_USERNAME':'synthetic-user','SMTP_PASSWORD':'synthetic-mail-password','SMTP_FROM':'no-reply@example.test'}.items():
        monkeypatch.setenv(key,value)


def test_explicit_email_only_production_needs_no_google_key(monkeypatch):
    production(monkeypatch)
    monkeypatch.delenv('GOOGLE_CLIENT_ID',raising=False)
    assert auth_settings().mode=='email'
    assert auth_settings().google_client_id==''


@pytest.mark.parametrize('key,value',[
    ('AUTH_MODE','local_test'),('AUTH_MODE','unknown'),('APP_ENV','staging'),('OTP_HASH_SECRET',''),
    ('SMTP_HOST','mailpit'),('SMTP_HOST',''),('SMTP_SECURITY','plain'),('SMTP_USERNAME',''),
    ('SMTP_PASSWORD',''),('SMTP_FROM','invalid'),('SMTP_PORT','0'),('SMTP_SECURITY','invalid'),
])
def test_production_rejects_missing_or_unsafe_configuration(monkeypatch,key,value):
    production(monkeypatch)
    monkeypatch.setenv(key,value)
    with pytest.raises(RuntimeError):
        auth_settings()


def test_google_mode_does_not_silently_become_email_or_development(monkeypatch):
    production(monkeypatch)
    monkeypatch.setenv('AUTH_MODE','google')
    monkeypatch.delenv('GOOGLE_CLIENT_ID',raising=False)
    with pytest.raises(RuntimeError,match='GOOGLE_CLIENT_ID'):
        auth_settings()


def test_development_email_verification_needs_no_live_credentials(monkeypatch):
    monkeypatch.setenv('AUTH_MODE','local_test')
    settings=auth_settings()
    assert settings.mode=='local_test' and len(settings.otp_secret)>=32
    smtp=mail_settings(settings.environment)
    assert smtp.security=='plain' and smtp.port==1025 and not smtp.password


def gmail_development(monkeypatch):
    for key, value in {'APP_ENV':'development', 'AUTH_MODE':'google',
                       'GOOGLE_CLIENT_ID':'synthetic-client.apps.googleusercontent.com',
                       'SMTP_HOST':'smtp.gmail.com', 'SMTP_PORT':'587', 'SMTP_SECURITY':'starttls',
                       'SMTP_USERNAME':'synthetic-sender@example.test', 'SMTP_PASSWORD':'synthetic-app-password',
                       'SMTP_FROM':'synthetic-sender@example.test'}.items():
        monkeypatch.setenv(key, value)


def test_development_google_and_real_smtp_can_be_configured(monkeypatch):
    gmail_development(monkeypatch)
    settings = auth_settings()
    assert settings.environment == 'development' and settings.mode == 'google'
    assert settings.google_client_id == 'synthetic-client.apps.googleusercontent.com'
    assert mail_settings(settings.environment).host == 'smtp.gmail.com'


@pytest.mark.parametrize('key,value', [('SMTP_SECURITY','plain'), ('SMTP_USERNAME',''), ('SMTP_PASSWORD','')])
def test_gmail_requires_secure_authenticated_delivery_even_in_development(monkeypatch, key, value):
    gmail_development(monkeypatch)
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        auth_settings()


def test_gmail_transport_uses_tls_and_sends_to_registered_address(monkeypatch):
    from unittest.mock import patch
    from app.core.mail import SmtpMailer
    gmail_development(monkeypatch)
    with patch('app.core.mail.smtplib.SMTP') as transport:
        smtp = transport.return_value.__enter__.return_value
        SmtpMailer(mail_settings('development')).send_otp('synthetic-recipient@example.test', '123456')
        transport.assert_called_once_with('smtp.gmail.com', 587, timeout=10)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with('synthetic-sender@example.test', 'synthetic-app-password')
        message = smtp.send_message.call_args.args[0]
        assert message['To'] == 'synthetic-recipient@example.test'
        assert message['From'] == 'synthetic-sender@example.test'
        assert '123456' in message.get_content()
        assert [call[0] for call in smtp.method_calls] == ['starttls', 'login', 'send_message']


def test_default_authentication_is_email_and_ignores_unused_google_credentials(monkeypatch):
    production(monkeypatch)
    monkeypatch.delenv('AUTH_MODE', raising=False)
    monkeypatch.setenv('GOOGLE_CLIENT_ID', 'unused-synthetic-client.apps.googleusercontent.com')
    settings = auth_settings()
    assert settings.mode == 'email'
    assert settings.google_client_id == ''


def test_reset_email_uses_reset_subject_and_never_exposes_smtp_failure_details(monkeypatch):
    import smtplib
    from unittest.mock import patch
    from fastapi import HTTPException
    from app.core.mail import SmtpMailer
    gmail_development(monkeypatch)
    mailer = SmtpMailer(mail_settings('development'))
    with patch('app.core.mail.smtplib.SMTP') as transport:
        mailer.send_password_reset('synthetic@example.test', '123456')
        message = transport.return_value.__enter__.return_value.send_message.call_args.args[0]
        assert message['Subject'] == 'Reset your elo password'
        assert '123456' in message.get_content()
    with patch('app.core.mail.smtplib.SMTP', side_effect=smtplib.SMTPAuthenticationError(535, b'synthetic-private-provider-detail')):
        with pytest.raises(HTTPException) as error:
            mailer.send_otp('synthetic@example.test', '123456')
        assert error.value.status_code == 503
        assert 'rejected its credentials' in error.value.detail
        assert 'synthetic-private-provider-detail' not in error.value.detail


@pytest.mark.parametrize('failure,expected', [
    (OSError('synthetic-private-network-detail'), 'outgoing mail server'),
    (smtplib.SMTPConnectError(421, b'synthetic-private-response'), 'outgoing mail server'),
    (smtplib.SMTPServerDisconnected('synthetic-private-response'), 'outgoing mail server'),
    (ssl.SSLError('synthetic-private-certificate-detail'), 'secure connection'),
    (smtplib.SMTPNotSupportedError('synthetic-private-response'), 'secure connection'),
    (smtplib.SMTPSenderRefused(550, b'synthetic-private-response', 'sender@example.test'), 'sending address'),
    (smtplib.SMTPRecipientsRefused({'recipient@example.test': (550, b'synthetic-private-response')}), 'recipient address'),
    (smtplib.SMTPDataError(554, b'synthetic-private-response'), 'rejected the verification email'),
])
def test_email_delivery_errors_give_specific_safe_recovery_guidance(monkeypatch, failure, expected):
    from unittest.mock import patch
    from fastapi import HTTPException
    from app.core.mail import SmtpMailer
    gmail_development(monkeypatch)
    with patch('app.core.mail.smtplib.SMTP', side_effect=failure):
        with pytest.raises(HTTPException) as error:
            SmtpMailer(mail_settings('development')).send_otp('recipient@example.test', '123456')
    assert error.value.status_code == 503
    assert expected in error.value.detail
    assert 'synthetic-private' not in error.value.detail
    assert 'recipient@example.test' not in error.value.detail
