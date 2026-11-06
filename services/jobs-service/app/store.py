"""Jobs-owned MongoDB records: public catalogue, per-board sync state and private applications."""
import base64
import binascii
import hashlib
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from elo_shared.runtime import Problem
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.normalise import job_link, plain_text, query_terms

CLOSE_AFTER_MISSED_SYNCS = 3
MAX_APPLICATIONS_PER_OWNER = 500
MAX_HISTORY = 50
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
# A word plus common endings, so "engineer" finds "engineers" without "intern" finding "international".
WORD_ENDINGS = '(?:s|es|ing|ed|er|ers)?'
INTERNAL_FIELDS = {'source_id', 'search_terms', 'first_seen_at', 'last_seen_at', 'closed_at', 'missed_syncs'}


def _encode_cursor(row):
    return base64.urlsafe_b64encode(f"{row['posted_at'].isoformat()}|{row['_id']}".encode()).decode()


def _decode_cursor(value):
    try:
        moment, identifier = base64.urlsafe_b64decode(value.encode()).decode().split('|')
        parsed = datetime.fromisoformat(moment)
        if parsed.tzinfo is None or not re.fullmatch(r'[0-9a-f]{32}', identifier):
            raise ValueError
        return parsed, identifier
    except (ValueError, binascii.Error, UnicodeError):
        raise Problem('This page of results is no longer valid. Search again.', 422, 'validation') from None


def search_filter(q=None, job_types=(), industries=(), workplaces=(), companies=(), posted_from=None, posted_to=None):
    query = {'status': 'open'}
    terms = query_terms(q or '')
    if terms:
        query['$and'] = [{'search_terms': {'$regex': f'^{re.escape(term)}{WORD_ENDINGS}$'}} for term in terms]
    for field, values in (('job_type', job_types), ('industry', industries), ('workplace', workplaces), ('company', companies)):
        if values:
            query[field] = {'$in': list(values)}
    posted = {}
    if posted_from:
        posted['$gte'] = posted_from
    if posted_to:
        posted['$lt'] = posted_to
    if posted:
        query['posted_at'] = posted
    return query


def _posting_view(row):
    return {'id': row['_id'], **{k: v for k, v in row.items() if k != '_id' and k not in INTERNAL_FIELDS}}


class JobsStore:
    def __init__(self, database, live=None):
        self.live = live
        self.postings = database.job_postings
        self.sources = database.job_sources
        self.applications = database.job_applications

    def ensure_indexes(self):
        if self.live is not None:
            self.applications.create_index([('user_id', ASCENDING), ('updated_at', DESCENDING)])
            return
        self.postings.create_index([('status', ASCENDING), ('posted_at', DESCENDING), ('_id', DESCENDING)])
        self.postings.create_index([('source_id', ASCENDING)])
        self.postings.create_index([('search_terms', ASCENDING)])
        self.applications.create_index([('user_id', ASCENDING), ('updated_at', DESCENDING)])

    # Search
    def search(self, query, cursor=None, limit=20):
        total = self.postings.count_documents(query)
        page = dict(query)
        if cursor:
            moment, identifier = _decode_cursor(cursor)
            page['$or'] = [{'posted_at': {'$lt': moment}}, {'posted_at': moment, '_id': {'$lt': identifier}}]
        rows = list(self.postings.find(page, {'search_terms': 0}).sort([('posted_at', DESCENDING), ('_id', DESCENDING)]).limit(limit + 1))
        more = len(rows) > limit
        rows = rows[:limit]
        return {'items': [_posting_view(r) for r in rows], 'total': total, 'next_cursor': _encode_cursor(rows[-1]) if more else None}

    def posting(self, identifier):
        row = self.postings.find_one({'_id': identifier}, {'search_terms': 0})
        if not row:
            raise Problem('This job is no longer listed.', 404, 'not_found')
        return _posting_view(row)

    def filter_options(self):
        def counted(field):
            rows = self.postings.aggregate([{'$match': {'status': 'open'}}, {'$group': {'_id': f'${field}', 'count': {'$sum': 1}}}])
            return sorted(({'value': r['_id'], 'count': r['count']} for r in rows), key=lambda o: (-o['count'], o['value']))
        latest = self.sources.find_one({'last_synced_at': {'$ne': None}}, {'last_synced_at': 1}, sort=[('last_synced_at', DESCENDING)])
        return {'job_types': counted('job_type'), 'industries': counted('industry'), 'workplaces': counted('workplace'),
                'companies': sorted(counted('company'), key=lambda o: o['value'].casefold()),
                'last_synced_at': latest['last_synced_at'] if latest else None}

    # Sync
    def claim_source(self, source_id, now, lease_seconds=600):
        """Atomic per-board lease, so several workers never sync one board at once."""
        self.sources.update_one({'_id': source_id}, {'$setOnInsert': {'failures': 0, 'next_attempt_at': EPOCH, 'lease_until': EPOCH, 'last_synced_at': None}}, upsert=True)
        token = str(uuid4())
        row = self.sources.find_one_and_update(
            {'_id': source_id, 'lease_until': {'$lte': now}, 'next_attempt_at': {'$lte': now}},
            {'$set': {'lease_until': now + timedelta(seconds=lease_seconds), 'lease_token': token}},
            return_document=ReturnDocument.AFTER)
        return row and row['lease_token']

    def finish_source(self, source_id, token, now, *, next_attempt_at, succeeded):
        update = {'$set': {'lease_until': EPOCH, 'lease_token': None, 'next_attempt_at': next_attempt_at}}
        if succeeded:
            update['$set'].update(failures=0, last_synced_at=now)
        else:
            update['$inc'] = {'failures': 1}
        self.sources.update_one({'_id': source_id, 'lease_token': token}, update)

    def failures(self, source_id):
        row = self.sources.find_one({'_id': source_id}, {'failures': 1})
        return row['failures'] if row else 0

    def publish(self, source_id, documents, now, *, close_missing):
        """Upsert a board's postings. Absent postings close only after repeated complete reads."""
        existing = {r['_id']: r for r in self.postings.find({'source_id': source_id}, {'first_seen_at': 1, 'status': 1, 'missed_syncs': 1})}
        for document in documents:
            first_seen = existing.get(document['_id'], {}).get('first_seen_at', now)
            estimated = document['posted_at'] is None or document['posted_at'] > now + timedelta(days=1)
            self.postings.replace_one({'_id': document['_id']}, {
                **document, 'posted_at': first_seen if estimated else document['posted_at'], 'posted_at_estimated': estimated,
                'status': 'open', 'first_seen_at': first_seen, 'last_seen_at': now, 'closed_at': None, 'missed_syncs': 0}, upsert=True)
        if close_missing:
            seen = {d['_id'] for d in documents}
            for identifier, row in existing.items():
                if identifier in seen or row.get('status') != 'open':
                    continue
                missed = row.get('missed_syncs', 0) + 1
                closing = {'status': 'closed', 'closed_at': now} if missed >= CLOSE_AFTER_MISSED_SYNCS else {}
                self.postings.update_one({'_id': identifier}, {'$set': {'missed_syncs': missed, **closing}})

    def remove_unlisted_sources(self, enabled_ids):
        """The off switch: a board removed from the registry leaves the catalogue on the next run."""
        enabled = list(enabled_ids)
        self.postings.delete_many({'source_id': {'$nin': enabled}})
        self.sources.delete_many({'_id': {'$nin': enabled}})

    # Applications
    def _application_view(self, row, statuses):
        fallback = 'unknown' if self.live or row.get('source') == 'link' else 'removed'
        return {'id': row['_id'], 'posting_status': statuses.get(row['posting_id'], fallback),
                **{k: v for k, v in row.items() if k not in ('_id', 'user_id')}}

    def list_applications(self, owner):
        rows = list(self.applications.find({'user_id': owner}).sort('updated_at', DESCENDING).limit(MAX_APPLICATIONS_PER_OWNER))
        statuses = {} if self.live else {r['_id']: r['status'] for r in self.postings.find({'_id': {'$in': [r['posting_id'] for r in rows]}}, {'status': 1})}
        return {'items': [self._application_view(r, statuses) for r in rows]}

    def create_application(self, owner, posting_id, now):
        """The identity comes from owner and posting, so a repeated save returns the same record."""
        identifier = hashlib.sha256(f'{owner}:{posting_id}'.encode()).hexdigest()[:32]
        existing = self.applications.find_one({'_id': identifier, 'user_id': owner})
        if existing and self.live:
            return self._application_view(existing, {})
        posting = self.live.posting(posting_id) if self.live else self.postings.find_one({'_id': posting_id})
        if not posting:
            raise Problem('This job is no longer listed.', 404, 'not_found')
        if existing:
            return self._application_view(existing, {posting_id: posting['status']})
        if self.applications.count_documents({'user_id': owner}) >= MAX_APPLICATIONS_PER_OWNER:
            raise Problem('You have reached the saved job limit. Remove a saved job and retry.', 413, 'application_capacity')
        row = {'_id': identifier, 'user_id': owner, 'posting_id': posting_id, 'version': 1, 'status': 'saved',
               'snapshot': {k: posting[k] for k in ('title', 'company', 'location', 'job_type', 'listing_url', 'apply_url')},
               'history': [{'status': 'saved', 'at': now}], 'created_at': now, 'updated_at': now}
        try:
            self.applications.insert_one(row)
        except DuplicateKeyError:
            row = self.applications.find_one({'_id': identifier, 'user_id': owner})
        return self._application_view(row, {posting_id: posting['status']})

    def save_link(self, owner, body, now):
        """Save a job found elsewhere. Saving the same link twice, or a listing already saved, returns that record."""
        url = job_link(body.url)
        if not url:
            raise Problem('Paste the full https:// link to the job.', 422, 'validation')
        title, company, location = (plain_text(value) for value in (body.title, body.company, body.location))
        if not title or not company:
            raise Problem('Add the job title and the employer.', 422, 'validation')
        existing = self.applications.find_one({'user_id': owner, 'snapshot.listing_url': url})
        if existing:
            return self._application_view(existing, {})
        if self.applications.count_documents({'user_id': owner}) >= MAX_APPLICATIONS_PER_OWNER:
            raise Problem('You have reached the saved job limit. Remove a saved job and retry.', 413, 'application_capacity')
        identifier = hashlib.sha256(f'{owner}:link:{url}'.encode()).hexdigest()[:32]
        row = {'_id': identifier, 'user_id': owner, 'posting_id': hashlib.sha256(f'link:{url}'.encode()).hexdigest()[:32],
               'source': 'link', 'version': 1, 'status': 'saved',
               'snapshot': {'title': title, 'company': company, 'location': location, 'job_type': body.job_type, 'listing_url': url, 'apply_url': url},
               'history': [{'status': 'saved', 'at': now}], 'created_at': now, 'updated_at': now}
        try:
            self.applications.insert_one(row)
        except DuplicateKeyError:
            row = self.applications.find_one({'_id': identifier, 'user_id': owner})
        return self._application_view(row, {})

    def update_application(self, owner, identifier, expected_version, status, now):
        row = self.applications.find_one_and_update(
            {'_id': identifier, 'user_id': owner, 'version': expected_version},
            {'$set': {'status': status, 'updated_at': now}, '$inc': {'version': 1},
             '$push': {'history': {'$each': [{'status': status, 'at': now}], '$slice': -MAX_HISTORY}}},
            return_document=ReturnDocument.AFTER)
        if row:
            posting = None if self.live else self.postings.find_one({'_id': row['posting_id']}, {'status': 1})
            return self._application_view(row, {row['posting_id']: posting['status']} if posting else {})
        self._raise_missing_or_changed(owner, identifier)

    def delete_application(self, owner, identifier, expected_version):
        if not self.applications.delete_one({'_id': identifier, 'user_id': owner, 'version': expected_version}).deleted_count:
            self._raise_missing_or_changed(owner, identifier)

    def _raise_missing_or_changed(self, owner, identifier):
        if self.applications.find_one({'_id': identifier, 'user_id': owner}, {'_id': 1}):
            raise Problem('This saved job changed in another session. Reload and retry.', 409, 'conflict')
        raise Problem('This saved job was not found.', 404, 'not_found')
