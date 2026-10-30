"""Server-owned account identities and revocable, attempt-bound sessions."""
from datetime import timedelta
from secrets import token_urlsafe
from uuid import uuid4
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.core.mail import normalize_email
from app.core.passwords import hasher, password_matches
from app.core.security import digest, keyed, now
from app.repositories.verification import VerificationRepository
from app.repositories.password_reset import PasswordResetRepository


class AccountRepository:
    def __init__(self, database, mailer=None):
        self.accounts, self.flows, self.sessions = database.accounts, database.auth_flows, database.auth_sessions
        self.mailer = mailer
        self.verification = VerificationRepository(database)
        self.password_reset = PasswordResetRepository(database, self.verification)
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
                  'expires_at': now() + timedelta(minutes=10), 'attempt_expires_at': now() + timedelta(minutes=10), 'active_session': None}
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
        else:
            account, registration, replaces = self.authenticate(data, flow, settings, verify)
            changes = {'fingerprint': fingerprint, 'account_id': account['id'], 'session_hash': digest(data.session_token)}
            if account.get('password_hash'):
                changes['credential_hash'] = account['password_hash']
            if registration:
                changes.update(registration_candidate=account, registration_replaces=replaces)
            claim = self.flows.update_one({'_id': flow['_id'], 'attempt': flow['attempt'], 'status': 'pending', 'fingerprint': {'$exists': False}},
                {'$set': changes})
            if not claim.modified_count:
                current = self.flows.find_one({'_id': flow['_id'], 'attempt': flow['attempt']})
                if not current or current.get('fingerprint') != fingerprint or current['status'] not in ('pending', 'completed'):
                    raise HTTPException(409, 'Access attempt cancelled or superseded. Start again.')
            flow = self.attempt(data, settings)
        # A concurrent identical completion must use the winning flow's candidate,
        # never the temporary identity generated by its losing request.
        account = self.bound_account(flow)
        if flow.get('registration_candidate') and flow.get('otp_verified'):
            account = self.activate_registration(flow)
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
                if not account:
                    raise HTTPException(404, 'No account was found for this email address. Create a new account to get started.')
                raise HTTPException(401, 'Email or password is incorrect.')
            return account, False, None
        if account:
            if google and not account.get('email_verified') and account.get('created_by') == digest(data.attempt_id):
                return account, False, None
            if google or not self.reclaimable_reservation(account):
                raise HTTPException(409, 'An account already exists for this email address. Sign in or use Forgot password.')
        identifier = str(uuid4())
        candidate = {'id': identifier, 'identity': identity, 'provider': provider, 'email': email,
                     'name': name, 'owner': identity if google else provider + ':' + identifier,
                     'created_at': now(), 'created_by': digest(data.attempt_id), 'email_verified': False}
        if not google:
            candidate['password_hash'] = hasher.hash(data.password)
        return candidate, True, account['id'] if account else None

    def bound_account(self, flow):
        account = flow.get('registration_candidate') or self.accounts.find_one({'id': flow.get('account_id')})
        if not account:
            raise HTTPException(409, 'This account access changed. Start again.')
        if (flow.get('credential_hash') != account.get('password_hash')
            and ('credential_hash' in flow or account.get('password_changed_at'))):
            raise HTTPException(409, 'Your password changed. Start a new sign-in attempt.')
        return account

    def reclaimable_reservation(self, account):
        """Only the old, empty email-signup record may be replaced after OTP proof."""
        allowed = {'_id', 'id', 'identity', 'provider', 'email', 'name', 'owner',
                   'created_at', 'created_by', 'email_verified', 'password_hash'}
        provider = account.get('provider')
        if (provider not in ('email', 'local_test') or account.get('email_verified') is not False
            or set(account) - allowed
            or any(not isinstance(account.get(key), str) or not account[key]
                   for key in ('id', 'email', 'password_hash', 'created_by'))
            or account.get('identity') != provider + ':' + account.get('email', '')
            or account.get('owner') != provider + ':' + account.get('id', '')):
            return False
        database = self.accounts.database
        return not any((database.profile_versions.find_one({'owner': account['owner']}, {'_id': 1}),
                        database.profile_mutations.find_one({'owner': account['owner']}, {'_id': 1}),
                        database.capability_mutations.find_one({'user_id': account['id']}, {'_id': 1}),
                        self.sessions.find_one({'account_id': account['id']}, {'_id': 1})))

    def activate_registration(self, flow):
        if not flow.get('otp_verified'):
            raise HTTPException(409, 'Verify your email before creating an account.')
        candidate = flow['registration_candidate']
        marker = {'flow': flow['_id'], 'attempt': flow['attempt'], 'fingerprint': flow['fingerprint']}
        activated = {**candidate, 'email_verified': True, 'email_verified_at': now(), 'registration_attempt': marker}
        current = self.accounts.find_one({'identity': candidate['identity']})
        if current and current.get('id') == candidate['id'] and current.get('registration_attempt') == marker:
            activated = current
        elif current:
            if current.get('id') != flow.get('registration_replaces') or not self.reclaimable_reservation(current):
                raise HTTPException(409, 'An account already exists for this email address. Sign in or use Forgot password.')
            # Compare the complete previously inspected reservation. A concurrent
            # verification, migration or newly attached data must defeat replacement.
            activated = self.accounts.find_one_and_replace(
                {'_id': current['_id'], '$expr': {'$eq': ['$$ROOT', {'$literal': current}]}},
                activated, return_document=ReturnDocument.AFTER)
            if activated is None:
                activated = self.accounts.find_one({'identity': candidate['identity']})
        else:
            try:
                self.accounts.insert_one(activated)
            except DuplicateKeyError:
                activated = self.accounts.find_one({'identity': candidate['identity']})
        if (not activated or activated.get('id') != candidate['id']
            or activated.get('registration_attempt') != marker):
            raise HTTPException(409, 'An account already exists for this email address. Sign in or use Forgot password.')
        if flow.get('registration_replaces'):
            # The fresh ID/owner already fences old proofs. Explicit cancellation
            # also makes retries clear, and is safe to repeat after a lost response.
            self.flows.update_many({'account_id': flow['registration_replaces']},
                                   {'$set': {'status': 'cancelled', 'active_session': None}})
            self.sessions.update_many({'account_id': flow['registration_replaces']}, {'$set': {'revoked': True}})
        return activated

    def publish(self, data, flow, account, settings):
        session_hash = digest(data.session_token)
        if flow.get('session_hash') != session_hash:
            raise HTTPException(409, 'The verification session changed. Start again.')
        self.sessions.update_one({'_id': session_hash}, {'$setOnInsert': {
            'account_id': account['id'], 'flow': flow['_id'], 'auth_mode': settings.mode,
            'credential_hash': account.get('password_hash'),
            'expires_at': now() + timedelta(hours=24), 'revoked': False}}, upsert=True)
        updated = self.flows.update_one({'_id': flow['_id'], 'attempt': flow['attempt'], 'status': 'pending',
                                        'fingerprint': flow['fingerprint']},
            {'$set': {'status': 'completed', 'active_session': session_hash, 'expires_at': now() + timedelta(days=2)},
             '$unset': {'registration_candidate': '', 'registration_replaces': ''}})
        if not updated.modified_count:
            latest = self.flows.find_one({'_id': flow['_id']})
            if not latest or latest.get('status') != 'completed' or latest.get('fingerprint') != flow['fingerprint']:
                raise HTTPException(409, 'Access attempt cancelled or superseded. Start again.')
        return self.session(data.session_token, settings)

    def verify_email(self, data, settings):
        flow = self.attempt(data, settings)
        if flow.get('session_hash') != digest(data.session_token) or not flow.get('account_id'):
            raise HTTPException(409, 'This verification request does not match account access. Start again.')
        account = self.bound_account(flow)
        verified = self.verification.consume(data, flow, account, settings)
        if verified.get('registration_candidate'):
            account = self.activate_registration(verified)
        else:
            updated = self.accounts.update_one({'id': account['id'], 'identity': account['identity'], 'email': account['email'],
                                               'migration_pending': {'$ne': True}},
                                              {'$set': {'email_verified': True, 'email_verified_at': now()}})
            if not updated.matched_count:
                raise HTTPException(409, 'This account access changed. Start again.')
        return self.publish(data, verified, account, settings)

    def resend(self, data, settings):
        flow = self.attempt(data, settings)
        if flow['status'] != 'pending' or flow.get('session_hash') != digest(data.session_token) or not flow.get('account_id'):
            raise HTTPException(409, 'Start a new verification attempt.')
        return self.verification.send(flow, self.bound_account(flow), settings, self.mailer, resend=True)

    def session(self, token, settings=None):
        session = self.sessions.find_one({'_id': digest(token), 'revoked': False, 'expires_at': {'$gt': now()}})
        if (not session or (settings and session.get('auth_mode') != settings.mode)
            or not self.flows.find_one({'_id': session['flow'], 'active_session': session['_id'], 'status': 'completed'})):
            raise HTTPException(401, 'Your session ended. Please sign in again.')
        account = self.accounts.find_one({'id': session['account_id'], 'email_verified': True, 'migration_pending': {'$ne': True}})
        if not account:
            raise HTTPException(401, 'Verify your email and sign in again.')
        if session.get('credential_hash') != account.get('password_hash'):
            # Keep pre-upgrade sessions only until the first password reset.
            legacy = 'credential_hash' not in session and not account.get('password_changed_at')
            if not legacy:
                raise HTTPException(401, 'Your password changed. Please sign in again.')
        return {**account, 'expires_at': session['expires_at'].replace(tzinfo=now().tzinfo)}

    def logout(self, token):
        key = digest(token)
        session = self.sessions.find_one_and_update({'_id': key}, {'$set': {'revoked': True}})
        if session:
            self.flows.update_one({'_id': session['flow'], 'active_session': key}, {'$set': {'active_session': None, 'status': 'cancelled'}})

    def cancel(self, data):
        self.flows.update_one({'_id': digest(data.flow_id), 'attempt': digest(data.attempt_id)},
                             {'$set': {'active_session': None, 'status': 'cancelled'}})
