import imaplib
import os
import re
import ssl
import sys
import time
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses


SUBJECT = 'Verify your elo account'


def verification_code(raw, sender, recipient):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if message['Subject'] != SUBJECT:
        return None
    from_addresses = [address.casefold() for _, address in getaddresses(message.get_all('From', []))]
    to_addresses = [address.casefold() for _, address in getaddresses(message.get_all('To', []))]
    if from_addresses != [sender] or to_addresses != [recipient]:
        return None
    body = message.get_body(preferencelist=('plain',))
    if body is None:
        return None
    match = re.search(r'^Your elo verification code is: ([0-9]{6})\r?$', body.get_content(), re.MULTILINE)
    return match.group(1) if match else None


def read_verification_code(address, password, recipient):
    deadline = time.monotonic() + 60
    with imaplib.IMAP4_SSL('imap.gmail.com', ssl_context=ssl.create_default_context(), timeout=10) as inbox:
        inbox.login(address, password)
        status, _ = inbox.select('INBOX', readonly=True)
        if status != 'OK':
            raise imaplib.IMAP4.error('Could not open the Gmail inbox.')
        while time.monotonic() < deadline:
            status, messages = inbox.uid('SEARCH', None, 'TO', f'"{recipient}"', 'SUBJECT', f'"{SUBJECT}"')
            if status != 'OK':
                raise imaplib.IMAP4.error('Could not search the Gmail inbox.')
            for uid in reversed((messages[0] or b'').split()):
                status, parts = inbox.uid('FETCH', uid, '(BODY.PEEK[])')
                if status != 'OK':
                    raise imaplib.IMAP4.error('Could not read the Gmail message.')
                for part in parts:
                    if isinstance(part, tuple):
                        code = verification_code(part[1], address, recipient)
                        if code:
                            return code
            time.sleep(2)
    return None


def main():
    address = os.getenv('ELO_TEST_GMAIL_ADDRESS', '').strip().lower()
    password = os.getenv('ELO_TEST_GMAIL_APP_PASSWORD', '').strip()
    recipient = sys.argv[1] if len(sys.argv) == 2 else ''
    if not re.fullmatch(r'[a-z0-9]+(?:\.[a-z0-9]+)*@gmail\.com', address) or not password:
        sys.exit('Set ELO_TEST_GMAIL_ADDRESS and ELO_TEST_GMAIL_APP_PASSWORD for a dedicated Gmail mailbox.')
    local_part = address.split('@', 1)[0]
    if not re.fullmatch(rf'{re.escape(local_part)}\+elo-[0-9a-f]{{24}}@gmail\.com', recipient):
        sys.exit('The requested recipient must be an Elo test alias of the configured Gmail mailbox.')
    try:
        code = read_verification_code(address, password, recipient)
    except (imaplib.IMAP4.error, OSError):
        sys.exit('Could not read the Gmail test inbox. Check the App Password and IMAP connection.')
    if code is None:
        sys.exit('No matching Elo verification email arrived in the Gmail test inbox within 60 seconds.')
    print(code)


if __name__ == '__main__':
    main()
