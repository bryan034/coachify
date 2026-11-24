import pytest


@pytest.fixture(autouse=True)
def isolated_development_environment(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')
    for name in ('SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURITY', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'SMTP_FROM', 'OTP_HASH_SECRET'):
        monkeypatch.delenv(name, raising=False)
