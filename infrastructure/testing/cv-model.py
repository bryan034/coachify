"""Synthetic OpenAI-compatible HTTP boundary for disposable integration tests.

Refuses non-fixture documents. Never deployed by the application Compose file.
It tests transport/schema validation and persistence, not model intelligence.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def interpret_fixture(value):
    """Fixed labelled examples, not a substitute for live semantic evaluation."""
    item, question, answer = value['source_item'], value['question'], value['answer']
    if item['title'] not in {'Team dashboard', 'Synthetic reporting internship', 'Python', 'SQL', 'Synthetic University'}:
        raise ValueError('Only known synthetic source items are accepted')
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
    if answer in known:
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
            if 'source_item' in value:
                try: result = interpret_fixture(value)
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


ThreadingHTTPServer(('0.0.0.0', 9000), Handler).serve_forever()
