"""The opt-in runner preserves failed attempts and isolates deployment settings."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest


def runner():
    path=Path(__file__).resolve().parents[3]/'infrastructure/testing/run-career-flow.py'
    spec=importlib.util.spec_from_file_location('career_flow_runner',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_attempt_is_retained_and_failure_cannot_be_hidden_by_later_success(monkeypatch,tmp_path):
    module=runner()
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setenv('CAREER_LLM_API_KEY','PRIVATE inherited key')
    monkeypatch.setenv('UNRELATED_SECRET','PRIVATE unrelated secret')
    class Ready:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
    class Opener:
        def open(self,url,**kwargs):
            if url.endswith('/workspace'):raise HTTPError(url,401,'Unauthorized',{},None)
            return Ready()
    monkeypatch.setattr(module,'build_opener',lambda *args:Opener())
    calls=[]
    results=iter([1,0,0,0])
    def execute(command,**kwargs):
        calls.append((command,kwargs))
        env=kwargs['env']
        assert env['CAREER_LLM_API_KEY']=='' and 'UNRELATED_SECRET' not in env
        if command[0]=='npx':return SimpleNamespace(returncode=next(results))
        if 'logs' in command:
            if kwargs.get('capture_output'):assert '--since' in command
            return SimpleNamespace(returncode=0,stdout=(
                'career-service-1  | INFO: ai_usage stage=jd_extraction attempt=1 provider_attempt=1 counters={} finish_reason=stop\n'
                'career-service-1  | Arbitrary PRIVATE content\n'))
        assert command[:4]==['docker','compose','--env-file','/dev/null']
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess,'run',execute)
    args=SimpleNamespace(mode='both',port=8093,mail_port=8036,no_build=True,skip_boundary=True,repeat=2,keep=False)
    with pytest.raises(RuntimeError,match='Career journey failed'):module.run(args)
    reports=list((tmp_path/'apps/frontend/test-results/career-flow/reports').glob('*.json'))
    assert len(reports)==1
    report=json.loads(reports[0].read_text())
    assert [attempt['passed'] for attempt in report['attempts']]==[False,True,True,True]
    assert [attempt['mode'] for attempt in report['attempts']]==['fixture','fixture','local','local']
    assert [attempt['attempt'] for attempt in report['attempts']]==[1,2,1,2]
    assert all(len(attempt['diagnostics'])==1 for attempt in report['attempts'])
    assert 'PRIVATE' not in reports[0].read_text()
    assert 'down' in calls[-1][0] and '--volumes' in calls[-1][0]
    outputs=[call[0][call[0].index('--output')+1] for call in calls if call[0][0]=='npx']
    assert len(set(outputs))==4
