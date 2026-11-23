from copy import deepcopy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from elo_shared.runtime import Problem
from pymongo.errors import DuplicateKeyError

from app.schemas import Slot, SlotCreate

SINGAPORE = ZoneInfo('Asia/Singapore')
RETRIES = 12


def busy():
    return Problem('Another change is in progress. Retry this action.', 409, 'busy')


def save_revision(collection, previous, updated, *, condition=None):
    updated['version'] = previous['version'] + 1 if previous else 1
    if previous is None:
        try:
            collection.insert_one(updated)
        except DuplicateKeyError:
            return False
        return True
    predicate = {'_id': previous['_id'], 'version': previous['version']}
    if condition is not None:
        predicate['$expr'] = condition
    try:
        return collection.replace_one(predicate, updated).matched_count == 1
    except DuplicateKeyError:
        return False


def view_slot(slot):
    return Slot(id=slot['id'], version=slot['version'], starts_at=slot['starts_at'], durations=slot['durations'])


class Schedules:
    def __init__(self, collection):
        self.collection = collection

    def ensure_indexes(self):
        self.collection.create_index('slots.id', unique=True)
        self.collection.create_index([('expert_id', 1), ('date', 1)])

    def find(self, slot_id):
        schedule = self.collection.find_one({'slots.id': slot_id})
        if schedule is None:
            return None, None
        return schedule, self.slot(schedule, slot_id)

    @staticmethod
    def slot(schedule, slot_id):
        return next(slot for slot in schedule['slots'] if slot['id'] == slot_id)

    def open_slots(self, expert_ids):
        now = datetime.now(UTC)
        schedules = self.collection.find({
            'expert_id': {'$in': list(expert_ids)},
            'date': {'$gte': now.astimezone(SINGAPORE).date().isoformat()},
        })
        return [
            (schedule['expert_id'], slot)
            for schedule in schedules for slot in schedule['slots']
            if slot['starts_at'] > now and not slot['closed'] and slot['held_by'] is None
        ]

    def publish(self, expert_id: str, command: SlotCreate) -> Slot:
        starts_at = command.starts_at.astimezone(UTC)
        ends_at = starts_at + timedelta(minutes=max(command.durations))
        date = starts_at.astimezone(SINGAPORE).date()
        if (ends_at - timedelta(milliseconds=1)).astimezone(SINGAPORE).date() != date:
            raise Problem('Choose a window within one Singapore day.', 422, 'slot_date')
        slot_id = str(command.mutation_id)
        schedule_id = f'{expert_id}:{date.isoformat()}'
        for _ in range(RETRIES):
            existing_schedule, existing = self.find(slot_id)
            if existing is not None:
                if (existing_schedule['_id'], existing['starts_at'], existing['durations']) == (
                    schedule_id, starts_at, list(command.durations),
                ):
                    return view_slot(existing)
                raise Problem('This action ID was already used for another appointment.', 409, 'mutation_reused')
            if starts_at <= datetime.now(UTC):
                raise Problem('Choose a future start time.', 422, 'slot_time')
            previous = self.collection.find_one({'_id': schedule_id})
            updated = deepcopy(previous) if previous else {
                '_id': schedule_id, 'expert_id': expert_id, 'date': date.isoformat(), 'slots': [],
            }
            if any(slot['id'] == slot_id for slot in updated['slots']):
                continue
            if any(slot['starts_at'] < ends_at and starts_at < slot['ends_at'] for slot in updated['slots']):
                raise Problem('This window overlaps an existing appointment.', 409, 'slot_overlap')
            new_slot = {
                'id': slot_id, 'version': 1, 'starts_at': starts_at, 'ends_at': ends_at,
                'durations': list(command.durations), 'closed': False, 'held_by': None,
            }
            updated['slots'].append(new_slot)
            if save_revision(self.collection, previous, updated):
                return view_slot(new_slot)
        raise busy()

    def claim(self, booking):
        for _ in range(RETRIES):
            schedule, slot = self.find(booking['slot_id'])
            if slot is None:
                return False
            if slot['held_by'] == booking['id']:
                return True
            if slot['version'] != booking['slot_version'] or slot['closed'] or slot['held_by'] is not None:
                return False
            starts_at = slot['starts_at']
            updated = deepcopy(schedule)
            next_slot = self.slot(updated, slot['id'])
            next_slot['version'] += 1
            next_slot['held_by'] = booking['id']
            if save_revision(self.collection, schedule, updated, condition={'$gt': [starts_at, '$$NOW']}):
                return True
            next_slot['held_by'] = None
            next_slot['closed'] = True
            if save_revision(self.collection, schedule, updated, condition={'$lte': [starts_at, '$$NOW']}):
                return False
        raise busy()

    def release(self, booking):
        for _ in range(RETRIES):
            schedule, slot = self.find(booking['slot_id'])
            if slot is None or slot['held_by'] != booking['id']:
                return
            updated = deepcopy(schedule)
            next_slot = self.slot(updated, slot['id'])
            next_slot['version'] += 1
            next_slot['held_by'] = None
            if save_revision(self.collection, schedule, updated):
                return
        raise busy()
