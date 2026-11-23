import logging
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from elo_shared.runtime import Problem, digest
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.schedules import RETRIES, Schedules, busy, save_revision, view_slot
from app.schemas import Access, Booking, Expert, Recommendation, Report, ReportReceipt

logger = logging.getLogger(__name__)
UNPUBLISHED = ('submitting', 'slot_unavailable')
REFUNDED = ('declined', 'expired', 'slot_unavailable')


def missing_booking():
    return Problem('Chat request not found.', 404, 'booking_not_found')


def mutation_key(wallet, kind, command):
    key = str(command.mutation_id)
    payload = digest([kind, command.model_dump(mode='json')])
    existing = wallet['receipts'].get(key)
    if existing is not None and existing['payload'] != payload:
        raise Problem('This action ID was used with different details.', 409, 'mutation_reused')
    return key, payload, existing


def booking_view(booking, *, for_expert=False):
    fields = {key: booking[key] for key in Booking.model_fields}
    if for_expert:
        fields.update(prep_done=False, notes='')
    return Booking(**fields)


def new_wallet(account_id):
    return {'_id': account_id, 'enabled': False, 'credits': 0, 'bookings': [], 'receipts': {}}


def get_booking(wallet, booking_id):
    return next(booking for booking in wallet['bookings'] if booking['id'] == booking_id)


def advance_booking(wallet, booking_id, status):
    updated = deepcopy(wallet)
    booking = get_booking(updated, booking_id)
    booking.update(status=status, version=booking['version'] + 1)
    if status in REFUNDED:
        updated['credits'] += booking['credits']
        booking['release_pending'] = status != 'slot_unavailable'
    return updated, booking


def order_by_time(bookings):
    return sorted(bookings, key=lambda booking: booking['starts_at'])


class Socials:
    def __init__(self, database):
        self.wallets = database.wallets
        self.experts = database.experts
        self.schedules = Schedules(database.schedules)
        self.reports = database.reports

    def ensure_indexes(self):
        self.wallets.create_index('bookings.id')
        self.wallets.create_index('bookings.expert_account_id')
        self.wallets.create_index('bookings.status')
        self.wallets.create_index('bookings.release_pending')
        self.experts.create_index('account_id')
        self.schedules.ensure_indexes()
        self.reports.create_index([('reporter_id', 1), ('mutation_id', 1)], unique=True)
        self.reports.create_index('created_at')

    def put_expert(self, expert_id, command):
        fields = command.model_dump()
        try:
            expert = self.experts.find_one_and_update(
                {'_id': expert_id, 'account_id': command.account_id},
                {'$set': fields}, upsert=True, return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError as error:
            raise Problem('Expert account assignments are fixed.', 409, 'expert_assignment') from error
        return self.expert_view(expert, len(self.schedules.open_slots([expert_id])))

    def expert(self, expert_id, *, active=True):
        criteria = {'_id': expert_id}
        if active:
            criteria['active'] = True
        expert = self.experts.find_one(criteria)
        if expert is None:
            raise Problem('Expert not found.', 404, 'expert_not_found')
        return expert

    def publish_slot(self, expert_id, command):
        self.expert(expert_id, active=False)
        return self.schedules.publish(expert_id, command)

    def access(self, account_id):
        wallet = self.wallets.find_one({'_id': account_id}) or new_wallet(account_id)
        return Access(access='enabled' if wallet['enabled'] else 'locked', credits=wallet['credits'])

    def set_access(self, account_id, command):
        for _ in range(RETRIES):
            previous = self.wallets.find_one({'_id': account_id})
            wallet = deepcopy(previous) if previous else new_wallet(account_id)
            key, payload, existing = mutation_key(wallet, 'access', command)
            if existing is not None:
                return self.access(account_id)
            wallet['enabled'] = command.enabled
            wallet['credits'] += command.credits
            wallet['receipts'][key] = {'payload': payload}
            if save_revision(self.wallets, previous, wallet):
                return Access(access='enabled' if wallet['enabled'] else 'locked', credits=wallet['credits'])
        raise busy()

    @staticmethod
    def expert_view(expert, open_slots):
        fields = {key: expert[key] for key in ('name', 'role', 'field', 'organisation', 'linkedin_url')}
        return Expert(id=expert['_id'], open_slots=open_slots, **fields)

    def workspace(self, account_id, goal: dict):
        wallet = self.wallets.find_one({'_id': account_id}) or new_wallet(account_id)
        enabled = wallet['enabled']
        experts = list(self.experts.find({'active': True}).sort([('field', 1), ('name', 1)])) if enabled else []
        counts = Counter(expert_id for expert_id, _ in self.schedules.open_slots(expert['_id'] for expert in experts))
        recommendation = self.recommend(experts, counts, goal)
        return {
            'access': 'enabled' if enabled else 'locked',
            'credits': wallet['credits'],
            'experts': [self.expert_view(expert, counts[expert['_id']]) for expert in experts],
            'recommendation': recommendation,
            'bookings': [booking_view(booking) for booking in reversed(wallet['bookings'])],
            'expert_inbox': self.experts.find_one({'account_id': account_id}, {'_id': 1}) is not None,
        }

    @staticmethod
    def recommend(experts, counts, goal):
        role = goal.get('role')
        if not isinstance(role, str) or not role.strip() or len(role.strip()) > 120:
            return None

        def normal(value):
            return ' '.join(value.casefold().split()) if isinstance(value, str) else ''

        matches = []
        for expert in experts:
            field_match = normal(goal.get('field')) == normal(expert['field'])
            role_match = normal(role) in {normal(value) for value in [expert['role'], *expert['aliases']]}
            if role_match or field_match:
                matches.append((role_match, counts[expert['_id']] > 0, expert['_id']))
        if not matches:
            return None
        return Recommendation(expert_id=max(matches)[2], role=role.strip())

    def slots(self, account_id, expert_id):
        if self.access(account_id).access != 'enabled':
            raise Problem('Chats & Socials access is required.', 403, 'access_required')
        self.expert(expert_id)
        return [view_slot(slot) for slot in order_by_time(slot for _, slot in self.schedules.open_slots([expert_id]))]

    def request_chat(self, account, command):
        account_id = account['id']
        for _ in range(RETRIES):
            previous = self.wallets.find_one({'_id': account_id})
            if previous is None:
                raise Problem('Chats & Socials access is required.', 403, 'access_required')
            updated = deepcopy(previous)
            key, payload, existing = mutation_key(updated, 'request', command)
            if existing is not None:
                return booking_view(self.finish_submission(account_id, existing['booking_id']))
            if not updated['enabled']:
                raise Problem('Chats & Socials access is required.', 403, 'access_required')
            credits = command.duration_minutes // 30
            if updated['credits'] < credits:
                raise Problem('You need more chat credits for this duration.', 409, 'insufficient_credits')
            expert = self.expert(command.expert_id)
            schedule, slot = self.schedules.find(str(command.slot_id))
            if schedule is None or schedule['expert_id'] != expert['_id'] or command.duration_minutes not in slot['durations']:
                raise Problem('Choose a time and duration offered by this expert.', 422, 'invalid_slot')
            if slot['version'] != command.slot_version or slot['closed'] or slot['held_by'] is not None:
                raise Problem('This time is unavailable. Choose another time.', 409, 'slot_unavailable')
            booking_id = str(uuid4())
            booking = {
                'id': booking_id, 'version': 1, 'expert_id': expert['_id'], 'expert_name': expert['name'],
                'expert_account_id': expert['account_id'], 'starts_at': slot['starts_at'],
                'duration_minutes': command.duration_minutes, 'status': 'submitting',
                'question': command.question, 'meeting_url': None, 'credits': credits, 'prep_done': False,
                'notes': '', 'member_name': account['name'][:120], 'slot_id': slot['id'],
                'slot_version': command.slot_version, 'release_pending': False,
            }
            updated['bookings'].append(booking)
            updated['receipts'][key] = {'payload': payload, 'booking_id': booking_id}
            updated['credits'] -= credits
            if save_revision(self.wallets, previous, updated):
                return booking_view(self.finish_submission(account_id, booking_id))
        raise busy()

    def finish_submission(self, owner_id, booking_id):
        for _ in range(RETRIES):
            wallet = self.wallets.find_one({'_id': owner_id})
            booking = get_booking(wallet, booking_id)
            if booking['status'] != 'submitting':
                return booking
            status = 'requested' if self.schedules.claim(booking) else 'slot_unavailable'
            updated, published = advance_booking(wallet, booking_id, status)
            if save_revision(self.wallets, wallet, updated):
                return published
        raise busy()

    def assigned(self, account_id):
        if self.experts.find_one({'account_id': account_id}, {'_id': 1}) is None:
            raise Problem('A Chats & Socials expert account is required.', 403, 'expert_required')
        return [
            booking_view(booking, for_expert=True)
            for booking in order_by_time(
                booking
                for wallet in self.wallets.find({'bookings.expert_account_id': account_id})
                for booking in wallet['bookings']
                if booking['expert_account_id'] == account_id and booking['status'] in ('requested', 'accepted')
            )
        ]

    def agenda(self, account_id):
        wallet = self.wallets.find_one({'_id': account_id}) or new_wallet(account_id)
        return [booking_view(booking) for booking in order_by_time(
            item for item in wallet['bookings'] if item['status'] == 'accepted'
        )]

    def decision(self, account_id, booking_id, command):
        for _ in range(RETRIES):
            wallet = self.wallets.find_one({'bookings.id': booking_id})
            if wallet is None:
                raise missing_booking()
            booking = get_booking(wallet, booking_id)
            if booking['expert_account_id'] != account_id or booking['status'] in UNPUBLISHED:
                raise missing_booking()
            key, payload, existing = mutation_key(wallet, f'decision:{booking_id}', command)
            if existing is not None:
                return booking_view(booking, for_expert=True)
            if booking['version'] != command.expected_version or booking['status'] != 'requested':
                raise Problem('This request has changed. Refresh to see its latest status.', 409, 'booking_changed')
            status = 'accepted' if command.decision == 'accept' else 'declined'
            updated, decided = advance_booking(wallet, booking_id, status)
            decided['meeting_url'] = command.meeting_url
            updated['receipts'][key] = {'payload': payload}
            condition = {'$gt': [booking['starts_at'], '$$NOW']}
            if save_revision(self.wallets, wallet, updated, condition=condition):
                if decided['release_pending']:
                    self.finish_release(wallet['_id'], booking_id)
                return booking_view(decided, for_expert=True)
            self.expire(wallet, booking)
        raise busy()

    def expire(self, wallet, booking):
        updated, _ = advance_booking(wallet, booking['id'], 'expired')
        condition = {'$lte': [booking['starts_at'], '$$NOW']}
        if save_revision(self.wallets, wallet, updated, condition=condition):
            self.finish_release(wallet['_id'], booking['id'])

    def finish_release(self, owner_id, booking_id):
        for _ in range(RETRIES):
            wallet = self.wallets.find_one({'_id': owner_id})
            updated = deepcopy(wallet)
            booking = get_booking(updated, booking_id)
            if not booking['release_pending']:
                return
            self.schedules.release(booking)
            booking['release_pending'] = False
            if save_revision(self.wallets, wallet, updated):
                return
        raise busy()

    def follow_up(self, account_id, booking_id, command):
        for _ in range(RETRIES):
            wallet = self.wallets.find_one({'_id': account_id, 'bookings.id': booking_id})
            if wallet is None:
                raise missing_booking()
            updated = deepcopy(wallet)
            booking = get_booking(updated, booking_id)
            key, payload, existing = mutation_key(updated, f'follow_up:{booking_id}', command)
            if existing is not None:
                return booking_view(booking)
            if booking['version'] != command.expected_version or booking['status'] != 'accepted':
                raise Problem('This chat has changed. Refresh before saving.', 409, 'booking_changed')
            booking.update(prep_done=command.prep_done, notes=command.notes, version=booking['version'] + 1)
            updated['receipts'][key] = {'payload': payload}
            if save_revision(self.wallets, wallet, updated):
                return booking_view(booking)
        raise busy()

    def report(self, account_id, booking_id, command):
        wallet = self.wallets.find_one({'bookings.id': booking_id})
        if wallet is None:
            raise missing_booking()
        booking = get_booking(wallet, booking_id)
        if account_id not in (wallet['_id'], booking['expert_account_id']) or booking['status'] in UNPUBLISHED:
            raise missing_booking()
        identity = {'reporter_id': account_id, 'mutation_id': str(command.mutation_id)}
        row = {
            **identity, '_id': str(uuid4()), 'booking_id': booking_id,
            'reason': command.reason, 'created_at': datetime.now(UTC),
        }
        try:
            self.reports.insert_one(row)
        except DuplicateKeyError:
            row = self.reports.find_one(identity)
            if (row['booking_id'], row['reason']) != (booking_id, command.reason):
                raise Problem('This action ID was used with different details.', 409, 'mutation_reused')
        return ReportReceipt(id=row['_id'])

    def report_queue(self):
        return [
            Report(id=row['_id'], **{key: row[key] for key in ('booking_id', 'reporter_id', 'reason', 'created_at')})
            for row in self.reports.find().sort('created_at', -1).limit(100)
        ]

    def recover(self):
        now = datetime.now(UTC)
        for wallet in self.wallets.find({'$or': [
            {'bookings.status': 'submitting'},
            {'bookings.release_pending': True},
            {'bookings': {'$elemMatch': {'status': 'requested', 'starts_at': {'$lte': now}}}},
        ]}):
            for booking in wallet['bookings']:
                try:
                    if booking['status'] == 'submitting':
                        self.finish_submission(wallet['_id'], booking['id'])
                    elif booking['release_pending']:
                        self.finish_release(wallet['_id'], booking['id'])
                    elif booking['status'] == 'requested' and booking['starts_at'] <= now:
                        self.expire(wallet, booking)
                except Problem:
                    logger.warning('A chat request is still awaiting recovery.')
