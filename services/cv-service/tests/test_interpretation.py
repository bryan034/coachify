from copy import deepcopy
from uuid import uuid4
import pytest
from app.domain.capabilities import effective_items, skills_for, validate_interpretation
from app.schemas.cv import AnswerMutation, ItemMutation, validate_item_dates
from app.clarification.service import answer as save_domain_answer
from tests.conftest import ready, mutation, FakeInterpreter
from tests.test_clarification import prepare_context


PERSONAL = 'I wrote Python for six months with my tutor. My teammate wrote SQL.'


def mixed_output(item, question, text, revision):
    return {'item_id': item['id'], 'answer_revision': revision, 'resolution': 'resolved',
        'claims': [
            {'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'personal', 'assistance': 'supervised',
             'experience_months': 6, 'evidence_excerpt': text.split('. ')[0] + '.',
             'changed_fields': ['attribution', 'assistance', 'experience_months']},
            {'skill_id': 'skill:sql', 'name': 'SQL', 'attribution': 'team', 'evidence_excerpt': 'My teammate wrote SQL.',
             'changed_fields': ['attribution']}],
        'resolved_uncertainties': [question['uncertainty']], 'remaining_uncertainties': []}


def project_question(harness):
    cv, questions = prepare_context(harness, ready(harness))
    question = next(q for q in questions if q['kind'] == 'project')
    return cv, question, f"/api/v1/cv/{cv['id']}/clarifications/{question['id']}"


def test_mixed_personal_team_duration_and_supervision(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    app.state.interpreter.payload = mixed_output
    result = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL))
    assert result.status_code == 200, result.text
    saved = result.json()
    clarification = next(q for q in saved['clarifications'] if q['id'] == question['id'])
    assert clarification['answer'] == PERSONAL
    assert clarification['answer_revision'] == 1
    assert clarification['interpretation_status'] == 'ready'
    assert clarification['resolution'] == 'resolved'
    python = next(s for s in saved['skills'] if s['skill_id'] == 'skill:python')
    assert python['experience_months'] == 6
    assert python['proficiency'] is None
    assert python['sources'][0]['attribution'] == 'personal'
    assert python['sources'][0]['assistance'] == 'supervised'
    assert python['sources'][0]['explicit'] is False
    sql = next(s for s in saved['skills'] if s['skill_id'] == 'skill:sql')
    assert question['item_id'] not in sql['item_ids']
    assert sql['explicit'] is True
    assert saved['original_items'] == cv['original_items']
    assert client.get('/api/v1/cv/' + cv['id']).json()['skills'] == saved['skills']


@pytest.mark.parametrize('attribution,explanation', [
    ('observed', 'I only observed Python and SQL work.'),
    ('denied', 'I did not perform Python or SQL work.'),
    ('team', 'The team performed Python and SQL work.')])
def test_nonpersonal_source_is_removed_without_global_denial(harness, attribution, explanation):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    app.state.interpreter.payload = {'resolution': 'resolved', 'claims': [
        {'skill_id': 'skill:' + name.lower(), 'name': name, 'attribution': attribution,
         'evidence_excerpt': explanation, 'changed_fields': ['attribution']} for name in ('Python', 'SQL')],
        'resolved_uncertainties': ['personal_contribution'], 'remaining_uncertainties': []}
    saved = client.put(path, json=mutation(cv['version'], action='answer', answer=explanation)).json()
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['interpretation_status'] == 'ready'
    assert [s['skill_id'] for s in saved['skills']] == ['skill:sql']
    assert saved['skills'][0]['explicit'] is True
    assert question['item_id'] not in saved['skills'][0]['item_ids']


def test_failure_keeps_answer_retry_is_distinct_and_idempotent(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    app.state.interpreter.failure = 'Synthetic provider unavailable.'
    request = mutation(cv['version'], action='answer', answer=PERSONAL)
    failed = client.put(path, json=request).json()
    q = next(q for q in failed['clarifications'] if q['id'] == question['id'])
    assert q['answer'] == PERSONAL and q['interpretation_status'] == 'failed'
    assert q['resolution'] == 'unresolved'
    assert failed['effective_version'] == cv['effective_version']
    assert app.state.interpreter.calls == 1
    assert client.put(path, json=request).json()['version'] == failed['version']
    assert app.state.interpreter.calls == 1
    app.state.interpreter.failure = None
    app.state.interpreter.payload = mixed_output
    retry = mutation(failed['version'])
    interpreted = client.post(path + '/interpretation/retry', json=retry)
    assert interpreted.status_code == 200, interpreted.text
    saved = interpreted.json()
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['interpretation_status'] == 'ready'
    assert app.state.interpreter.calls == 2
    assert client.post(path + '/interpretation/retry', json=retry).json()['version'] == saved['version']
    assert app.state.interpreter.calls == 2


def test_pending_answer_is_durable_before_provider_and_recoverable(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    def inspect_durable_answer():
        pending = app.state.service.get('owner-a', cv['id'])
        q = next(q for q in pending['clarifications'] if q['id'] == question['id'])
        assert q['answer'] == PERSONAL and q['interpretation_status'] == 'pending'
        assert pending['effective_version'] == cv['effective_version']
    app.state.interpreter.before_return = inspect_durable_answer
    app.state.interpreter.payload = mixed_output
    assert client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).status_code == 200
    # Reproduce a process death after the first write using the persisted state.
    current = app.state.service.get('owner-a', cv['id'])
    changed = deepcopy(current)
    q = next(q for q in changed['clarifications'] if q['id'] == question['id'])
    q['interpretation_status'] = 'pending'
    changed['revision'] += 1
    changed['version'] += 1
    app.state.repository.replace(current, changed)
    app.state.interpreter.before_return = None
    response = client.post(path + '/interpretation/retry', json=mutation(changed['version']))
    assert response.status_code == 200
    assert next(q for q in response.json()['clarifications'] if q['id'] == question['id'])['interpretation_status'] == 'ready'


def test_newer_answer_fences_late_interpretation(harness):
    client, app, *_ = harness
    from dataclasses import replace
    # Exercise two overlapping synthetic responses under an explicitly larger
    # owner limit; the default one-call guard has separate admission coverage.
    app.state.service.model_usage.settings = replace(app.state.settings, model_concurrent_per_owner=2)
    cv, question, path = project_question(harness)
    newer_text = 'I only observed Python and SQL work.'
    replacement = FakeInterpreter()
    replacement.payload = {'resolution': 'resolved', 'claims': [
        {'skill_id': 'skill:' + name.lower(), 'name': name, 'attribution': 'observed',
         'evidence_excerpt': newer_text, 'changed_fields': ['attribution']} for name in ('Python', 'SQL')],
        'resolved_uncertainties': ['personal_contribution'], 'remaining_uncertainties': []}
    def newer_answer():
        latest = app.state.service.get('owner-a', cv['id'])
        save_domain_answer(app.state.service, 'owner-a', cv['id'], question['id'],
            AnswerMutation.model_validate(mutation(latest['version'], action='answer', answer=newer_text)), replacement)
    app.state.interpreter.before_return = newer_answer
    app.state.interpreter.payload = mixed_output
    response = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL))
    assert response.status_code == 409
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    q = next(q for q in saved['clarifications'] if q['id'] == question['id'])
    assert q['answer'] == newer_text and q['answer_revision'] == 2
    assert q['interpretation_status'] == 'ready'
    assert 'skill:python' not in [s['skill_id'] for s in saved['skills']]


def test_paraphrase_changes_answer_history_not_effective_facts(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    app.state.interpreter.payload = mixed_output
    first = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
    second_text = 'I wrote Python for six months with my tutor, as explained. My teammate wrote SQL.'
    second = client.put(path, json=mutation(first['version'], action='answer', answer=second_text)).json()
    assert second['effective_version'] == first['effective_version']
    assert second['version'] > first['version']
    q = next(q for q in second['clarifications'] if q['id'] == question['id'])
    assert q['answer'] == second_text and q['answer_revision'] == 2
    assert q['interpretation_status'] == 'ready'


def test_partial_answer_permits_only_distinct_followup(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    text = 'I wrote Python independently. My teammate wrote SQL. I am unsure how long I used Python.'
    app.state.interpreter.payload = {'resolution': 'partial', 'claims': [
        {'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'personal', 'assistance': 'independent',
         'evidence_excerpt': 'I wrote Python independently.', 'changed_fields': ['attribution', 'assistance']},
        {'skill_id': 'skill:sql', 'name': 'SQL', 'attribution': 'team',
         'evidence_excerpt': 'My teammate wrote SQL.', 'changed_fields': ['attribution']}],
        'resolved_uncertainties': ['personal_contribution'], 'remaining_uncertainties': ['duration']}
    saved = client.put(path, json=mutation(cv['version'], action='answer', answer=text)).json()
    revisited, questions = prepare_context(harness, saved, 'target-b')
    followups = [q for q in questions if q['item_id'] == question['item_id'] and q['status'] == 'unanswered']
    assert len(followups) == 1
    assert followups[0]['uncertainty'] == 'duration'
    assert followups[0]['followup_of'] == question['id']
    app.state.interpreter.payload = None
    followup_path = f"/api/v1/cv/{cv['id']}/clarifications/{followups[0]['id']}"
    unknown = client.put(followup_path, json=mutation(revisited['version'], action='answer', answer='I do not know how many months.')).json()
    final, questions = prepare_context(harness, unknown, 'target-c')
    assert not [q for q in questions if q['item_id'] == question['item_id'] and q['status'] == 'unanswered']
    assert 'duration' in next(i for i in final['items'] if i['id'] == question['item_id'])['uncertainties']


def test_proficiency_answer_does_not_clear_known_months(harness):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [{'kind': 'skill', 'title': 'SQL', 'description': 'Independent SQL queries for a personal dataset.',
        'explicit': True, 'evidence': [{'block_id': 'b3', 'excerpt': 'Independent SQL queries for a personal dataset.'}],
        'experience_months': 6, 'uncertainties': ['proficiency']}]}
    cv, questions = prepare_context(harness, ready(harness))
    result = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{questions[0]['id']}",
        json=mutation(cv['version'], action='answer', answer='I can write basic joins with guidance.')).json()
    assert result['skills'][0]['experience_months'] == 6
    assert result['skills'][0]['proficiency'] == 'basic joins'


@pytest.mark.parametrize('reverse', [False, True])
def test_claim_specific_dependency_and_independent_aggregation(harness, reverse):
    client, app, extractor, *_ = harness
    parent = {'kind': 'project', 'title': 'Project A', 'description': 'Project A: Team built a Python and SQL application.',
        'explicit': True, 'evidence': [{'block_id': 'b2', 'excerpt': 'Project A: Team built a Python and SQL application.'}],
        'skill_names': ['Python', 'SQL'], 'uncertainties': ['personal_contribution']}
    derived = {**deepcopy(parent), 'kind': 'experience', 'title': 'Derived work', 'explicit': False,
        'uncertainties': [], 'supporting_items': [0]}
    independent = {'kind': 'skill', 'title': 'SQL', 'description': 'Independent SQL queries for a personal dataset.',
        'explicit': True, 'evidence': [{'block_id': 'b3', 'excerpt': 'Independent SQL queries for a personal dataset.'}],
        'proficiency': 'basic', 'experience_months': 12}
    items = [parent, derived, independent]
    if reverse:
        items.reverse()
        items[1]['supporting_items'] = [2]
    extractor.payload = {'items': items}
    cv, question, path = project_question(harness)
    app.state.interpreter.payload = mixed_output
    saved = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
    sql = next(s for s in saved['skills'] if s['skill_id'] == 'skill:sql')
    assert sql['experience_months'] == 12 and sql['proficiency'] == 'basic'
    assert len(sql['sources']) == 1
    python = next(s for s in saved['skills'] if s['skill_id'] == 'skill:python')
    assert len(python['sources']) == 2 and python['experience_months'] == 6
    derived_item = next(i for i in saved['items'] if i['title'] == 'Derived work')
    assert derived_item['skill_ids'] == ['skill:python']


def test_unknown_source_does_not_erase_known_values_and_conflicts_are_per_field():
    def item(identifier, months, proficiency, uncertain=False):
        return {'id': identifier, 'title': 'SQL', 'skill_ids': ['skill:sql'], 'skill_names': ['SQL'],
            'provenance': 'explicit', 'removed': False, 'evidence': [], 'proficiency': proficiency,
            'experience_months': months, 'support_uncertain': uncertain}
    known, unknown = item('known', 6, 'basic'), item('unknown', None, None, True)
    for items in ([known, unknown], [unknown, known]):
        result = skills_for(items)[0]
        assert result['experience_months'] == 6 and result['proficiency'] == 'basic'
    result = skills_for([known, item('different', 12, 'basic')])[0]
    assert result['experience_months'] is None and result['proficiency'] == 'basic'
    assert result['conflicting_fields'] == ['experience_months']


def test_non_skill_conditions_require_kind_and_whole_phrase_matches(harness):
    client, app, extractor, targets, _ = harness
    extractor.payload = {'items': [{'kind': 'education', 'title': 'Example University',
        'description': 'Education: Example University, Computing', 'explicit': True,
        'evidence': [{'block_id': 'b1', 'excerpt': 'Education: Example University, Computing'}],
        'uncertainties': ['qualification', 'date']}]}
    cv = ready(harness)
    targets.context_value = {'id': 'target', 'version': 1, 'type': 'specific_job', 'confirmed': True, 'skill_ids': [],
        'conditions': [{'id': str(uuid4()), 'kind': 'qualification', 'label': 'Computing qualification',
            'description': 'Computing qualification', 'item_kinds': ['education'], 'match_terms': ['Computing'],
            'evidence': 'Computing qualification', 'origin': 'user_reviewed_jd'}]}
    response = client.post(f"/api/v1/cv/{cv['id']}/clarifications/prepare",
        json=mutation(cv['version'], career_target_id='target', career_target_version=1))
    assert response.status_code == 200, response.text
    assert [q['uncertainty'] for q in response.json()['questions']] == ['qualification']
    targets.context_value['conditions'][0]['match_terms'] = ['compute']
    assert client.get(f"/api/v1/cv/{cv['id']}/clarifications").json()['questions'] == []


def test_duration_answer_preserves_known_proficiency(harness):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [{'kind': 'skill', 'title': 'SQL', 'description': 'Independent SQL queries for a personal dataset.',
        'explicit': True, 'evidence': [{'block_id': 'b3', 'excerpt': 'Independent SQL queries for a personal dataset.'}],
        'proficiency': 'basic', 'uncertainties': ['duration']}]}
    cv, questions = prepare_context(harness, ready(harness))
    app.state.interpreter.payload = {'resolution': 'resolved', 'claims': [
        {'skill_id': 'skill:sql', 'name': 'SQL', 'attribution': 'unknown', 'experience_months': 6,
         'evidence_excerpt': 'I used SQL for six months.', 'changed_fields': ['experience_months']}],
        'resolved_uncertainties': ['duration'], 'remaining_uncertainties': []}
    result = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{questions[0]['id']}",
        json=mutation(cv['version'], action='answer', answer='I used SQL for six months.')).json()
    assert result['skills'][0]['experience_months'] == 6
    assert result['skills'][0]['proficiency'] == 'basic'


@pytest.mark.parametrize('edited_months', [6, 9])
def test_same_canonical_rename_preserves_clarified_values_and_applies_explicit_changes(harness, edited_months):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [{'kind': 'skill', 'title': 'SQL',
        'description': 'Independent SQL queries for a personal dataset.', 'explicit': True,
        'evidence': [{'block_id': 'b3', 'excerpt': 'Independent SQL queries for a personal dataset.'}],
        'uncertainties': ['proficiency', 'duration']}]}
    cv, questions = prepare_context(harness, ready(harness))
    question = next(q for q in questions if q['uncertainty'] == 'proficiency')
    text = 'I used SQL for six months and can write basic joins independently.'
    app.state.interpreter.payload = {'resolution': 'resolved', 'claims': [
        {'skill_id': 'skill:sql', 'name': 'SQL', 'attribution': 'unknown', 'proficiency': 'basic joins',
         'experience_months': 6, 'assistance': 'independent', 'evidence_excerpt': text,
         'changed_fields': ['proficiency', 'experience_months', 'assistance']}],
        'resolved_uncertainties': ['proficiency', 'duration'], 'remaining_uncertainties': []}
    answered = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{question['id']}",
        json=mutation(cv['version'], action='answer', answer=text))
    assert answered.status_code == 200, answered.text
    saved = answered.json()
    assert saved['skills'][0]['experience_months'] == 6
    assert saved['skills'][0]['proficiency'] == 'basic joins'
    # The form includes current values; unchanged values are intentionally absent
    # from the stored patch and must survive the title's canonical-identity match.
    renamed = client.patch(f"/api/v1/cv/{cv['id']}/items/{question['item_id']}", json=mutation(
        saved['version'], action='update', title='sql', proficiency='basic joins', experience_months=edited_months))
    assert renamed.status_code == 200, renamed.text
    skill = renamed.json()['skills'][0]
    assert skill['name'] == 'sql' and skill['skill_id'] == 'skill:sql'
    assert skill['experience_months'] == edited_months
    assert skill['proficiency'] == 'basic joins'
    assert skill['sources'][0]['assistance'] == 'independent'
    if edited_months == 6:
        assert skill['sources'][0]['evidence'] == saved['skills'][0]['sources'][0]['evidence']
        assert skill['sources'][0]['evidence_type'] == 'user_clarified'


def test_unknown_receipt_alone_does_not_change_effective_facts(harness):
    client, app, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    question = next(q for q in questions if q['uncertainty'] == 'proficiency')
    saved = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{question['id']}",
        json=mutation(cv['version'], action='answer', answer='I do not know.')).json()
    assert saved['effective_version'] == cv['effective_version']
    assert saved['version'] > cv['version']
    q = next(q for q in saved['clarifications'] if q['id'] == question['id'])
    assert q['status'] == 'answered' and q['resolution'] == 'unanswerable'
    assert 'proficiency' in next(i for i in saved['items'] if i['id'] == question['item_id'])['uncertainties']


def test_source_edit_fences_interpretation_and_retry(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    def edit_source():
        current = app.state.service.get('owner-a', cv['id'])
        app.state.service.edit('owner-a', cv['id'], question['item_id'],
            ItemMutation.model_validate(mutation(current['version'], action='update', description='My corrected project description.')))
    app.state.interpreter.before_return = edit_source
    app.state.interpreter.payload = mixed_output
    assert client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).status_code == 409
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    q = next(q for q in saved['clarifications'] if q['id'] == question['id'])
    assert q['answer'] == PERSONAL
    assert q['reconciliation_required'] is True
    assert q['interpretation'] is None
    assert client.post(path + '/interpretation/retry', json=mutation(saved['version'])).status_code == 409


def test_newer_answer_overrides_older_correction_without_later_dates_reasserting_it(harness):
    client, app, *_ = harness
    cv = ready(harness)
    project = next(item for item in cv['items'] if item['kind'] == 'project')
    item_path = f"/api/v1/cv/{cv['id']}/items/{project['id']}"
    corrected = client.patch(item_path, json=mutation(cv['version'], action='update',
        description='Reviewed project description with Python and SQL.', experience_months=12))
    assert corrected.status_code == 200, corrected.text
    cv, questions = prepare_context(harness, corrected.json())
    question = next(q for q in questions if q['item_id'] == project['id'])
    path = f"/api/v1/cv/{cv['id']}/clarifications/{question['id']}"
    app.state.interpreter.payload = mixed_output
    answered = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL))
    assert answered.status_code == 200, answered.text
    saved = answered.json()
    assert next(s for s in saved['skills'] if s['skill_id'] == 'skill:python')['experience_months'] == 6
    dated = client.patch(item_path, json=mutation(saved['version'], action='update', start_date='2024-06', end_date='2025-01'))
    assert dated.status_code == 200, dated.text
    saved = dated.json()
    python = next(s for s in saved['skills'] if s['skill_id'] == 'skill:python')
    assert python['experience_months'] == 6
    assert python['sources'][0]['attribution'] == 'personal'
    assert python['sources'][0]['evidence_type'] == 'user_clarified'
    q = next(q for q in saved['clarifications'] if q['id'] == question['id'])
    assert q['reconciliation_required'] is False
    # Date-only correction leaves the contribution answer editable.
    changed = client.put(path, json=mutation(saved['version'], action='answer',
        answer='I wrote Python for six months with my tutor, as explained. My teammate wrote SQL.'))
    assert changed.status_code == 200, changed.text
    assert next(s for s in changed.json()['skills'] if s['skill_id'] == 'skill:python')['experience_months'] == 6
    assert changed.json()['effective_version'] == saved['effective_version']
    # A later correction to the source still supersedes and invalidates that answer.
    changed_source = client.patch(item_path, json=mutation(changed.json()['version'], action='update',
        description='This description changes which work belonged to me.'))
    assert changed_source.status_code == 200, changed_source.text
    saved = changed_source.json()
    python = next(s for s in saved['skills'] if s['skill_id'] == 'skill:python')
    assert python['experience_months'] is None
    assert python['sources'][0]['support_uncertain'] is True
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['reconciliation_required'] is True
    assert client.put(path, json=mutation(saved['version'], action='answer', answer=PERSONAL)).status_code == 409
    assert all('_field_sequences' not in item for item in effective_items(app.state.service.get('owner-a', cv['id'])))


def test_newer_value_correction_supersedes_interpreted_months(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    app.state.interpreter.payload = mixed_output
    answered = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
    result = client.patch(f"/api/v1/cv/{cv['id']}/items/{question['item_id']}",
        json=mutation(answered['version'], action='update', experience_months=9))
    assert result.status_code == 200, result.text
    saved = result.json()
    python = next(s for s in saved['skills'] if s['skill_id'] == 'skill:python')
    assert python['experience_months'] == 9
    assert python['sources'][0]['attribution'] == 'personal'
    assert python['sources'][0]['assistance'] == 'supervised'
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['reconciliation_required'] is False


def test_replacement_reapply_retry_restores_clarified_support_after_copied_corrections(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    text = PERSONAL + ' I cleaned data with pandas.'
    def with_new_skill(item, q, answer, revision):
        result = mixed_output(item, q, answer, revision)
        result['claims'].append({'skill_id': 'skill:pandas', 'name': 'pandas', 'attribution': 'personal',
            'changed_fields': ['attribution'], 'evidence_excerpt': 'I cleaned data with pandas.'})
        return result
    app.state.interpreter.payload = with_new_skill
    saved = client.put(path, json=mutation(cv['version'], action='answer', answer=text)).json()
    item_path = f"/api/v1/cv/{cv['id']}/items/{question['item_id']}"
    saved = client.patch(item_path, json=mutation(saved['version'], action='update', start_date='2024', end_date='2025')).json()
    correction = 'Reviewed Python and SQL project source.'
    saved = client.patch(item_path, json=mutation(saved['version'], action='update', description=correction)).json()
    new = ready(harness)
    base = f"/api/v1/cv/{new['id']}"
    compare = client.post(base + '/reconciliation/compare', json=mutation(new['version'],
        source_cv_id=cv['id'], source_version=saved['version']))
    assert compare.status_code == 200, compare.text
    candidate = client.get(base + '/reconciliation').json()
    target = next(item for item in new['items'] if item['kind'] == 'project')
    choices = [{'item_id': identifier, 'target_item_id': target['id'] if identifier == question['item_id'] else None}
               for identifier in candidate['affected_item_ids']]
    reapplied = client.post(base + '/reconciliation', json=mutation(compare.json()['version'],
        candidate_id=candidate['candidate_id'], action='accept_candidate', choices=choices))
    assert reapplied.status_code == 200, reapplied.text
    mapped = next(q for q in reapplied.json()['clarifications'] if q['item_id'] == target['id'])
    assert mapped['interpretation_status'] == 'failed' and mapped['interpretation'] is None
    retry = client.post(base + f"/clarifications/{mapped['id']}/interpretation/retry",
        json=mutation(reapplied.json()['version']))
    assert retry.status_code == 200, retry.text
    interpreted = retry.json()
    mapped = next(q for q in interpreted['clarifications'] if q['id'] == mapped['id'])
    assert mapped['interpretation_status'] == 'ready'
    assert mapped['reconciled_from']['cv_id'] == cv['id']
    python = next(s for s in interpreted['skills'] if s['skill_id'] == 'skill:python')
    assert python['experience_months'] == 6
    assert python['sources'][0]['support_uncertain'] is False
    assert python['sources'][0]['attribution'] == 'personal'
    assert python['sources'][0]['assistance'] == 'supervised'
    assert next(s for s in interpreted['skills'] if s['skill_id'] == 'skill:pandas')['sources'][0]['attribution'] == 'personal'
    assert target['id'] not in next(s for s in interpreted['skills'] if s['skill_id'] == 'skill:sql')['item_ids']
    project = next(item for item in interpreted['items'] if item['id'] == target['id'])
    assert project['description'] == correction
    assert project['start_date'] == '2024' and project['end_date'] == '2025'
    assert client.get('/api/v1/cv/' + cv['id']).json() == saved


@pytest.mark.parametrize('with_history', [False, True])
def test_legacy_correction_chronology_uses_history_or_preserves_correction_priority(with_history):
    item = {'id': 'project', 'kind': 'project', 'title': 'Project', 'description': 'Source',
        'provenance': 'explicit', 'removed': False, 'evidence': [], 'skill_ids': ['skill:python'],
        'skill_names': ['Python'], 'proficiency': None, 'experience_months': None, 'uncertainties': []}
    overlay = {'description': 'Earlier correction', 'support_uncertain': True, 'provenance': 'user_corrected'}
    interpretation = {'applied_sequence': 4, 'claims': [{'skill_id': 'skill:python', 'name': 'Python',
        'attribution': 'personal', 'experience_months': 6, 'changed_fields': ['attribution', 'experience_months'],
        'evidence_excerpt': 'I used Python for six months.'}], 'resolved_uncertainties': [], 'remaining_uncertainties': []}
    document = {'version': 5, 'original_items': [item], 'overlays': {'project': overlay},
        'clarifications': [{'id': 'q', 'item_id': 'project', 'interpretation': interpretation}]}
    if with_history:
        document['history'] = [{'version': 1, 'overlays': {}}, {'version': 2, 'overlays': {'project': deepcopy(overlay)}}]
    effective = effective_items(document)
    assert effective[0]['description'] == 'Earlier correction'
    assert effective[0]['skill_claims'][0]['support_uncertain'] is (not with_history)
    assert skills_for(effective)[0]['experience_months'] == (6 if with_history else None)


@pytest.mark.parametrize('reverse', [False, True])
def test_one_denied_parent_preserves_other_supporting_parent(reverse):
    def item(identifier, parents=()):
        return {'id': identifier, 'kind': 'project', 'title': identifier, 'description': identifier,
            'provenance': 'explicit', 'removed': False, 'evidence': [], 'skill_ids': ['skill:sql'], 'skill_names': ['SQL'],
            'proficiency': 'basic', 'experience_months': 6, 'supporting_item_ids': list(parents), 'uncertainties': []}
    original = [item('team-source'), item('personal-source'), item('derived', ['team-source', 'personal-source'])]
    if reverse: original.reverse()
    document = {'original_items': original, 'overlays': {}, 'clarifications': [{'id': 'q', 'item_id': 'team-source',
        'interpretation': {'applied_sequence': 1, 'claims': [{'skill_id': 'skill:sql', 'name': 'SQL',
            'attribution': 'team', 'changed_fields': ['attribution'], 'evidence_excerpt': 'My teammate wrote SQL.'}],
            'resolved_uncertainties': [], 'remaining_uncertainties': []}}]}
    derived = next(i for i in effective_items(document) if i['id'] == 'derived')
    assert derived['skill_ids'] == ['skill:sql']
    assert derived['skill_claims'][0]['support_uncertain'] is False
    document['overlays']['personal-source'] = {'removed': True, 'provenance': 'user_corrected'}
    derived = next(i for i in effective_items(document) if i['id'] == 'derived')
    assert derived['skill_ids'] == []


@pytest.mark.parametrize('operation', ['answer', 'retry'])
def test_concurrent_same_key_invokes_provider_once(harness, monkeypatch, operation):
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from threading import Barrier, Event
    from app.clarification.service import retry_interpretation
    from app.schemas.cv import Mutation

    client, app, *_ = harness
    cv, question, path = project_question(harness)
    interpreter = app.state.interpreter
    if operation == 'retry':
        interpreter.failure = 'Synthetic initial failure.'
        cv = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
        interpreter.failure = None
        interpreter.calls = 0
        request = Mutation.model_validate(mutation(cv['version']))
        invoke = retry_interpretation
    else:
        request = AnswerMutation.model_validate(mutation(cv['version'], action='answer', answer=PERSONAL))
        invoke = save_domain_answer
    interpreter.payload = mixed_output
    entered, release = Event(), Event()
    def block_provider():
        entered.set()
        if not release.wait(5): raise AssertionError('Test did not release synthetic provider.')
    interpreter.before_return = block_provider
    barrier = Barrier(2)
    replace = app.state.repository.replace
    def concurrent_replace(previous, document):
        q = next(q for q in document['clarifications'] if q['id'] == question['id'])
        if document['version'] == cv['version'] + 1 and q.get('interpretation_status') == 'pending':
            barrier.wait(timeout=5)
        return replace(previous, document)
    monkeypatch.setattr(app.state.repository, 'replace', concurrent_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke, app.state.service, 'owner-a', cv['id'], question['id'], request, interpreter)
                   for _ in range(2)]
        try:
            assert entered.wait(5), 'One winning invocation should reach the provider.'
            finished, _ = wait(futures, timeout=3, return_when=FIRST_COMPLETED)
            # The loser replays the saved pending receipt while the winner alone
            # waits on the provider. Without the token both block and this fails.
            assert len(finished) == 1
            receipt = next(iter(finished)).result()
            assert next(q for q in receipt['clarifications'] if q['id'] == question['id'])['interpretation_status'] == 'pending'
            assert interpreter.calls == 1
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]
    latest = app.state.service.get('owner-a', cv['id'])
    saved_q = next(q for q in latest['clarifications'] if q['id'] == question['id'])
    assert saved_q['interpretation_status'] == 'ready'
    assert saved_q['answer_revision'] == 1
    assert saved_q['interpretation_token'] is None
    assert interpreter.calls == 1
    replayed = invoke(app.state.service, 'owner-a', cv['id'], question['id'], request, interpreter)
    assert replayed['version'] == latest['version']
    assert interpreter.calls == 1


def test_live_pending_lease_blocks_fresh_retries_and_expiry_allows_recovery(harness, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.clarification.service import retry_interpretation
    from app.domain.errors import Conflict
    from app.schemas.cv import Mutation

    client, app, *_ = harness
    from dataclasses import replace
    # This lease-fencing case deliberately overlaps two synthetic calls. Keep
    # that scenario explicit while production defaults allow one per account.
    app.state.service.model_usage.settings = replace(app.state.settings, model_concurrent_per_owner=2)
    cv, question, path = project_question(harness)
    entered, release = Event(), Event()
    interpreter = app.state.interpreter
    interpreter.payload = mixed_output
    def hold_provider():
        entered.set()
        assert release.wait(5)
    interpreter.before_return = hold_provider
    with ThreadPoolExecutor(max_workers=1) as executor:
        original = executor.submit(save_domain_answer, app.state.service, 'owner-a', cv['id'], question['id'],
            AnswerMutation.model_validate(mutation(cv['version'], action='answer', answer=PERSONAL)), interpreter)
        try:
            assert entered.wait(5)
            pending = app.state.service.get('owner-a', cv['id'])
            for _ in range(3):
                with pytest.raises(Conflict, match='still being interpreted'):
                    retry_interpretation(app.state.service, 'owner-a', cv['id'], question['id'],
                        Mutation.model_validate(mutation(pending['version'])), interpreter)
            assert interpreter.calls == 1
            assert app.state.service.get('owner-a', cv['id'])['version'] == pending['version']
            q = next(q for q in pending['clarifications'] if q['id'] == question['id'])
            monkeypatch.setattr('app.clarification.service.now', lambda: q['interpretation_lease_until'] + 1)
            replacement = FakeInterpreter()
            replacement.payload = mixed_output
            recovered = retry_interpretation(app.state.service, 'owner-a', cv['id'], question['id'],
                Mutation.model_validate(mutation(pending['version'])), replacement)
            assert replacement.calls == 1
            assert next(q for q in recovered['clarifications'] if q['id'] == question['id'])['interpretation_status'] == 'ready'
        finally:
            release.set()
        with pytest.raises(Conflict): original.result(timeout=5)
    assert app.state.service.get('owner-a', cv['id'])['version'] == recovered['version']


def test_interpretation_capacity_is_nonblocking_and_recoverable(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    app.state.interpreter.payload = mixed_output
    assert app.state.service.interpretation_slots.acquire(blocking=False)
    assert app.state.service.interpretation_slots.acquire(blocking=False)
    try:
        response = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL))
        assert response.status_code == 200
        failed = response.json()
        q = next(q for q in failed['clarifications'] if q['id'] == question['id'])
        assert q['answer'] == PERSONAL and q['interpretation_status'] == 'failed'
        assert 'busy' in q['interpretation_error']
        assert app.state.interpreter.calls == 0
    finally:
        app.state.service.interpretation_slots.release()
        app.state.service.interpretation_slots.release()
    result = client.post(path + '/interpretation/retry', json=mutation(failed['version']))
    assert result.status_code == 200
    assert next(q for q in result.json()['clarifications'] if q['id'] == question['id'])['interpretation_status'] == 'ready'
    assert app.state.interpreter.calls == 1


def test_answer_resolving_another_prepared_uncertainty_hides_obsolete_prompt(harness):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [{'kind': 'skill', 'title': 'SQL', 'description': 'Independent SQL queries for a personal dataset.',
        'explicit': True, 'evidence': [{'block_id': 'b3', 'excerpt': 'Independent SQL queries for a personal dataset.'}],
        'uncertainties': ['proficiency', 'duration']}]}
    cv, questions = prepare_context(harness, ready(harness))
    proficiency = next(q for q in questions if q['uncertainty'] == 'proficiency')
    duration = next(q for q in questions if q['uncertainty'] == 'duration')
    text = 'I can write basic joins and used SQL for six months.'
    app.state.interpreter.payload = {'resolution': 'resolved', 'claims': [
        {'skill_id': 'skill:sql', 'name': 'SQL', 'attribution': 'unknown', 'proficiency': 'basic joins',
         'experience_months': 6, 'evidence_excerpt': text, 'changed_fields': ['proficiency', 'experience_months']}],
        'resolved_uncertainties': ['proficiency', 'duration'], 'remaining_uncertainties': []}
    response = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{proficiency['id']}",
        json=mutation(cv['version'], action='answer', answer=text))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['items'][0]['uncertainties'] == []
    assert next(q for q in saved['clarifications'] if q['id'] == duration['id'])['status'] == 'unanswered'
    current = client.get(f"/api/v1/cv/{cv['id']}/clarifications").json()['questions']
    assert [q['id'] for q in current] == [proficiency['id']]
    _, revisited = prepare_context(harness, saved, 'another-target')
    assert [q['id'] for q in revisited] == [proficiency['id']]
