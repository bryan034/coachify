"""Request-time public board reads. Listings are never persisted or served from a catalogue."""
import os
import re
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Lock

import httpx
from elo_shared.runtime import Problem

from app.normalise import build, source_id
from app.providers import USER_AGENT, ProviderUnavailable, fetch_json, read_board
from app.store import EPOCH, _decode_cursor, _encode_cursor, _posting_view
from app.registry import load_sources


class LiveJobs:
    def __init__(self, sources=None, fetch=None, clock=None):
        self.sources = ([] if os.getenv('ELO_SYNTHETIC_TEST_FIXTURES') == '1' else load_sources()) if sources is None else sources
        self.fetch = fetch
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = Lock()
        self._flight = None

    def read(self, query=None):
        # All routes share public board data, never owner-specific application records.
        # Keep only an active operation: completed results are not cached.
        with self._lock:
            leader = self._flight is None
            if leader:
                self._flight = Future()
            flight = self._flight
        if not leader:
            return flight.result()
        try:
            result = self._read_boards()
            flight.set_result(result)
            return result
        except BaseException as error:
            flight.set_exception(error)
            raise
        finally:
            with self._lock:
                self._flight = None

    def _read_boards(self):
        sources = self.sources
        now = self.clock()
        if not sources:
            return [], [], now
        deadline = time.monotonic() + 20
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=5, headers={'User-Agent': USER_AGENT}) as client:
            fetch = self.fetch or (lambda url: fetch_json(client, url))
            def board(source):
                if time.monotonic() >= deadline:
                    return [], [source_id(source)]
                try:
                    records, rejected = read_board(source, fetch)
                    documents = [d for raw in records if (d := build(source, raw)) is not None]
                    return documents, [source_id(source)] if rejected or len(documents) != len(records) else []
                except ProviderUnavailable:
                    return [], [source_id(source)]
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(board, sources))
        rows = {d['_id']: d for documents, _ in results for d in documents}
        failures = [name for _, failed in results for name in failed]
        if len(failures) == len(sources) and not rows:
            raise Problem('Job sites could not be read. Retry shortly.', 503, 'providers_unavailable')
        for row in rows.values():
            estimated = row['posted_at'] is None or row['posted_at'] > now + timedelta(days=1)
            row.update(posted_at=EPOCH if estimated else row['posted_at'], posted_at_estimated=estimated, status='open')
        return list(rows.values()), failures, now

    def search(self, query, cursor=None, limit=20, ranking=None):
        boundary = _decode_cursor(cursor) if cursor and ranking is None else None
        rows, failures, now = self.read(query)
        def matches(row):
            if any(row[field] not in query[field]['$in'] for field in ('company', 'industry', 'job_type', 'workplace') if field in query):
                return False
            if any(not any(re.search(term['search_terms']['$regex'], word) for word in row['search_terms']) for term in query.get('$and', [])):
                return False
            dates = query.get('posted_at', {})
            # Retrieval time is not evidence of a posting date.
            if dates and row['posted_at_estimated']:
                return False
            return not (('$gte' in dates and row['posted_at'] < dates['$gte']) or ('$lt' in dates and row['posted_at'] >= dates['$lt']))
        if ranking is not None:
            import base64,json,hashlib
            from app.normalise import query_terms
            role_terms=set(query_terms(ranking.get('role','')))
            skills=ranking.get('skills',[])
            def matched(row):return [name for name in skills if query_terms(name) and all(term in row['search_terms'] for term in query_terms(name))]
            def order(row):
                title=set(query_terms(row['title']))
                return (len(title&role_terms)*4+len(matched(row)),row['posted_at'].isoformat(),row['_id'])
            signature=hashlib.sha256(json.dumps({'ranking':ranking,'query':query},sort_keys=True,default=str).encode()).hexdigest()[:12]
            rows=sorted((row for row in rows if matches(row)),key=order,reverse=True)
            total=len(rows)
            if cursor:
                try:
                    decoded=json.loads(base64.urlsafe_b64decode(cursor))
                    if decoded['v']!=1 or decoded['context']!=signature:raise ValueError
                    boundary=tuple(decoded['position'])
                except (ValueError,KeyError,TypeError):raise Problem('The recommended search changed. Start a new search.',409,'search_changed') from None
                rows=[row for row in rows if order(row)<boundary]
            page=rows[:limit]
            items=[{**_posting_view(row),'matched_skills':matched(row) if ranking.get('skills_available',True) else None,'match_basis':'Profile skill names appearing in listing text; not a competence assessment.'} for row in page]
            next_cursor=base64.urlsafe_b64encode(json.dumps({'v':1,'context':signature,'position':order(page[-1])}).encode()).decode() if len(rows)>limit else None
            return {'items':items,'total':total,'next_cursor':next_cursor,'unavailable_sources':failures,'retrieved_at':now}
        rows = sorted((r for r in rows if matches(r)), key=lambda r: (r['posted_at'], r['_id']), reverse=True)
        total = len(rows)
        if boundary:
            rows = [r for r in rows if (r['posted_at'], r['_id']) < boundary]
        page = rows[:limit]
        return {'items': [_posting_view(r) for r in page], 'total': total,
                'next_cursor': _encode_cursor(page[-1]) if len(rows) > limit else None,
                'unavailable_sources': failures, 'retrieved_at': now}

    def posting(self, identifier):
        rows, failures, _ = self.read()
        for row in rows:
            if row['_id'] == identifier:
                return _posting_view(row)
        if failures:
            raise Problem('Some job sites could not be checked. Retry shortly.', 503, 'providers_unavailable')
        raise Problem('This job is no longer listed.', 404, 'not_found')

    def filter_options(self):
        rows, failures, now = self.read()
        def counted(field):
            return [{'value': value, 'count': count} for value, count in sorted(Counter(r[field] for r in rows).items())]
        return {'job_types': counted('job_type'), 'industries': counted('industry'), 'workplaces': counted('workplace'),
                'companies': counted('company'), 'last_synced_at': None, 'retrieved_at': now, 'unavailable_sources': failures}
