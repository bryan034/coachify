"""Legacy catalogue compatibility helpers. Not used by the live API or deployed Compose stack."""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.normalise import build, source_id
from app.providers import USER_AGENT, ProviderUnavailable, fetch_json, read_board
from app.registry import Source, load_sources
from app.store import JobsStore

log = logging.getLogger('elo.jobs.sync')
MAX_BACKOFF = timedelta(hours=24)
POLL_SECONDS = 300
PAUSE_BETWEEN_BOARDS_SECONDS = 1.0



def sync_source(store, source, fetch, now, interval):
    """Returns the number of Singapore postings published, or None when another worker holds or defers the board."""
    identifier = source_id(source)
    token = store.claim_source(identifier, now)
    if not token:
        return None
    try:
        records, rejected = read_board(source, fetch)
        documents = [d for d in (build(source, r) for r in records) if d is not None]
        rejected += len(records) - len(documents)
        # A record that failed validation might be one of the postings it would otherwise close.
        store.publish(identifier, documents, now, close_missing=rejected == 0)
    except ProviderUnavailable as error:
        delay = min(MAX_BACKOFF, interval * 2 ** store.failures(identifier))
        store.finish_source(identifier, token, now, next_attempt_at=now + delay, succeeded=False)
        log.warning('board %s unavailable: %s; retrying after %s', identifier, error, delay)
        return None
    store.finish_source(identifier, token, now, next_attempt_at=now + interval, succeeded=True)
    log.info('board %s published=%d rejected=%d', identifier, len(documents), rejected)
    return len(documents)


def sync_all(store, sources, fetch, interval, clock=lambda: datetime.now(timezone.utc), pause=time.sleep):
    store.remove_unlisted_sources([source_id(s) for s in sources])
    published = 0
    for source in sources:
        count = sync_source(store, source, fetch, clock(), interval)
        if count is not None:
            published += count
            pause(PAUSE_BETWEEN_BOARDS_SECONDS)
    return published


def interval_from_environment():
    hours = float(os.getenv('JOBS_SYNC_INTERVAL_HOURS', '6'))
    if not 1 <= hours <= 168:
        raise ValueError('JOBS_SYNC_INTERVAL_HOURS must be between 1 and 168.')
    return timedelta(hours=hours)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    interval = interval_from_environment()
    sources = load_sources()
    mongo = MongoClient(os.environ['MONGODB_URI'], tz_aware=True, serverSelectionTimeoutMS=5000)
    store = JobsStore(mongo[os.getenv('MONGODB_DATABASE', 'elo_jobs')])
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=30, headers={'User-Agent': USER_AGENT}) as client:
        fetch = lambda url: fetch_json(client, url)
        while True:
            try:
                store.ensure_indexes()
                sync_all(store, sources, fetch, interval)
            except PyMongoError as error:
                log.warning('storage unavailable: %s', type(error).__name__)
            time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
