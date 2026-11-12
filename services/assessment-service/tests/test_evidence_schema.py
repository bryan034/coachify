import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from elo_shared.runtime import Model, Problem
from app.schemas import batch_schema


EVIDENCE={'cv:item1:claim:0':{'ref':'cv:item1:claim:0','text':'I used Python.','attribution':'personal'}}
REQUIREMENTS=[{'ref':'job:req1','kind':'job_skill','name':'Python'}]


def output(refs):
    return {'outcomes':[{'requirement_ref':'job:req1','components':[{
        'dimension':'capability','status':'uncertain','explanation':'Needs review.',
        'evidence_refs':refs}], 'mapping_method':'unresolved','mapping_reason':'Needs review.'}]}


@pytest.mark.parametrize('ref',['item1','cv:item1','job:req1','language.python','invented'])
def test_batch_schema_rejects_ids_that_are_not_supplied_evidence_keys(ref):
    schema=batch_schema(REQUIREMENTS,EVIDENCE)
    with pytest.raises(ValidationError):
        schema.model_validate(output([ref]))
    assert schema.model_validate(output(list(EVIDENCE))).outcomes[0].components[0].evidence_refs==list(EVIDENCE)


def test_empty_evidence_allows_only_empty_references_and_scopes_requirement_ids():
    schema=batch_schema(REQUIREMENTS,{})
    assert schema.model_validate(output([])).outcomes[0].components[0].evidence_refs==[]
    with pytest.raises(ValidationError):
        schema.model_validate(output(['invented']))
    value=output([])
    value['outcomes'][0]['requirement_ref']='job:other-batch'
    with pytest.raises(ValidationError):
        schema.model_validate(value)


@pytest.mark.parametrize('repair_succeeds',[True,False])
def test_model_schema_repairs_unknown_refs_before_domain_validation(monkeypatch,repair_succeeds):
    monkeypatch.setenv('ASSESSMENT_LLM_API_KEY','synthetic')
    monkeypatch.setenv('ASSESSMENT_LLM_BASE_URL','https://synthetic.invalid/v1')
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        refs=list(EVIDENCE) if repair_succeeds and len(requests)>1 else ['item1']
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop',
            'message':{'content':json.dumps(output(refs))}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Model(client,'ASSESSMENT').generate(batch_schema(REQUIREMENTS,EVIDENCE),
                'Assess.',{'requirements':REQUIREMENTS,'evidence':EVIDENCE})
    if repair_succeeds:
        assert asyncio.run(run()).outcomes[0].components[0].evidence_refs==list(EVIDENCE)
        assert len(requests)==2
    else:
        with pytest.raises(Problem) as error:
            asyncio.run(run())
        assert error.value.code=='model_output'
        assert len(requests)==3
    assert 'cv:item1:claim:0' in requests[0]['messages'][0]['content']
    assert 'failed local schema validation' in requests[1]['messages'][-1]['content']


def test_schemas_do_not_reuse_references_from_another_snapshot():
    first=batch_schema(REQUIREMENTS,EVIDENCE)
    second=batch_schema(REQUIREMENTS,{'declaration:manual1':{'text':'I used Python.'}})
    assert first.model_validate(output(list(EVIDENCE)))
    with pytest.raises(ValidationError):
        second.model_validate(output(list(EVIDENCE)))
