import importlib.util
from email import policy
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock

import pytest


ADDRESS = 'elo.synthetic.test@gmail.com'
RECIPIENT = 'elo.synthetic.test+elo-0123456789abcdef01234567@gmail.com'


@pytest.fixture
def inbox():
    path = Path(__file__).resolve().parents[3] / 'infrastructure/testing/gmail_test_inbox.py'
    spec = importlib.util.spec_from_file_location('gmail_test_inbox', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def message_bytes(**headers):
    message = EmailMessage(policy=policy.SMTP)
    for name, value in ({'From': ADDRESS, 'To': RECIPIENT, 'Subject': 'Verify your elo account'} | headers).items():
        message[name] = value
    message.set_content('Your elo verification code is: 123456\n\nThis code expires in 10 minutes.')
    return message.as_bytes()


@pytest.mark.parametrize('headers', [
    {'To': 'elo.synthetic.test+elo-abcdef0123456789abcdef01@gmail.com'},
    {'From': 'other.synthetic.test@gmail.com'},
    {'Subject': 'Reset your elo password'},
])
def test_ignores_messages_outside_the_exact_sender_recipient_and_purpose(inbox, headers):
    assert inbox.verification_code(message_bytes(**headers), ADDRESS, RECIPIENT) is None


def test_polls_gmail_with_read_only_search_and_fetch(inbox, monkeypatch):
    connection = MagicMock()
    mailbox = connection.return_value.__enter__.return_value
    mailbox.select.return_value = ('OK', [b'1'])
    mailbox.uid.side_effect = [
        ('OK', [None]),
        ('OK', [b'12']),
        ('OK', [(b'12 (BODY[] {42}', message_bytes()), b')']),
    ]
    monkeypatch.setattr(inbox.imaplib, 'IMAP4_SSL', connection)
    monkeypatch.setattr(inbox.time, 'sleep', lambda _: None)

    assert inbox.read_verification_code(ADDRESS, 'synthetic-app-password', RECIPIENT) == '123456'
    assert connection.call_args.args == ('imap.gmail.com',)
    assert connection.call_args.kwargs['ssl_context'].check_hostname
    mailbox.login.assert_called_once_with(ADDRESS, 'synthetic-app-password')
    mailbox.select.assert_called_once_with('INBOX', readonly=True)
    assert mailbox.uid.call_args_list[0].args == (
        'SEARCH', None, 'TO', f'"{RECIPIENT}"', 'SUBJECT', '"Verify your elo account"',
    )
    mailbox.uid.assert_called_with('FETCH', b'12', '(BODY.PEEK[])')


def test_rejects_an_address_outside_the_test_mailbox_before_connecting(inbox, monkeypatch):
    monkeypatch.setenv('ELO_TEST_GMAIL_ADDRESS', ADDRESS)
    monkeypatch.setenv('ELO_TEST_GMAIL_APP_PASSWORD', 'synthetic-app-password')
    monkeypatch.setattr(inbox.sys, 'argv', ['gmail_test_inbox.py', 'other.synthetic.test@gmail.com'])
    connection = MagicMock()
    monkeypatch.setattr(inbox.imaplib, 'IMAP4_SSL', connection)

    with pytest.raises(SystemExit, match='Elo test alias'):
        inbox.main()
    connection.assert_not_called()
