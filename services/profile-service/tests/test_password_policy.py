import pytest
from pydantic import ValidationError
from app.api.v1.accounts import Complete, ResetComplete


@pytest.mark.parametrize('length', [7, 8, 128, 129])
@pytest.mark.parametrize('schema', [Complete, ResetComplete])
def test_password_length_policy_is_consistent_for_access_and_reset(schema, length):
    secret = 'A' * 43
    fields = ({'flow_id': secret, 'attempt_id': secret, 'session_token': secret}
              if schema is Complete else {'challenge_id': secret, 'code': '123456'})
    if 8 <= length <= 128:
        assert schema(**fields, password='x' * length).password == 'x' * length
    else:
        with pytest.raises(ValidationError):
            schema(**fields, password='x' * length)
