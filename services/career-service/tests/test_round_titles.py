import asyncio
import copy
import json
import os
from datetime import timedelta
from threading import Lock
from uuid import uuid4
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.ai.adapter import AIAdapter
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.errors import AIError
from app.repositories.goals import now
from app.schemas.opportunity import Finding
from app.schemas.round_titles import RoundTitles
from app.workflows.round_titles import prepare

LONG = 'Technical interview with the hiring manager'


class Rows:
    def __init__(self):
        self.data = {}
        self.lock = Lock()

    def update_one(self, query, update, upsert=False):
        with self.lock:
            key = query['_id']
            created = key not in self.data and upsert
            if created:
                self.data[key] = {'_id': key, **copy.deepcopy(update.get('$setOnInsert', {}))}
            row = self.data.get(key)
            if row and all(row.get(k) == v for k, v in query.items()):
                row.update(copy.deepcopy(update.get('$set', {})))
            return NS(upserted_id=key if created else None)

    def find_one(self, query):
        with self.lock:
            return copy.deepcopy(self.data.get(query['_id']))


def categories(name=LONG):
    finding = Finding(finding_id='f'+'1'*16, field='round_format', value='A short call with a manager.',
        confidence='medium', evidence_type='candidate_reported', source_ids=['s1'], quotes=['A short call with a manager.'],
        scope='exact', last_verified_at=now(), round_number=2, round_name=name)
    return {'interview_intelligence': {'status': 'completed', 'findings': [finding.model_dump(mode='json')]}}


def request(output=None, error=None, delay=0):
    calls = []
    rows = Rows()

    async def generate(body, operation, **kwargs):
        calls.append(body)
        if delay:
            await asyncio.sleep(delay)
        if error:
            raise error
        value = output or RoundTitles(titles=[{'round_number': 2, 'title': 'Technical interview'}])
        kwargs['validate_output'](value)
        return NS(data=value)

    state = NS(ai=NS(generate=generate, context_enabled=True), opportunities=NS(store=NS(rows=rows)))
    return NS(app=NS(state=state)), calls, rows


def test_short_names_need_no_model_or_cache_write():
    req, calls, rows = request()
    assert asyncio.run(prepare(req, 'owner', categories('Technical interview'))) == {'2': 'Technical interview'}
    assert not calls and not rows.data


def test_long_names_are_shortened_once_without_rewriting_the_research():
    req, calls, rows = request()
    values = categories()
    original = copy.deepcopy(values)
    assert asyncio.run(prepare(req, 'owner', values)) == {'2': 'Technical interview'}
    assert asyncio.run(prepare(req, 'another-owner', values)) == {'2': 'Technical interview'}
    assert len(calls) == 1 and len(rows.data) == 1
    assert calls[0].stage == 'interview_round_titles'
    assert json.loads(calls[0].context) == {'rounds': [{'round_number': 2, 'names': [LONG]}]}
    assert values == original


def test_pending_research_does_not_start_title_generation():
    req, calls, rows = request()
    assert asyncio.run(prepare(req, 'owner', categories(), finished=False)) == {'2': 'Round 2'}
    assert not calls and not rows.data


def test_concurrent_reads_share_one_shortening_pass():
    req, calls, _ = request(delay=0.02)

    async def run():
        return await asyncio.gather(*(prepare(req, str(i), categories()) for i in range(4)))

    assert asyncio.run(run()) == [{'2': 'Technical interview'}] * 4
    assert len(calls) == 1


@pytest.mark.parametrize('error', [AIError('unavailable'), AIError('rate_limited'), RuntimeError('synthetic provider failure')])
def test_failed_shortening_uses_a_short_fallback_and_is_not_repeated(error):
    req, calls, _ = request(error=error)
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert len(calls) == 1


def test_unexpected_round_numbers_are_rejected_without_a_second_pass():
    req, calls, _ = request(output=RoundTitles(titles=[{'round_number': 1, 'title': 'Other interview'}]))
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert len(calls) == 1


def test_short_title_schema_rejects_overlong_or_empty_labels():
    for title in ['This title has four words', '', 'Two\nlines']:
        with pytest.raises(ValidationError):
            RoundTitles(titles=[{'round_number': 2, 'title': title}])


def test_storage_failure_does_not_make_an_uncached_model_call():
    req, calls, rows = request()

    def unavailable(*args, **kwargs):
        raise PyMongoError('synthetic storage failure')

    rows.update_one = unavailable
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert not calls


def test_expired_attempt_is_not_reissued():
    req, calls, rows = request(error=AIError('unavailable'))
    asyncio.run(prepare(req, 'owner', categories()))
    for value in rows.data.values():
        value.update(state='running', deadline=now()-timedelta(seconds=1))
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert len(calls) == 1


def test_provider_request_is_small_structured_title_only_json():
    adapter = AIAdapter(AISettings(provider='compatible', response_mode='json_schema'), None)
    payload = adapter._payload(AIInput(stage='interview_round_titles', context=json.dumps({'rounds': [{'round_number': 2, 'names': [LONG]}]})))
    assert payload['response_format']['json_schema']['name'] == 'interview_round_titles'
    assert payload['max_tokens'] == 512
    assert 'one to three words' in payload['messages'][0]['content']
    assert 'Technical interview with the hiring manager' in payload['messages'][1]['content']


def test_invalid_long_model_title_is_not_repaired_with_another_call():
    from app.schemas.round_titles import RoundTitle
    bad = RoundTitles.model_construct(titles=[RoundTitle.model_construct(round_number=2, title='This title has four words')])
    req, calls, _ = request(output=bad)
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert len(calls) == 1


def test_multiple_long_names_share_one_batch_and_short_names_are_left_alone():
    values = categories()
    original = values['interview_intelligence']['findings'][0]
    values['interview_intelligence']['findings'].extend([
        {**original, 'finding_id': 'f'+'2'*16, 'round_number': 3, 'round_name': 'Final interview with the department manager'},
        {**original, 'finding_id': 'f'+'3'*16, 'round_number': 1, 'round_name': 'HR call'},
    ])
    req, calls, _ = request(output=RoundTitles(titles=[{'round_number': 2, 'title': 'Technical interview'}, {'round_number': 3, 'title': 'Final interview'}]))
    assert asyncio.run(prepare(req, 'owner', values)) == {'1': 'HR call', '2': 'Technical interview', '3': 'Final interview'}
    assert len(calls) == 1
    assert {row['round_number'] for row in json.loads(calls[0].context)['rounds']} == {2, 3}


def test_api_projection_exposes_titles_without_touching_the_saved_findings():
    from app.schemas.opportunity_api import OpportunityView
    values = categories()
    view = OpportunityView(available=True, job_id='job', career_target_id='1'*24, status='completed',
        categories=values, round_titles={'2': 'Technical interview'}, error_code=None)
    assert view.categories['interview_intelligence'].findings[0].round_name == LONG
    assert view.round_titles == {'2': 'Technical interview'}


def test_mongodb_claims_allow_one_pass_across_concurrent_readers():
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri:
        pytest.skip('Requires disposable MongoDB')
    mongo = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=3000)
    db = mongo['elo_round_titles_test_' + uuid4().hex]
    req, calls, _ = request(delay=0.02)
    req.app.state.opportunities.store.rows = db.research_contexts

    async def run():
        return await asyncio.gather(*(prepare(req, str(i), categories()) for i in range(4)))

    try:
        assert asyncio.run(run()) == [{'2': 'Technical interview'}] * 4
        assert asyncio.run(prepare(req, 'next-reader', categories())) == {'2': 'Technical interview'}
        assert len(calls) == 1
        assert db.research_contexts.count_documents({'kind': 'round_titles', 'state': 'done'}) == 1
    finally:
        mongo.drop_database(db.name)
        mongo.close()


def test_disconnecting_a_reader_does_not_cancel_the_shared_title_result():
    req, calls, _ = request(delay=0.03)

    async def run():
        first = asyncio.create_task(prepare(req, 'first-owner', categories()))
        while not calls:
            await asyncio.sleep(0.001)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return await prepare(req, 'next-owner', categories())

    assert asyncio.run(run()) == {'2': 'Technical interview'}
    assert len(calls) == 1


def test_malformed_cached_title_data_does_not_break_research_reads():
    req, calls, rows = request()
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Technical interview'}
    for value in rows.data.values():
        value['titles'] = {'not-a-round': 'This title has too many words'}
    assert asyncio.run(prepare(req, 'owner', categories())) == {'2': 'Round 2'}
    assert len(calls) == 1
