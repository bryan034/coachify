"""Safe local diagnostic output distinguishes schema, scope and grounding."""
import json
import asyncio
from pathlib import Path
import runpy
import pytest
from app.ai.adapter import AIAdapter
from app.ai.config import AISettings

probe = runpy.run_path(str(Path(__file__).with_name('local_model_probe.py')))
inspect_response, main, parser = (probe[name] for name in ('inspect_response', 'main', 'parser'))

SOURCE = 'ExampleCo is hiring a Software Engineer Intern in Singapore.'


def response(identity, finish='stop'):
    return json.dumps({'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(identity)}}]}).encode()


@pytest.mark.parametrize('identity,expected', [
    ({'is_job_description': False}, (True, False, False, 'career_scope')),
    ({'is_job_description': True, 'evidence': [SOURCE]}, (True, True, True, None)),
    ({'is_job_description': True, 'evidence': ['A fabricated quote.']}, (True, True, False, 'provenance')),
    ({'role': 'Intern'}, (False, None, False, 'missing')),
])
def test_identity_diagnostic_checks_scope_and_exact_evidence(identity, expected):
    result = inspect_response(AIAdapter(AISettings(), None), response(identity), SOURCE)
    issue = result['validation'][0]['issue'] if result['validation'] else None
    assert (result['schema_valid'], result['is_job_description'], result['valid_job_identity'], issue) == expected
    assert SOURCE not in json.dumps(result)


def test_length_finish_remains_incomplete_even_with_valid_json():
    result = inspect_response(AIAdapter(AISettings(), None), response({'is_job_description': True}, finish='length'), SOURCE)
    assert not result['schema_valid']
    assert result['validation'] == [{'issue': 'incomplete_output'}]


@pytest.mark.parametrize('identity,violations', [
    ({'is_job_description': True}, [{'field':'evidence','issue':'missing_source_evidence'}]),
    ({'is_job_description': True, 'evidence':['PRIVATE invented quote']}, [{'field':'evidence.0','issue':'quote_not_in_source'}]),
    ({'is_job_description': True, 'evidence':[SOURCE], 'role':'PRIVATE invented role'}, [{'field':'role','issue':'identity_not_in_source'}]),
    ({'is_job_description': True, 'evidence':[SOURCE], 'field':'private@example.test'}, [{'field':'field','issue':'invalid_public_identity'}]),
])
def test_probe_identifies_grounding_failures_without_exposing_values(identity,violations):
    result=inspect_response(AIAdapter(AISettings(),None),response(identity),SOURCE)
    assert result['schema_valid'] and result['is_job_description']
    assert not result['valid_job_identity']
    assert result['validation']==[{'issue':'provenance','violations':violations}]
    assert 'PRIVATE' not in json.dumps(result) and 'private@example.test' not in json.dumps(result)


@pytest.mark.parametrize('message,reason', [
    ({'content': 'PRIVATE malformed response'}, 'json_syntax'),
    ({'content': None, 'reasoning_content': 'PRIVATE reasoning'}, 'response_envelope'),
    ({'content': '{"is_job_description":true,"is_job_description":false}'}, 'json_syntax'),
])
def test_probe_explains_transport_rejection_without_disclosing_model_output(message, reason):
    raw = json.dumps({'choices': [{'finish_reason': 'stop', 'message': message}]}).encode()
    result = inspect_response(AIAdapter(AISettings(), None), raw, SOURCE)
    assert result['validation'] == [{'issue': 'invalid_output', 'reason': reason}]
    assert not result['schema_valid']
    assert 'PRIVATE' not in json.dumps(result)


def test_dry_run_prints_payload_only_when_requested(tmp_path, capsys, monkeypatch):
    import httpx
    async def forbidden(*args, **kwargs):
        raise AssertionError('Dry run must not make HTTP requests.')
    monkeypatch.setattr(httpx.AsyncClient, 'post', forbidden)
    jd = tmp_path / 'public-jd.txt'
    jd.write_text(SOURCE, encoding='utf-8')
    assert parser().parse_args([]).timeout == 45
    args = ['--jd-file', str(jd), '--dry-run']
    asyncio.run(main(parser().parse_args(args)))
    assert SOURCE not in capsys.readouterr().out
    asyncio.run(main(parser().parse_args([*args, '--show-content'])))
    output = capsys.readouterr().out
    assert SOURCE in output
    assert 'document_type' in output
    assert '8192' in output


@pytest.mark.parametrize('cap',[4096,8192])
def test_probe_dry_run_reports_the_requested_output_budget(cap,capsys):
    asyncio.run(main(parser().parse_args(['--dry-run','--max-output-tokens',str(cap)])))
    report=json.loads(capsys.readouterr().out)
    assert report['max_tokens']==cap
    assert report['estimated_input_tokens']+cap+report['reserved_margin_tokens']<=report['context_tokens']


@pytest.mark.parametrize('failure',[None,'positive_rejected','negative_invalid_output'])
def test_live_suite_requires_all_positive_and_negative_cases_to_pass(failure,capsys,monkeypatch):
    from app.ai.adapter import AIError
    from app.ai.jd_scope import CareerScopeError,JobIdentity
    suite=probe['scope_suite'];cases=probe['synthetic_cases']();calls=[]
    expected={text:(name,accepted) for name,text,accepted in cases}
    async def fake_identify(adapter,text,owner):
        calls.append(text);name,accepted=expected[text]
        if failure=='negative_invalid_output' and name=='resume':raise AIError('invalid_output',reason='json_syntax')
        if not accepted or failure=='positive_rejected' and name=='long_ad':raise CareerScopeError()
        return JobIdentity(is_job_description=True,evidence=[text[:160]])
    monkeypatch.setitem(suite.__globals__,'identify_job',fake_identify)
    result=asyncio.run(suite(parser().parse_args(['--suite','--repeat','2'])))
    reports=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert result is (failure is None)
    assert reports[-1]=={'passed':16 if failure is None else 14,'total':16,'all_passed':failure is None}
    assert len(calls)==16
    assert all(text not in json.dumps(reports) for _,text,_ in cases)


def test_suite_cannot_turn_a_dry_run_into_live_requests():
    with pytest.raises(ValueError,match='no requests were sent'):
        asyncio.run(main(parser().parse_args(['--suite','--dry-run'])))
