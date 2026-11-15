"""The synthetic request-size replay never sends a provider request."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'measure_request_sizes.py'
spec=importlib.util.spec_from_file_location('request_size_replay',SCRIPT)
replay=importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_replay_is_deterministic_content_free_and_offline():
    with patch('socket.socket.connect',side_effect=AssertionError('Network access is forbidden in replay')):
        first=replay.run()
        second=replay.run()
    assert first==second
    assert first['provider_calls']==0 and len(first['rows'])==24
    assert {row['fixture'] for row in first['rows']}=={'clear','sparse','long','ambiguous'}
    assert {row['stage'] for row in first['rows']}=={'extraction','extraction_repair','evidence_verification',
        'cv_interview_interpret','cv_interview_plan','clarification_interpretation'}
    assert all(row['request_bytes']>0 and row['system_text_bytes']>0 for row in first['rows'])
    encoded=json.dumps(first)
    assert all(answer not in encoded for answer in replay.CASES.values())
    base=json.loads((Path(__file__).parent/'fixtures'/'request-size-baseline.json').read_text())
    changes=replay.compare(first,base)
    assert len(changes)==24 and all(set(row)=={'fixture','stage','request_bytes_before','request_bytes_after','request_bytes_delta'} for row in changes)
    before=json.loads((Path(__file__).parent/'fixtures'/'request-size-before-7b33a07.json').read_text())
    assert len(replay.compare(first,before))==24


def test_comparison_rejects_incomplete_baselines():
    current={'format':'cv-request-size-replay-v1','rows':[{'fixture':'clear','stage':'extraction','request_bytes':10}]}
    with pytest.raises(ValueError,match='missing'):
        replay.compare(current,{'format':current['format'],'rows':[]})
