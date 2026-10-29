from copy import deepcopy
import pytest
from app.domain.attachments import assess_links
from tests.conftest import ready, upload, mutation, docx


def changed_candidate(harness, remove=False):
    client, app, extractor, *_ = harness
    cv = ready(harness)
    item = cv['items'][1]
    changes = {'action': 'remove'} if remove else {'action': 'update', 'description': 'I wrote Python with guidance.'}
    edited = client.patch(f"/api/v1/cv/{cv['id']}/items/{item['id']}", json=mutation(cv['version'], **changes)).json()
    extractor.payload = {'items': [
        {'kind': 'education', 'title': 'Example University', 'description': 'Computing degree', 'explicit': True,
         'evidence': [{'block_id': 'b1', 'excerpt': 'Education: Example University, Computing'}]},
        {'kind': 'project', 'title': 'Project A reinterpreted', 'description': 'Team built a Python and SQL application.',
         'explicit': True, 'skill_names': ['Python', 'SQL'], 'uncertainties': ['personal_contribution'],
         'evidence': [{'block_id': 'b2', 'excerpt': 'Team built a Python and SQL application.'}]}]}
    assert upload(client, cv_id=cv['id'], expected_version=edited['version']).status_code == 202
    app.state.worker.run_once()
    failed = client.get('/api/v1/cv/' + cv['id']).json()
    candidate = client.get(f"/api/v1/cv/{cv['id']}/reconciliation").json()
    assert failed['status'] == 'failed' and failed['error']['code'] == 'reconciliation_required'
    assert failed['reconciliation_candidate_id'] == candidate['candidate_id']
    return failed, candidate, item, edited


def test_reprocessing_candidate_is_saved_and_keep_restores_previous_ready_result(harness):
    client, app, *_ = harness
    cv, candidate, item, edited = changed_candidate(harness)
    assert candidate['previous_items'][1]['description'] == edited['items'][1]['description']
    assert candidate['candidate_items'][1]['id'] != item['id']
    assert client.post(f"/api/v1/cv/operations/{cv['operation_id']}/retry", json=mutation(cv['version'])).status_code == 409
    body = mutation(cv['version'], candidate_id=candidate['candidate_id'], action='keep_previous')
    result = client.post(f"/api/v1/cv/{cv['id']}/reconciliation", json=body)
    assert result.status_code == 200, result.text
    kept = result.json()
    assert kept['status'] == 'ready' and kept['items'] == edited['items']
    assert kept['effective_version'] == edited['effective_version']
    assert kept['reconciliation_candidate_id'] is None
    assert client.post(f"/api/v1/cv/{cv['id']}/reconciliation", json=body).json()['version'] == kept['version']
    assert app.state.repository.get('owner-a', cv['id'])['history'][-1]['candidate']['id'] == candidate['candidate_id']


@pytest.mark.parametrize('reapply', [True, False])
def test_candidate_requires_explicit_mapping_and_retains_previous_history(harness, reapply):
    client, app, *_ = harness
    cv, candidate, item, edited = changed_candidate(harness, remove=True)
    path = f"/api/v1/cv/{cv['id']}/reconciliation"
    bad = mutation(cv['version'], candidate_id=candidate['candidate_id'], action='accept_candidate')
    assert client.post(path, json=bad).status_code == 409
    wrong = mutation(cv['version'], candidate_id=candidate['candidate_id'], action='accept_candidate',
                     choices=[{'item_id': item['id'], 'target_item_id': candidate['candidate_items'][0]['id']}])
    assert client.post(path, json=wrong).status_code == 409
    target = candidate['candidate_items'][1]['id']
    result = client.post(path, json=mutation(cv['version'], candidate_id=candidate['candidate_id'], action='accept_candidate',
        choices=[{'item_id': item['id'], 'target_item_id': target if reapply else None}]))
    assert result.status_code == 200, result.text
    accepted = result.json()
    assert accepted['status'] == 'ready' and accepted['extraction_version'] == cv['extraction_version'] + 1
    assert accepted['items'][1]['removed'] is reapply
    old = app.state.repository.get('owner-a', cv['id'])['history'][-1]
    assert old['overlays'][item['id']]['removed'] is True
    assert old['original_items'][1]['id'] == item['id']


def test_reconciliation_owner_and_stale_choices_are_rejected(harness):
    client, *_ = harness
    cv, candidate, item, _ = changed_candidate(harness)
    path = f"/api/v1/cv/{cv['id']}/reconciliation"
    assert client.post(path, json=mutation(cv['version'] - 1, candidate_id=candidate['candidate_id'], action='keep_previous')).status_code == 409
    client.headers['Authorization'] = 'Bearer owner-b'
    assert client.get(path).status_code == 404
    assert client.post(path, json=mutation(cv['version'], candidate_id=candidate['candidate_id'], action='keep_previous')).status_code == 404


def test_replacement_comparison_is_explicit_and_does_not_modify_previous_cv(harness):
    client, app, *_ = harness
    old = ready(harness)
    old_item = old['items'][1]
    old = client.patch(f"/api/v1/cv/{old['id']}/items/{old_item['id']}",
        json=mutation(old['version'], action='update', description='Only my own Python work.')).json()
    new = ready(harness)
    request = mutation(new['version'], source_cv_id=old['id'], source_version=old['version'])
    compare = client.post(f"/api/v1/cv/{new['id']}/reconciliation/compare", json=request)
    assert compare.status_code == 200, compare.text
    assert client.post(f"/api/v1/cv/{new['id']}/reconciliation/compare", json=request).status_code == 200
    candidate = client.get(f"/api/v1/cv/{new['id']}/reconciliation").json()
    assert candidate['source_cv_id'] == old['id']
    assert candidate['affected_item_ids'] == [old_item['id']]
    result = client.post(f"/api/v1/cv/{new['id']}/reconciliation", json=mutation(compare.json()['version'],
        candidate_id=candidate['candidate_id'], action='accept_candidate',
        choices=[{'item_id': old_item['id'], 'target_item_id': new['items'][1]['id']}]))
    assert result.status_code == 200, result.text
    assert result.json()['items'][1]['description'] == old['items'][1]['description']
    assert client.get('/api/v1/cv/' + old['id']).json() == old
    history = app.state.repository.get('owner-a', new['id'])['history'][-1]
    assert history['candidate']['source_cv_id'] == old['id']


def context(**changes):
    return {'id': 'goal-a', 'version': 1, 'selection_version': 1, 'type': 'specific_job',
            'confirmed': True, 'skill_ids': ['skill:python'], 'role': 'Analyst', 'field': 'Data', **changes}


@pytest.mark.parametrize('correction', [{'start_date': '2020'}, {'ongoing': True}])
def test_reapplied_dates_must_be_valid_with_replacement_and_failed_choice_is_retained(harness, correction):
    client, app, extractor, *_ = harness
    old = ready(harness)
    old_item = old['items'][0]
    old = client.patch(f"/api/v1/cv/{old['id']}/items/{old_item['id']}",
                      json=mutation(old['version'], action='update', **correction)).json()
    extractor.payload = {'items': [{'kind': 'education', 'title': 'Diploma', 'description': 'Graduated 2019',
        'explicit': True, 'end_date': '2019', 'evidence': [{'block_id': 'b1', 'excerpt': 'Graduated 2019'}]}]}
    uploaded = upload(client, data=docx(['Graduated 2019'])).json()
    app.state.worker.run_once()
    new = client.get('/api/v1/cv/' + uploaded['id']).json()
    assert new['status'] == 'ready'
    compared = client.post(f"/api/v1/cv/{new['id']}/reconciliation/compare", json=mutation(new['version'],
        source_cv_id=old['id'], source_version=old['version'])).json()
    path = f"/api/v1/cv/{new['id']}/reconciliation"
    candidate = client.get(path).json()
    invalid = client.post(path, json=mutation(compared['version'], candidate_id=candidate['candidate_id'],
        action='accept_candidate', choices=[{'item_id': old_item['id'], 'target_item_id': new['items'][0]['id']}]))
    assert invalid.status_code == 409, invalid.text
    assert client.get(path).json() == candidate
    assert client.get('/api/v1/cv/' + new['id']).json()['version'] == compared['version']
    archived = client.post(path, json=mutation(compared['version'], candidate_id=candidate['candidate_id'],
        action='accept_candidate', choices=[{'item_id': old_item['id'], 'target_item_id': None}]))
    assert archived.status_code == 200, archived.text
    assert archived.json()['items'][0]['end_date'] == '2019'
    assert archived.json()['items'][0]['start_date'] is None
    assert archived.json()['items'][0]['ongoing'] is False


def test_changed_previous_cv_does_not_trap_replacement_comparison(harness):
    client, *_ = harness
    old, new = ready(harness), ready(harness)
    compared = client.post(f"/api/v1/cv/{new['id']}/reconciliation/compare", json=mutation(new['version'],
        source_cv_id=old['id'], source_version=old['version'])).json()
    candidate = client.get(f"/api/v1/cv/{new['id']}/reconciliation").json()
    changed = client.patch(f"/api/v1/cv/{old['id']}/items/{old['items'][0]['id']}",
                          json=mutation(old['version'], action='update', title='Updated elsewhere'))
    assert changed.status_code == 200
    path = f"/api/v1/cv/{new['id']}/reconciliation"
    assert client.post(path, json=mutation(compared['version'], candidate_id=candidate['candidate_id'],
                                          action='accept_candidate')).status_code == 409
    discard = client.post(path, json=mutation(compared['version'], candidate_id=candidate['candidate_id'],
                                             action='keep_previous'))
    assert discard.status_code == 200, discard.text
    assert discard.json()['reconciliation_candidate_id'] is None
    edit = client.patch(f"/api/v1/cv/{new['id']}/items/{new['items'][0]['id']}",
                        json=mutation(discard.json()['version'], action='update', title='Editable again'))
    assert edit.status_code == 200, edit.text


def handoff_path(cv, **changes):
    from urllib.parse import urlencode
    params = {'expected_version': cv['version'], 'expected_selection_version': 1,
              'expected_declarations_version': 1, 'expected_target_id': 'goal-a',
              'expected_target_version': 1, 'expected_target_selection_version': 1, **changes}
    return f"/api/v1/cv/{cv['id']}/analysis-input?" + urlencode(params)


@pytest.mark.parametrize('target_type', ['specific_job', 'career_exploration'])
def test_target_bound_snapshot_contains_exact_source_and_target_versions(harness, target_type):
    client, app, _, targets, _ = harness
    cv = ready(harness)
    targets.context_value = context(type=target_type)
    client.put('/api/v1/cv/selection', json=mutation(0, cv_id=cv['id']))
    response = client.get(handoff_path(cv))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['requires_consumer_revalidation'] is True
    assert value['target']['id'] == 'goal-a' and value['target']['type'] == target_type
    assert value['target']['selection_version'] == 1
    assert value['capabilities']['cv_version'] == cv['version']
    assert value['capabilities']['upload_profile_version'] == cv['profile_version']
    assert value['capabilities']['declarations_version'] == 1
    assert value['capabilities']['declaration_links'][0]['status'] == 'standalone'
    assert not hasattr(app.state, 'analyses')


def test_target_bound_snapshot_rejects_missing_changed_and_switched_away_and_back(harness):
    client, app, _, targets, _ = harness
    cv = ready(harness)
    client.put('/api/v1/cv/selection', json=mutation(0, cv_id=cv['id']))
    assert client.get(handoff_path(cv)).status_code == 409
    targets.context_value = context(version=2)
    assert client.get(handoff_path(cv)).status_code == 409
    calls = 0
    async def switched(authorization):
        nonlocal calls
        calls += 1
        return context(selection_version=1 if calls == 1 else 3)
    targets.selected_context = switched
    assert client.get(handoff_path(cv)).status_code == 409


def test_attachment_checks_item_changes_not_unrelated_cv_revision(harness):
    client, app, *_ = harness
    cv = ready(harness)
    item = cv['items'][1]
    declaration = {'id': 'd', 'name': 'Python', 'skill_id': 'skill:python',
        'attached_to': {'cv_id': cv['id'], 'item_id': item['id'], 'cv_version': cv['version']},
        'attached_source_fingerprint': item['source_fingerprint']}
    def status(row=declaration):
        return assess_links(app.state.repository, 'owner-a', [row], cv['id'])[0]['status']
    assert status() == 'current'
    assert status({**declaration, 'attached_source_fingerprint': None}) == 'unverified'
    other = cv['items'][0]
    cv = client.patch(f"/api/v1/cv/{cv['id']}/items/{other['id']}",
        json=mutation(cv['version'], action='update', title='Corrected university')).json()
    assert status() == 'current'
    cv = client.patch(f"/api/v1/cv/{cv['id']}/items/{item['id']}",
        json=mutation(cv['version'], action='update', description='My revised Python description.')).json()
    assert status() == 'changed'
    cv = client.patch(f"/api/v1/cv/{cv['id']}/items/{item['id']}", json=mutation(cv['version'], action='remove')).json()
    assert status() == 'removed'
    assert declaration['attached_to']['cv_version'] < cv['version']


def test_date_edit_validates_combined_range_and_preserves_skill_months(harness):
    client, *_ = harness
    cv = ready(harness)
    item = cv['items'][2]
    path = f"/api/v1/cv/{cv['id']}/items/{item['id']}"
    first = client.patch(path, json=mutation(cv['version'], action='update', start_date='2020-06',
        end_date='2021', experience_months=6))
    assert first.status_code == 200, first.text
    cv = first.json()
    assert client.patch(path, json=mutation(cv['version'], action='update', start_date='2022')).status_code == 422
    result = client.patch(path, json=mutation(cv['version'], action='update', end_date=None, ongoing=True))
    assert result.status_code == 200, result.text
    edited = next(row for row in result.json()['items'] if row['id'] == item['id'])
    assert edited['experience_months'] == 6 and edited['end_date'] is None and edited['ongoing'] is True
