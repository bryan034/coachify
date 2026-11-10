"""Synthetic OpenAI-compatible HTTP boundary for disposable integration tests.

Refuses non-fixture documents. Never deployed by the application Compose file.
It tests transport/schema validation and persistence, not model intelligence.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


CHAT_MIXED_ANSWER = "I wrote the Python loader for six months with my tutor's help. I also used Pandas to clean the data. My teammate wrote SQL."
CHAT_EXTRA_CONTEXT = 'I also used Power BI for two months.'
CHAT_CORRECTION = 'Actually, I used Python for three months, not six.'
CHAT_PARTIAL_FAILURE = CHAT_MIXED_ANSWER + ' I cannot clarify my internship yet. SYNTHETIC_SECOND_ACTION_FAILURE'


def conversation_fixture(value):
    """Reviewed fixed chat cases; never a general natural-language interpreter."""
    message = value['message']
    items = value.get('items', [])
    if any(item.get('title') not in {'Team dashboard', 'Synthetic reporting internship', 'Python', 'SQL', 'Synthetic University'} for item in items):
        raise ValueError('Only known synthetic source items are accepted')
    project = next((item for item in items if item.get('kind') == 'project'), None)
    question = next((question for question in value.get('questions', []) if project and question.get('item_id') == project['id']), None)
    action = {'kind': 'clarify', 'item_id': project['id'] if project else None,
              'question_id': question['id'] if question else None, 'excerpt': message}
    if message in {CHAT_MIXED_ANSWER, CHAT_EXTRA_CONTEXT}:
        if not project or (not question and not value.get('interview')): raise ValueError('The synthetic project question must exist')
        return {'reply': 'I will update the explanation for Team dashboard.', 'actions': [action]}
    if message == CHAT_PARTIAL_FAILURE:
        work = next(item for item in items if item.get('kind') == 'experience')
        work_question = next((question for question in value.get('questions', []) if question.get('item_id') == work['id']), None)
        return {'reply': 'These statements concern the project and the internship separately.', 'actions': [
            {**action, 'excerpt': CHAT_MIXED_ANSWER},
            {'kind': 'clarify', 'item_id': work['id'], 'question_id': work_question['id'] if work_question else None,
             'excerpt': 'I cannot clarify my internship yet. SYNTHETIC_SECOND_ACTION_FAILURE'}]}
    if message == CHAT_CORRECTION:
        if not project or (not question and not value.get('interview')): raise ValueError('The synthetic project question must exist')
        return {'reply': 'Review this correction to the reported Python duration.', 'actions': [{**action, 'kind': 'correct'}]}
    if message in {'Why are you asking?', 'Why does that matter?', 'Why are you asking this question?'}:
        return {'reply': 'This distinguishes your own contribution from team work for the selected target. It does not establish whether you used the skill elsewhere.', 'actions': []}
    if message == 'What if I had six months of SQL experience?':
        return {'reply': 'That is a hypothetical question. Your saved CV facts remain as they are.', 'actions': []}
    if message == 'I use Figma to make posters for my student society.':
        return {'reply': 'Review the proposed manual capability.', 'actions': [{'kind': 'add_capability', 'name': 'Figma', 'excerpt': message}]}
    if message == 'I also practise Python in weekly synthetic exercises.':
        return {'reply': 'Review the proposed manual capability and any matching source.', 'actions': [{'kind': 'add_capability', 'name': 'Python', 'excerpt': message}]}
    if message == 'I helped with that project.':
        candidates = [item['id'] for item in items if item.get('kind') in {'project', 'experience'}]
        return {'reply': 'Which source do you mean?', 'actions': [{'kind': 'clarify', 'excerpt': message, 'candidate_item_ids': candidates}]}
    if message == 'The Team dashboard project started in February 2023 and ended in 2024.':
        return {'reply': 'Review these project dates.', 'actions': [{**action, 'kind': 'correct', 'fields': {'start_date': '2023-02', 'end_date': '2024'}}]}
    if message == 'Remove the Team dashboard project.':
        return {'reply': 'Review the removal of this project.', 'actions': [{**action, 'kind': 'remove'}]}
    if message == 'I do not know.':
        active = value.get('active_question') or {}
        return {'reply': 'Unknown details can remain unknown.', 'actions': [{'kind': 'clarify', 'item_id': active.get('item_id'), 'question_id': active.get('id'), 'excerpt': message}]}
    if message == 'SYNTHETIC_CHAT_PROVIDER_FAILURE':
        raise RuntimeError('Deliberate synthetic chat outage')
    if message == 'SYNTHETIC_CHAT_INVALID_SOURCE':
        return {'reply': 'This synthetic output deliberately references a foreign source.', 'actions': [{**action, 'item_id': 'not-an-owned-item'}]}
    raise ValueError('This message is not in the reviewed synthetic chat fixture set')


def interpret_fixture(value):
    """Fixed labelled examples, not a substitute for live semantic evaluation."""
    item, question, answer = value['source_item'], value['question'], value['answer']
    if item['title'] not in {'Team dashboard', 'Synthetic reporting internship', 'Python', 'SQL', 'Synthetic University'}:
        raise ValueError('Only known synthetic source items are accepted')
    if answer == CHAT_PARTIAL_FAILURE:
        if item['title'] == 'Synthetic reporting internship':
            raise RuntimeError('Deliberate synthetic second-action interpretation outage')
        if item['title'] != 'Team dashboard': raise ValueError('Unknown synthetic partial-failure source')
        answer = CHAT_MIXED_ANSWER  # Excerpts still occur verbatim in the actual full message.
    claims = []
    ids = list(dict.fromkeys(item['skill_ids'] + [c['skill_id'] for c in item.get('skill_claims', [])]))
    names = {key: key.removeprefix('skill:').title() for key in ids}
    def claim(identifier, attribution, excerpt=None, assistance='unknown', months=None):
        fields = ['attribution']
        if assistance != 'unknown': fields.append('assistance')
        if months is not None: fields.append('experience_months')
        return {'skill_id': identifier, 'name': names.get(identifier, identifier.removeprefix('skill:').title()),
                'attribution': attribution, 'assistance': assistance, 'proficiency': None,
                'experience_months': months, 'evidence_excerpt': excerpt, 'changed_fields': fields}
    known = {
        'I wrote the SQL queries. A teammate built the Python application, with guidance from our tutor.':
            {'skill:sql': ('personal', 'I wrote the SQL queries.'),
             'skill:python': ('team', 'A teammate built the Python application, with guidance from our tutor.')},
        "I wrote the Python loader for six months with my tutor's help. My teammate wrote SQL.":
            {'skill:python': ('personal', "I wrote the Python loader for six months with my tutor's help.", 'supervised', 6),
             'skill:sql': ('team', 'My teammate wrote SQL.')},
        "I wrote the Python loader for six months with my tutor's help. I also used Pandas to clean the data. My teammate wrote SQL.":
            {'skill:python': ('personal', "I wrote the Python loader for six months with my tutor's help.", 'supervised', 6),
             'skill:pandas': ('personal', 'I also used Pandas to clean the data.'),
             'skill:sql': ('team', 'My teammate wrote SQL.')},
    }
    unknown = {'I do not know my proficiency yet.', 'I do not know.',
        'I checked reporting output under supervision. I do not know the full Python implementation.'}
    if answer == CHAT_EXTRA_CONTEXT and question['uncertainty'] == 'claim':
        claims = [claim('skill:power bi', 'personal', CHAT_EXTRA_CONTEXT, months=2)]
        resolution, resolved, remaining = 'resolved', [question['uncertainty']], []
    elif answer == CHAT_CORRECTION and question['uncertainty'] == 'claim':
        corrected = claim('skill:python', 'personal', CHAT_CORRECTION, months=3)
        corrected['changed_fields'] = ['experience_months']
        claims = [corrected]
        resolution, resolved, remaining = 'resolved', [question['uncertainty']], []
    elif answer in known:
        updates = known[answer]
        for identifier in list(dict.fromkeys(ids + list(updates))):
            claims.append(claim(identifier, *updates[identifier]) if identifier in updates else claim(identifier, 'unknown'))
        resolution = 'partial' if any(c['attribution'] == 'unknown' for c in claims) else 'resolved'
        resolved = [question['uncertainty']] if resolution == 'resolved' else []
        remaining = [] if resolved else [question['uncertainty']]
    elif answer in unknown:
        if question['uncertainty'] in {'personal_contribution', 'responsibility'}:
            claims = [claim(identifier, 'unknown') for identifier in ids]
        resolution, resolved, remaining = 'unanswerable', [], [question['uncertainty']]
    elif answer == 'SYNTHETIC_INTERPRETATION_FAILURE':
        raise RuntimeError('Deliberate synthetic interpretation outage')
    elif answer == 'I completed the Computer Science diploma in 2024.':
        return {'item_id': item['id'], 'answer_revision': value['answer_revision'], 'resolution': 'resolved',
                'claims': [], 'dates': {'start_date': None, 'end_date': '2024', 'ongoing': False,
                    'changed_fields': ['end_date'], 'evidence_excerpt': answer}, 'statement_excerpt': answer,
                'resolved_uncertainties': ['qualification'], 'remaining_uncertainties': []}
    else:
        raise ValueError('This answer is not in the reviewed synthetic fixture set')
    return {'item_id': item['id'], 'answer_revision': value['answer_revision'], 'resolution': resolution,
            'claims': claims, 'dates': None, 'statement_excerpt': None,
            'resolved_uncertainties': resolved, 'remaining_uncertainties': remaining}


def semantic_fixture(value):
    """Approve only reviewed text/claim pairs, never arbitrary model output."""
    if any('SYNTHETIC_SECOND_ACTION_FAILURE' in block['text'] and 'I cannot clarify my internship yet.' in block['text'] for block in value['source_blocks']):
        raise RuntimeError('Deliberate synthetic second-action evidence outage')
    labelled_answers = [CHAT_MIXED_ANSWER, CHAT_EXTRA_CONTEXT,
        "I wrote the SQL queries. A teammate built the Python application, with guidance from our tutor.",
        "I wrote the Python loader for six months with my tutor's help. My teammate wrote SQL."]
    approved = set()
    for answer in labelled_answers:
        result = interpret_fixture({'source_item': {'id': 'fixture', 'title': 'Team dashboard',
            'skill_ids': ['skill:python', 'skill:sql']}, 'question': {'uncertainty': 'claim'},
            'answer': answer, 'answer_revision': 1})
        for claim in result['claims']:
            if not claim['evidence_excerpt']: continue
            for field in claim['changed_fields']:
                item = claim.get(field)
                if field == 'experience_months' or item in (None, 'unknown'): continue
                statement = (f"For {claim['name']}, attribution is {item}. Personal means the user actually performed it; team means teammates only; observed means watching only; denied means explicitly not personally performed."
                    if field == 'attribution' else f"For the user's {claim['name']} work, {field} is {item}.")
                approved.add((claim['evidence_excerpt'], statement))
    for name, text in [('Figma', 'I use Figma to make posters for my student society.'),
                       ('Python', 'I also practise Python in weekly synthetic exercises.')]:
        approved.add((text, f'The user personally performed {name}: {text}'))
    manual = 'I use Figma to make posters for my student society.'
    approved.add((manual, 'Experience title: Student society posters'))
    approved.add((manual, 'In experience Student society posters, the user personally performed Figma: ' + manual))
    blocks = {block['id']: block['text'] for block in value['source_blocks']}
    return {'supported': [ref['index'] for ref in value['summaries']
        if (blocks.get(ref['block_id']), ref['excerpt']) in approved]}


def intake_fixture(value):
    message = value['message']
    if message == 'SYNTHETIC_CHAT_PROVIDER_FAILURE':
        raise RuntimeError('Deliberate synthetic chat outage')
    if message != 'I use Figma to make posters for my student society.':
        raise ValueError('Unknown synthetic intake message')
    return {'reply': 'Your poster experience is ready to review.', 'entries': [{
        'id': None, 'kind': 'project', 'title': 'Student society posters', 'title_evidence': message,
        'skills': [{'name': 'Figma', 'description': message,
                    'evidence': [{'message_id': value['message_id'], 'quote': message}]}]}]}


def review_question_fixture(value):
    target = value['target']
    if target.get('source_title') not in {'Team dashboard', 'Synthetic reporting internship', 'Python', 'SQL', 'Synthetic University'}:
        raise ValueError('Unknown synthetic review source')
    return {'reply': f"What can you share about {target['field']} in {target['source_title']}? Unknown is fine.", 'actions': []}


def interview_fixture(value):
    """Finite labelled cases for the new interview protocol, not an agent fallback."""
    source = value.get('focused_source') or {}
    known = {'Team dashboard', 'Synthetic reporting internship', 'Python', 'SQL', 'Synthetic University'}
    if source.get('title') not in known:
        raise ValueError('Unknown synthetic interview source')
    if value['task'] == 'cv_interview_plan':
        if value.get('topic_question_budget', {}).get('remaining') == 0:
            next_source = next((item for item in value['sources']
                if item['id'] != source['id'] and item['kind'] in {'project', 'experience'}
                and not item.get('coverage') and item.get('questions_remaining', 0) > 0
                and item.get('clarification_targets')), None)
            if next_source:
                target = next_source['clarification_targets'][0]
                return {'action': 'ask', 'reply': f"What did you personally do in {next_source['title']}?",
                        'item_id': next_source['id'], 'targets': [{key: target[key] for key in ('field', 'skill_name') if key in target}]}
            return {'action': 'pause', 'reply': 'The synthetic interview can pause here with remaining details uncertain.'}
        fields = {f['field']: f['status'] for f in value.get('evidence_index', {}).values()
                  if f['item_id'] == source['id'] and not f.get('skill_name')}
        for field in ('personal_contribution', 'responsibilities', 'task_scope'):
            attempt = value['memory']['attempts'].get(source['id'] + ':' + field + ':', {})
            if fields.get(field) in {'supported', 'unknown', 'skipped', 'not_applicable'} or attempt.get('declined') or attempt.get('count', 0) >= 2:
                continue
            return {'action': 'ask', 'reply': f"What can you share about {field.replace('_', ' ')} in {source['title']}? Unknown is fine.",
                    'item_id': source['id'], 'targets': [{'field': field}]}
        return {'action': 'pause', 'reply': 'The synthetic interview can pause here with remaining details uncertain.'}
    if value['message'] in {'Stop here.', 'I want to stop now.'}:
        return {'intent': 'stop', 'reply': 'Paused.', 'actions': [], 'interpretations': []}
    active = value.get('active_question')
    uncertainty = (active or {}).get('uncertainty', 'claim')
    routed = conversation_fixture({'message': value['message'], 'items': value['sources'], 'interview': True,
        'questions': [{**active, 'uncertainty': uncertainty}] if active else [], 'active_question': active})
    interpretations = []
    for action in routed['actions']:
        if action['kind'] not in {'clarify', 'correct'} or action.get('fields'): continue
        if not action.get('item_id') or action.get('item_id') not in {s['id'] for s in value['sources']}:
            continue
        if action.get('item_id') != source['id']:
            other = next(s for s in value['sources'] if s['id'] == action['item_id'])
            if other['title'] == 'Team dashboard' and value['message'] in {CHAT_EXTRA_CONTEXT, CHAT_CORRECTION}:
                output = interpret_fixture({'source_item': {**other, 'skill_ids': ['skill:python', 'skill:sql']},
                    'question': {'uncertainty': 'claim'}, 'answer': value['message'], 'answer_revision': 1})
                output.pop('answer_revision')
                interpretations.append(output)
                continue
            if value['message'] != CHAT_PARTIAL_FAILURE or other['title'] != 'Synthetic reporting internship':
                raise ValueError('Unknown synthetic cross-source answer')
            interpretations.append({'item_id': other['id'], 'resolution': 'unanswerable', 'claims': [],
                'resolved_uncertainties': [], 'remaining_uncertainties': ['claim'],
                'review_evidence': [{'field': 'responsibilities', 'status': 'unknown', 'value': None,
                    'evidence': [{'source_id': 'answer', 'quote': action['excerpt']}]}]})
            continue
        output = interpret_fixture({'source_item': source, 'question': {'uncertainty': uncertainty},
            'answer': value['message'], 'answer_revision': 1})
        output.pop('answer_revision')
        interpretations.append(output)
    return {'intent': 'answer' if interpretations else 'change' if routed['actions'] else 'side_question',
            **routed, 'interpretations': interpretations}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != '/v1/chat/completions':
            return self.send_json(404, {'error': 'Unknown fixture route'})
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= 1024 * 1024:
            return self.send_json(413, {'error': 'Fixture request size'})
        try:
            request = json.loads(self.rfile.read(size))
            if request.get('model') != 'synthetic-integration-fixture':
                return self.send_json(422, {'error': 'Only the synthetic fixture model is accepted'})
            value = json.loads(request['messages'][-1]['content'])
            if value.get('task') in {'cv_interview_interpret', 'cv_interview_plan'}:
                result = interview_fixture(value)
                return self.send_json(200, {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]})
            if value.get('task') in {'skills_intake', 'skills_question'}:
                try:
                    result = intake_fixture(value) if value['task'] == 'skills_intake' else {
                        'reply': 'What can you share about your ' + (value['target'].get('field') or value['target']['area']) + '? Unknown is fine.', 'actions': []}
                except RuntimeError:
                    return self.send_json(503, {'error': 'Deliberate synthetic outage'})
                return self.send_json(200, {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]})
            if 'summaries' in value or value.get('task') == 'cv_review_question':
                try: result = semantic_fixture(value) if 'summaries' in value else review_question_fixture(value)
                except RuntimeError:
                    return self.send_json(503, {'error': 'Deliberate synthetic evidence outage'})
                return self.send_json(200, {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]})
            if value.get('task') == 'cv_conversation' or 'source_item' in value:
                try: result = conversation_fixture(value) if value.get('task') == 'cv_conversation' else interpret_fixture(value)
                except RuntimeError:
                    return self.send_json(503, {'error': 'Deliberate synthetic outage'})
                return self.send_json(200, {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]})
            blocks = value['source_blocks']
            text = '\n'.join(block['text'] for block in blocks)
            if 'SYNTHETIC_CV_FIXTURE_V1' not in text:
                return self.send_json(422, {'error': 'Only labelled synthetic CV fixtures accepted'})
            if 'SYNTHETIC_PROVIDER_FAILURE' in text:
                return self.send_json(503, {'error': 'Deliberate synthetic outage'})
            items = []
            for block in blocks:
                if block['text'].startswith('Education:'):
                    items.append({'kind': 'education', 'title': 'Synthetic University',
                                  'description': block['text'], 'explicit': True,
                                  'evidence': [{'block_id': block['id'], 'excerpt': block['text']}],
                                  'uncertainties': ['qualification'] if 'SYNTHETIC_C_SERIES_COMPLETION' in text else []})
                if block['text'].startswith('Project:'):
                    project_index = len(items)
                    items.append({'kind': 'project', 'title': 'Team dashboard',
                                  'description': block['text'], 'explicit': True,
                                  'evidence': [{'block_id': block['id'], 'excerpt': block['text']}],
                                  'skill_names': ['Python', 'SQL'],
                                  'uncertainties': ['personal_contribution']})
                    for name in ['Python', 'SQL']:
                        items.append({'kind': 'skill', 'title': name,
                                      'description': f'{name} is mentioned in the team project; personal contribution is unclear.',
                                      'explicit': False,
                                      'evidence': [{'block_id': block['id'], 'excerpt': name}],
                                      'skill_names': [name], 'supporting_items': [project_index],
                                      'uncertainties': ['proficiency']})
                if block['text'].startswith('Experience:'):
                    items.append({'kind': 'experience', 'title': 'Synthetic reporting internship',
                                  'description': block['text'], 'explicit': True,
                                  'evidence': [{'block_id': block['id'], 'excerpt': block['text']}],
                                  'skill_names': ['Python'], 'uncertainties': ['responsibility']})
            result = {'items': items}
            if 'SYNTHETIC_BAD_OUTPUT' in text:
                result = {'items': [{'invented': 'invalid schema'}]}
            self.send_json(200, {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]})
        except (KeyError, TypeError, ValueError):
            self.send_json(400, {'error': 'Invalid fixture request'})


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 9000), Handler).serve_forever()
