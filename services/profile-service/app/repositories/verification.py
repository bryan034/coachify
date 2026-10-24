"""Atomic OTP claims and rate limits; SMTP never receives database credentials."""
from datetime import timedelta
from secrets import randbelow, token_urlsafe
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.core.security import now, keyed, digest


class VerificationRepository:
    def __init__(self, database):
        self.flows = database.auth_flows
        self.limits = database.auth_limits
        self.limits.create_index('expires_at', expireAfterSeconds=0)

    def limit(self, secret, category, identity, maximum):
        window = int(now().timestamp()) // 900
        identifier = keyed(secret, category, identity, window)
        try:
            self.limits.update_one({'_id': identifier}, {'$setOnInsert': {'count': 0, 'expires_at': now() + timedelta(minutes=30)}}, upsert=True)
        except DuplicateKeyError:
            pass
        claimed = self.limits.find_one_and_update({'_id': identifier, 'count': {'$lt': maximum}}, {'$inc': {'count': 1}})
        if claimed is None:
            raise HTTPException(429, 'Too many attempts. Please wait 15 minutes before trying again.')

    @staticmethod
    def receipt(flow):
        local, domain = flow['email'].split('@', 1)
        return {'verification_required': True, 'challenge_id': flow['challenge_id'],
                'masked_email': local[:1] + '***@' + domain,
                'expires_at': flow['code_expires_at'].replace(tzinfo=now().tzinfo),
                'resend_at': flow['resend_at'].replace(tzinfo=now().tzinfo)}

    def send(self, flow, account, settings, mailer, resend=False):
        if account.get('email_verified'):
            raise HTTPException(409, 'This email is already verified. Sign in again.')
        if flow.get('otp_verified') or flow.get('otp_attempts', 0) >= 5:
            raise HTTPException(429, 'Verification attempts exhausted. Start again after the cooldown.')
        if not resend and flow.get('delivery') == 'sent' and flow['code_expires_at'].replace(tzinfo=now().tzinfo) > now():
            return self.receipt(flow)
        if flow.get('resend_at') and flow['resend_at'].replace(tzinfo=now().tzinfo) > now():
            raise HTTPException(429, 'Wait 60 seconds before requesting another code.')
        code = f'{randbelow(1000000):06d}'
        challenge = token_urlsafe(32)
        timestamp = now()
        changes = {'challenge_id': challenge, 'email': account['email'], 'delivery': 'sending',
                   'code_hash': keyed(settings.otp_secret, account['id'], account['email'], challenge, code),
                   'code_expires_at': timestamp + timedelta(minutes=10), 'resend_at': timestamp + timedelta(seconds=60),
                   'attempt_expires_at': timestamp + timedelta(minutes=30)}
        conditions = {'_id': flow['_id'], 'attempt': flow['attempt'], 'status': 'pending', 'otp_verified': {'$ne': True},
                      '$or': [{'resend_at': {'$exists': False}}, {'resend_at': {'$lte': timestamp}}]}
        selected = self.flows.find_one_and_update(conditions, {'$set': changes}, return_document=ReturnDocument.AFTER)
        if selected is None:
            raise HTTPException(409, 'Another verification request is active. Please wait or start again.')
        try:
            self.limit(settings.otp_secret, 'delivery', account['email'], 5)
            if mailer is None:
                raise HTTPException(503, 'Email delivery unavailable. Please retry.')
            mailer.send_otp(account['email'], code)
        except Exception:
            self.flows.update_one({'_id': flow['_id'], 'challenge_id': challenge, 'status': 'pending'},
                                  {'$set': {'delivery': 'failed', 'resend_at': now()}, '$unset': {'code_hash': ''}})
            raise
        delivered = self.flows.update_one({'_id': flow['_id'], 'attempt': flow['attempt'], 'challenge_id': challenge, 'status': 'pending'},
                                         {'$set': {'delivery': 'sent'}})
        if not delivered.matched_count:
            raise HTTPException(409, 'Verification was cancelled. Start again.')
        return self.receipt(selected)

    def consume(self, data, flow, account, settings):
        receipt = keyed(settings.otp_secret, data.challenge_id, data.code, digest(data.session_token))
        if flow.get('verification_receipt') == receipt and flow.get('otp_verified'):
            return flow
        if flow['status'] != 'pending' or flow.get('challenge_id') != data.challenge_id:
            raise HTTPException(409, 'This code is no longer current. Use the latest email.')
        code_hash = keyed(settings.otp_secret, account['id'], account['email'], data.challenge_id, data.code)
        conditions = {'_id': flow['_id'], 'attempt': flow['attempt'], 'status': 'pending', 'challenge_id': data.challenge_id,
                      'delivery': 'sent', 'code_expires_at': {'$gt': now()},
                      '$or': [{'otp_attempts': {'$exists': False}}, {'otp_attempts': {'$lt': 5}}]}
        self.limit(settings.otp_secret, 'verification', account['email'], 25)
        consumed = self.flows.find_one_and_update({**conditions, 'code_hash': code_hash},
            {'$set': {'otp_verified': True, 'verification_receipt': receipt}, '$unset': {'code_hash': ''}}, return_document=ReturnDocument.AFTER)
        if consumed:
            return consumed
        latest = self.flows.find_one({'_id': flow['_id']})
        if latest and latest.get('verification_receipt') == receipt and latest.get('otp_verified'):
            return latest
        self.flows.update_one({**conditions, 'code_hash': {'$ne': code_hash}, 'otp_verified': {'$ne': True}}, {'$inc': {'otp_attempts': 1}})
        raise HTTPException(400, 'Code incorrect, expired or exhausted. Use the latest email or request another code.')
