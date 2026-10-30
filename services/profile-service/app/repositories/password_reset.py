"""Short-lived mailbox proofs; resetting credentials never changes profile data."""
from datetime import timedelta
from secrets import compare_digest, randbelow, token_urlsafe
from fastapi import HTTPException
from pymongo import ReturnDocument
from app.core.passwords import hasher
from app.core.security import digest, keyed, now


class PasswordResetRepository:
    def __init__(self, database, verification):
        self.accounts = database.accounts
        self.resets = database.password_resets
        self.verification = verification
        self.resets.create_index('expires_at', expireAfterSeconds=0)

    def request(self, email, settings, mailer):
        provider = 'local_test' if settings.mode == 'local_test' else 'email'
        identity = provider + ':' + email
        self.verification.limit(settings.otp_secret, 'password-reset-send', identity, 5)
        challenge = token_urlsafe(32)
        account = self.accounts.find_one({'identity': identity, 'email_verified': True,
                                          'migration_pending': {'$ne': True}})
        if account and account.get('password_hash'):
            code = f'{randbelow(1000000):06d}'
            record = {'_id': digest(challenge), 'account_id': account['id'], 'auth_mode': settings.mode,
                      'password_hash': account['password_hash'], 'attempts': 0, 'delivered': False,
                      'code_hash': keyed(settings.otp_secret, challenge, code),
                      'expires_at': now() + timedelta(minutes=10)}
            self.resets.insert_one(record)
            try:
                if mailer is None:
                    raise HTTPException(503, 'Email delivery unavailable. Please retry.')
                mailer.send_password_reset(email, code)
            except Exception:
                self.resets.delete_one({'_id': record['_id']})
                raise
            self.resets.update_one({'_id': record['_id']}, {'$set': {'delivered': True}})
        return {'challenge_id': challenge,
                'message': 'If an email/password account exists for this address, we sent a password reset code.'}

    def complete(self, data, settings):
        # Count every guess atomically before checking it. TTL cleanup is not an expiry check.
        record = self.resets.find_one_and_update(
            {'_id': digest(data.challenge_id), 'auth_mode': settings.mode, 'delivered': True,
             'expires_at': {'$gt': now()}, 'attempts': {'$lt': 5}},
            {'$inc': {'attempts': 1}}, return_document=ReturnDocument.AFTER)
        if not record or not compare_digest(record['code_hash'], keyed(settings.otp_secret, data.challenge_id, data.code)):
            raise HTTPException(400, 'Reset code incorrect, expired or exhausted. Request a new code if needed.')
        # The password hash is the credential generation: only one concurrent reset
        # can win, and every older proof, access attempt and session becomes stale.
        changed = self.accounts.update_one(
            {'id': record['account_id'], 'password_hash': record['password_hash'],
             'email_verified': True, 'migration_pending': {'$ne': True}},
            {'$set': {'password_hash': hasher.hash(data.password), 'password_changed_at': now()}})
        if not changed.modified_count:
            raise HTTPException(400, 'This reset code has already been used or the account changed. Request a new code.')
        return {'ok': True}
