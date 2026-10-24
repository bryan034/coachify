"""Server-owned account identities and revocable, attempt-bound sessions."""
from datetime import timedelta
from secrets import token_urlsafe
from uuid import uuid4
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from app.core.mail import normalize_email
from app.core.passwords import hasher, password_matches
from app.core.security import digest, keyed, now
from app.repositories.verification import VerificationRepository


class AccountRepository:
    def __init__(self, database, mailer=None):
        self.accounts, self.flows, self.sessions = database.accounts, database.auth_flows, database.auth_sessions
        self.mailer = mailer
        self.verification = VerificationRepository(database)
        self.accounts.create_index('identity', unique=True)
        self.accounts.create_index('owner', unique=True, partialFilterExpression={'owner': {'$type': 'string'}})
        self.sessions.create_index('expires_at', expireAfterSeconds=0)
        self.flows.create_index('expires_at', expireAfterSeconds=0)

    def local_accounts(self):
        return list(self.accounts.find({'provider': 'local_test', 'email': {'$type': 'string'}},
            {'_id': 0, 'id': 1, 'name': 1, 'email': 1}).sort('created_at', 1))

    def begin(self, data, settings):
        key = digest(data.flow_id)
        existing = self.flows.find_one({'_id': key})
        if existing and existing['generation'] >= data.generation:
            if (existing['generation'] == data.generation and existing['attempt'] == digest(data.attempt_id)
                and existing['status'] == 'pending' and existing['intent'] == data.intent and existing.get('auth_mode') == settings.mode
                and existing['attempt_expires_at'].replace(tzinfo=now().tzinfo) > now()):
                return {'nonce': existing['nonce']}
            raise HTTPException(409, 'This access attempt is no longer current. Start again.')
        record = {'_id': key, 'generation': data.generation, 'attempt': digest(data.attempt_id), 'intent': data.intent,
                  'auth_mode': settings.mode, 'nonce': token_urlsafe(32), 'status': 'pending',
                  'expires_at': now() + timedelta(days=2), 'attempt_expires_at': now() + timedelta(minutes=10), 'active_session': None}
        if existing:
            changed = self.flows.replace_one({'_id': key, 'generation': existing['generation']}, record).modified_count
            if not changed:
                raise HTTPException(409, 'Another access attempt started. Please retry.')
        else:
            try:
                self.flows.insert_one(record)
            except DuplicateKeyError:
                raise HTTPException(409, 'Another access attempt started. Please retry.')
        return {'nonce': record['nonce']}

    def attempt(self, data, settings):
        flow = self.flows.find_one({'_id': digest(data.flow_id), 'attempt': digest(data.attempt_id)})
        if (not flow or flow['status'] not in ('pending', 'completed') or flow.get('auth_mode') != settings.mode
            or flow['attempt_expires_at'].replace(tzinfo=now().tzinfo) <= now()):
            raise HTTPException(409, 'Access attempt cancelled, changed mode or expired. Start again.')
        return flow

    def finish(self, data, settings, verify):
        flow = self.attempt(data, settings)
        fingerprint = keyed(settings.otp_secret, flow['intent'], data.name, data.email, data.password,
                            data.credential, digest(data.session_token))
        if flow.get('fingerprint'):
            if flow['fingerprint'] != fingerprint:
                raise HTTPException(409, 'This attempt has already been used. Start again to change account details.')
            account = self.accounts.find_one({'id': flow['account_id']})
        else:
            account = self.authenticate(data, flow, settings, verify)
            claim = self.flows.update_one({'_id': flow['_id'], 'attempt': flow['attempt'], 'status': 'pending', 'fingerprint': {'$exists': False}},
                {'$set': {'fingerprint': fingerprint, 'account_id': account['id'], 'session_hash': digest(data.session_token)}})
            if not claim.modified_count:
                current = self.flows.find_one({'_id': flow['_id'], 'attempt': flow['attempt']})
                if not current or current.get('fingerprint') != fingerprint or current['status'] not in ('pending', 'completed'):
                    raise HTTPException(409, 'Access attempt cancelled or superseded. Start again.')
            flow = self.attempt(data, settings)
        if account.get('migration_pending'):
            raise HTTPException(409, 'Account maintenance in progress. Please retry later.')
        if not account.get('email_verified'):
            return self.verification.send(flow, account, settings, self.mailer)
        return self.publish(data, flow, account, settings)

    def authenticate(self, data, flow, settings, verify):
        google = data.credential is not None
        if google:
            if settings.mode != 'google' or data.email is not None or data.password is not None:
                raise HTTPException(401, 'Google access is unavailable for this request.')
            claims = verify(data.credential, settings.google_client_id, flow['nonce'])
            try:
                email = normalize_email(claims.get('email'))
            except ValueError as exc:
                raise HTTPException(401, 'Google must provide a verified email address.') from exc
            if claims.get('email_verified') is not True:
                raise HTTPException(401, 'Google must provide a verified email address.')
            identity, provider = 'google:' + claims['sub'], 'google'
            name = str(claims.get('name') or email.split('@')[0])[:80]
        else:
            if not data.email or not data.password:
                raise HTTPException(422, 'Enter your email address and password.')
            email = data.email
            provider = 'local_test' if settings.mode == 'local_test' else 'email'
            identity = provider + ':' + email
            name = (data.name or '').strip() or email.split('@')[0]
            self.verification.limit(settings.otp_secret, 'credentials', identity, 10)
        account = self.accounts.find_one({'identity': identity})
        if google and account and not account.get('email'):
            # Upgrade only after proving the exact Google subject; never link by email.
            self.accounts.update_one({'id': account['id'], 'email': {'$exists': False}},
                                     {'$set': {'email': email, 'email_verified': False}})
            account = self.accounts.find_one({'id': account['id']})
        if flow['intent'] == 'login':
            if google:
                if not account:
                    raise HTTPException(404, 'Account not found. Choose Create account first.')
            elif not password_matches((account or {}).get('password_hash'), data.password):
                raise HTTPException(401, 'Email or password is incorrect.')
            return account
        if account:
            # A pending account may be recovered only by proving its own credential.
            if account.get('email_verified') or account.get('created_by') != digest(data.attempt_id):
                raise HTTPException(409, 'An account already exists. Choose Sign in to continue verification if needed.')
            if not google and not password_matches(account.get('password_hash'), data.password):
                raise HTTPException(409, 'An account already exists. Choose Sign in.')
            return account
        identifier = str(uuid4())
        candidate = {'id': identifier, 'identity': identity, 'provider': provider, 'email': email,
                     'name': name, 'owner': identity if google else provider + ':' + identifier,
                     'created_at': now(), 'created_by': digest(data.attempt_id), 'email_verified': False}
        if not google:
            candidate['password_hash'] = hasher.hash(data.password)
        try:
            self.accounts.insert_one(candidate)
            return candidate
        except DuplicateKeyError:
            account = self.accounts.find_one({'identity': identity})
            if not account or (not google and not password_matches(account.get('password_hash'), data.password)):
                raise HTTPException(409, 'An account already exists. Choose Sign in.')
            if account.get('email_verified') or account.get('created_by') != digest(data.attempt_id):
                raise HTTPException(409, 'An account already exists. Choose Sign in to continue verification if needed.')
            return account

    def publish(self, data, flow, account, settings):
        session_hash = digest(data.session_token)
        if flow.get('session_hash') != session_hash:
            raise HTTPException(409, 'The verification session changed. Start again.')
        self.sessions.update_one({'_id': session_hash}, {'$setOnInsert': {
            'account_id': account['id'], 'flow': flow['_id'], 'auth_mode': settings.mode,
            'expires_at': now() + timedelta(hours=24), 'revoked': False}}, upsert=True)
        updated = self.flows.update_one({'_id': flow['_id'], 'attempt': flow['attempt'], 'status': 'pending',
                                        'fingerprint': flow['fingerprint']},
            {'$set': {'status': 'completed', 'active_session': session_hash}})
        if not updated.modified_count:
            latest = self.flows.find_one({'_id': flow['_id']})
            if not latest or latest.get('status') != 'completed' or latest.get('fingerprint') != flow['fingerprint']:
                raise HTTPException(409, 'Access attempt cancelled or superseded. Start again.')
        return self.session(data.session_token, settings)

    def verify_email(self, data, settings):
        flow = self.attempt(data, settings)
        if flow.get('session_hash') != digest(data.session_token) or not flow.get('account_id'):
            raise HTTPException(409, 'This verification request does not match account access. Start again.')
        account = self.accounts.find_one({'id': flow['account_id']})
        verified = self.verification.consume(data, flow, account, settings)
        self.accounts.update_one({'id': account['id'], 'email': account['email']},
                                 {'$set': {'email_verified': True, 'email_verified_at': now()}})
        return self.publish(data, verified, account, settings)

    def resend(self, data, settings):
        flow = self.attempt(data, settings)
        if flow['status'] != 'pending' or flow.get('session_hash') != digest(data.session_token) or not flow.get('account_id'):
            raise HTTPException(409, 'Start a new verification attempt.')
        return self.verification.send(flow, self.accounts.find_one({'id': flow['account_id']}), settings, self.mailer, resend=True)

    def session(self, token, settings=None):
        session = self.sessions.find_one({'_id': digest(token), 'revoked': False, 'expires_at': {'$gt': now()}})
        if (not session or (settings and session.get('auth_mode') != settings.mode)
            or not self.flows.find_one({'_id': session['flow'], 'active_session': session['_id'], 'status': 'completed'})):
            raise HTTPException(401, 'Your session ended. Please sign in again.')
        account = self.accounts.find_one({'id': session['account_id'], 'email_verified': True, 'migration_pending': {'$ne': True}})
        if not account:
            raise HTTPException(401, 'Verify your email and sign in again.')
        return {**account, 'expires_at': session['expires_at'].replace(tzinfo=now().tzinfo)}

    def logout(self, token):
        key = digest(token)
        session = self.sessions.find_one_and_update({'_id': key}, {'$set': {'revoked': True}})
        if session:
            self.flows.update_one({'_id': session['flow'], 'active_session': key}, {'$set': {'active_session': None, 'status': 'cancelled'}})

    def cancel(self, data):
        self.flows.update_one({'_id': digest(data.flow_id), 'attempt': digest(data.attempt_id)},
                             {'$set': {'active_session': None, 'status': 'cancelled'}})
