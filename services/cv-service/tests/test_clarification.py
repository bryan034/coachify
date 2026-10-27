from tests.conftest import ready, mutation


def prepare_context(harness, cv, target='target-a', version=1):
    client, app, _, targets, _ = harness
    targets.context_value = {'id': target, 'version': version, 'type': 'specific_job', 'confirmed': True,
                             'skill_ids': ['skill:python', 'skill:sql']}
    response = client.post(f"/api/v1/cv/{cv['id']}/clarifications/prepare", json=mutation(cv['version'],
        career_target_id=target, career_target_version=version))
    assert response.status_code == 200, response.text
    return client.get('/api/v1/cv/' + cv['id']).json(), response.json()['questions']


def test_defer_unconfirmed_context_and_skip_without_fact_change(harness):
    client, *_ = harness
    cv = ready(harness)
    response = client.post(f"/api/v1/cv/{cv['id']}/clarifications/prepare", json=mutation(cv['version'],
        career_target_id='missing', career_target_version=1))
    assert response.json()['deferred'] is True
    assert response.json()['questions'] == []
    prepared, questions = prepare_context(harness, cv)
    assert prepared['effective_version'] == cv['effective_version']
    question = questions[0]
    path = f"/api/v1/cv/{cv['id']}/clarifications/{question['id']}"
    assert client.put(path, json=mutation(prepared['version'], action='answer', answer=' ')).status_code == 422
    skipped = client.put(path, json=mutation(prepared['version'], action='skip')).json()
    assert skipped['effective_version'] == cv['effective_version']
    assert skipped['clarifications'][0]['status'] == 'skipped'
    repeated = client.put(path, json=mutation(skipped['version'], action='skip')).json()
    assert repeated['version'] == skipped['version']
    revisited, questions = prepare_context(harness, repeated, 'target-b')
    assert len(questions) == len(prepared['clarifications'])
    assert questions[0]['status'] == 'skipped'


def test_answer_preserves_personal_work_and_independent_support(harness):
    client, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    project_question = next(q for q in questions if q['kind'] == 'project')
    path = f"/api/v1/cv/{cv['id']}/clarifications/{project_question['id']}"
    text = 'I cleaned data with pandas. My teammate wrote SQL; I do not know their implementation.'
    request = mutation(cv['version'], action='answer', answer=text)
    response = client.put(path, json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    item = next(item for item in result['items'] if item['id'] == project_question['item_id'])
    assert result['clarifications'][0]['answer'] == text
    assert result['clarifications'][0]['interpretation_status'] == 'ready'
    assert result['clarifications'][0]['resolution'] == 'partial'
    assert item['provenance'] == 'user_clarified' and item['support_uncertain']
    assert item['proficiency'] is None and item['experience_months'] is None
    sql = next(skill for skill in result['skills'] if skill['name'] == 'SQL')
    assert all(source['item_id'] != item['id'] for source in sql['sources'])
    project_sql = next(claim for claim in item['skill_claims'] if claim['skill_id'] == 'skill:sql')
    assert project_sql['attribution'] == 'team'
    pandas = next(skill for skill in result['skills'] if skill['skill_id'] == 'skill:pandas')
    assert pandas['sources'][0]['attribution'] == 'personal'
    assert pandas['sources'][0]['assistance'] == 'unknown'
    assert pandas['evidence_type'] == 'user_clarified'
    assert sql['explicit'] is True
    assert result['original_items'][1]['description'] != text
    assert result['effective_version'] == cv['effective_version'] + 1
    assert client.put(path, json=request).json()['version'] == result['version']
    assert client.put(path, json=mutation(cv['version'], action='skip')).status_code == 409
    skipped = client.put(path, json=mutation(result['version'], action='skip')).json()
    assert skipped['clarifications'][0]['answer'] == text
    assert skipped['effective_version'] == result['effective_version']
    revisited, questions = prepare_context(harness, skipped, 'target-b')
    assert len(questions) == 2
    assert questions[0]['status'] == 'answered'


def test_correction_invalidates_question_and_unrelated_context_does_not_ask(harness):
    client, app, _, targets, _ = harness
    cv = ready(harness)
    targets.context_value = {'id': 'target', 'version': 1, 'type': 'career_exploration', 'confirmed': True, 'skill_ids': ['skill:unrelated']}
    result = client.post(f"/api/v1/cv/{cv['id']}/clarifications/prepare", json=mutation(cv['version'], career_target_id='target', career_target_version=1))
    assert result.json()['questions'] == []
    cv = client.get('/api/v1/cv/' + cv['id']).json()
    cv, questions = prepare_context(harness, cv)
    question = questions[0]
    changed = client.patch(f"/api/v1/cv/{cv['id']}/items/{question['item_id']}", json=mutation(cv['version'], action='remove')).json()
    response = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{question['id']}", json=mutation(changed['version'], action='answer', answer='I wrote code.'))
    assert response.status_code == 409


def test_distinct_uncertainties_keep_partial_and_separate_literal_answers(harness):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [{'kind': 'skill', 'title': 'SQL',
        'description': 'Independent SQL queries for a personal dataset.', 'explicit': True,
        'evidence': [{'block_id': 'b3', 'excerpt': 'Independent SQL queries for a personal dataset.'}],
        'uncertainties': ['proficiency', 'duration']}]}
    cv, questions = prepare_context(harness, ready(harness))
    proficiency = next(question for question in questions if question['uncertainty'] == 'proficiency')
    duration = next(question for question in questions if question['uncertainty'] == 'duration')
    def answer_question(question, version, explanation):
        response = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{question['id']}",
                              json=mutation(version, action='answer', answer=explanation))
        assert response.status_code == 200, response.text
        return response.json()
    partial = answer_question(proficiency, cv['version'], 'I can write basic joins with guidance.')
    reloaded = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(q for q in reloaded['clarifications'] if q['id'] == duration['id'])['status'] == 'unanswered'
    assert reloaded['items'][0]['uncertainties'] == ['duration']
    complete = answer_question(duration, partial['version'], 'I do not know how many months I used it.')
    effective = complete['items'][0]
    assert {q['answer'] for q in complete['clarifications']} == {
        'I can write basic joins with guidance.', 'I do not know how many months I used it.'}
    assert effective['experience_months'] is None and effective['proficiency'] == 'basic joins'
    assert next(q for q in complete['clarifications'] if q['id'] == duration['id'])['resolution'] == 'unanswerable'
    assert all(q['status'] == 'answered' for q in complete['clarifications'])
    assert effective['uncertainties'] == ['duration']
    revised = answer_question(proficiency, complete['version'], 'I can write basic joins independently.')
    assert next(q for q in revised['clarifications'] if q['id'] == proficiency['id'])['answer'] == 'I can write basic joins independently.'
    assert next(q for q in revised['clarifications'] if q['id'] == duration['id'])['answer'] == 'I do not know how many months I used it.'
    assert revised['skills'][0]['sources'][0]['assistance'] == 'independent'
    assert revised['effective_version'] == cv['effective_version'] + 2
