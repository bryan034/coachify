"""Manual skills intake. Profile owns the facts; CV owns bounded conversation history."""
from copy import deepcopy
import json
import httpx
from pydantic import ValidationError
from uuid import NAMESPACE_URL, uuid5
from starlette.concurrency import run_in_threadpool
from elo_shared.skills_profile import SkillsProfile, SkillsProfileWrite, FIELDS, SKILL_FIELDS
from app.domain.errors import Conflict, CvError
from app.schemas.intake import IntakeEvaluation

LABELS = {'work': 'work or internship experience', 'project': 'project',
          'education': 'education', 'interest': 'interests'}


def next_target(profile):
    for area in LABELS:
        entries = [e for e in profile['entries'] if e['kind'] == area]
        for entry in entries:
            for field in FIELDS[area]:
                if field not in entry['fields']:
                    return {'area': area, 'entry_id': entry['id'], 'title': entry['title'], 'field': field}
            for index, skill in enumerate(entry['skills']):
                for field in SKILL_FIELDS:
                    if field not in skill['dimensions']:
                        return {'area': area, 'entry_id': entry['id'], 'title': entry['title'],
                                'skill': skill['name'], 'skill_index': index, 'field': field}
        if area not in profile['areas']:
            return {'area': area, 'title': LABELS[area], 'field': None}
    return None


def skip_target(profile, target):
    if not target: return
    if not target.get('entry_id'):
        profile['areas'][target['area']] = 'skipped'
        return
    entry = next(e for e in profile['entries'] if e['id'] == target['entry_id'])
    fields = entry['skills'][target['skill_index']]['dimensions'] if 'skill_index' in target else entry['fields']
    fields[target['field']] = {'status': 'skipped', 'value': None, 'evidence': []}


def proposed_profile(current, evaluation, message, message_id):
    """Validate references locally; semantic equivalence is checked separately."""
    result, checks, blocks = deepcopy(current), [], []
    target = next_target(current)
    def evidence(refs, statement):
        for ref in refs:
            if ref['message_id'] != message_id or ref['quote'] not in message:
                raise ValueError('Intake interpretation cited a different statement. Your message is saved; retry.')
        identifier = str(len(blocks))
        blocks.append({'id': identifier, 'text': '\n'.join(ref['quote'] for ref in refs),
            'reference_context': target})
        checks.append({'block_id': identifier, 'excerpt': statement})
    for proposal in evaluation.entries:
        data = proposal.model_dump(mode='json')
        identifier = data['id'] or str(uuid5(NAMESPACE_URL, message_id + ':entry:' + str(len(result['entries']))))
        existing = next((e for e in result['entries'] if e['id'] == identifier), None)
        if data['id'] and (not existing or existing['kind'] != data['kind']):
            raise ValueError('Intake interpretation referred to another experience.')
        if data['title_evidence'] not in message:
            raise ValueError('The experience reference needs its supporting statement.')
        if not existing or existing['title'] != data['title']:
            evidence([{'message_id': message_id, 'quote': data['title_evidence']}], 'Experience title: ' + data['title'])
        entry = deepcopy(existing) if existing else {'id': identifier, 'kind': data['kind'], 'fields': {}, 'skills': []}
        entry['title'] = data['title']
        for name, field in data['fields'].items():
            if not field['evidence']:
                raise ValueError('Intake changes need the statement supporting the answer or uncertainty.')
            evidence(field['evidence'], f"For experience {entry['title']}, {name}: {field['value']}" if field['status'] == 'answered' else f"For experience {entry['title']}, the user says {name} is {field['status']}.")
            entry['fields'][name] = field
        for skill in data['skills']:
            previous = next((s for s in entry['skills'] if s['name'].casefold() == skill['name'].casefold()), None)
            if skill['description'] is not None:
                if not skill['evidence']: raise ValueError('A skill interpretation needs its supporting statement.')
                evidence(skill['evidence'], f"In experience {entry['title']}, the user personally performed {skill['name']}: {skill['description']}")
            elif previous:
                skill['description'], skill['evidence'] = previous['description'], previous['evidence']
            else: raise ValueError('A new skill needs a supported description of personal work.')
            for name, field in skill['dimensions'].items():
                if not field['evidence']: raise ValueError('Skill dimensions need their supporting answer.')
                evidence(field['evidence'], f"For {skill['name']}, {name}: {field['value']}" if field['status'] == 'answered' else f"For {skill['name']}, the user says {name} is {field['status']}.")
            if previous:
                skill['dimensions'] = {**previous['dimensions'], **skill['dimensions']}
                entry['skills'][entry['skills'].index(previous)] = skill
            else: entry['skills'].append(skill)
        if existing: result['entries'][result['entries'].index(existing)] = entry
        else: result['entries'].append(entry)
        result['areas'][entry['kind']] = 'answered'
    for area in evaluation.areas:
        evidence([{'message_id': message_id, 'quote': area.evidence}],
                 f"The user's {LABELS[area.area]} section is {area.status}.")
        result['areas'][area.area] = area.status
    for removal in evaluation.removals:
        entry = next((e for e in result['entries'] if e['id'] == str(removal.entry_id)), None)
        if not entry: raise ValueError('The experience to remove is unavailable.')
        subject = f"skill {removal.skill_name} from {entry['title']}" if removal.skill_name else f"experience {entry['title']}"
        evidence([{'message_id': message_id, 'quote': removal.evidence}], f'The user explicitly asks to remove the {subject}.')
        if removal.skill_name:
            if not any(s['name'].casefold() == removal.skill_name.casefold() for s in entry['skills']):
                raise ValueError('The skill to remove is unavailable.')
            entry['skills'] = [s for s in entry['skills'] if s['name'].casefold() != removal.skill_name.casefold()]
        else:
            result['entries'].remove(entry)
            if result['areas'].get(entry['kind']) == 'answered' and not any(e['kind'] == entry['kind'] for e in result['entries']):
                result['areas'].pop(entry['kind'])
    return SkillsProfile.model_validate(result).model_dump(mode='json'), blocks, checks


async def read_profile(app, account):
    try:
        response = await app.state.profile_client.get('/api/v1/profile/skills-profile',
            headers={'Authorization': account['authorization']})
        if response.status_code == 401: raise CvError('Your session ended. Sign in again.', 401)
        if response.status_code != 200: raise ValueError('Profile unavailable')
        return SkillsProfile.model_validate(response.json()).model_dump(mode='json')
    except (httpx.HTTPError, ValueError, ValidationError):
        raise CvError('Your skills profile is unavailable. Your conversation is saved; retry.', 503) from None


async def process_intake(service, app, account, conversation, route, token):
    from app.conversation.service import action_in, action_message, key
    owner, identifier = account['id'], conversation['_id']
    current = await read_profile(app, account)
    if not route.get('_profile_body') and route.get('_profile_version', current['version']) != current['version']:
        raise Conflict('Your profile changed after this question was shown. Review the latest summary before sending a new answer.')
    target = next_target(current)
    command = route.get('_command')
    candidate, reply = deepcopy(current), ''
    body = route.get('_profile_body')
    if body is None:
        if command == 'skip':
            skip_target(candidate, target)
            reply = 'Skipped. That detail remains unknown.'
        elif command not in {'review', 'continue', 'finish'}:
            focus = next((e for e in current['entries'] if target and e['id'] == target.get('entry_id')), None)
            payload = {'task': 'skills_intake', 'message': route['_text'], 'message_id': route['_turn_id'],
                'target': target, 'focus': focus,
                'entries': [{k: e[k] for k in ('id', 'kind', 'title')} for e in current['entries']],
                'history': [{'role': m['role'], 'text': m['text']} for m in conversation['messages'][-6:-2]]}
            background = await app.state.profile_client.get('/api/v1/profile', headers={'Authorization': account['authorization']})
            if background.status_code == 200:
                source = background.json()
                payload['background_context'] = {k: source[k] for k in ('education', 'employment', 'occupational_status') if k in source}
            if len(json.dumps(payload).encode()) > 96 * 1024:
                raise ValueError('This experience is too large to interpret safely. Send a focused update; your message is saved.')
            output, _ = await run_in_threadpool(service.route, owner, payload)
            evaluation = IntakeEvaluation.model_validate(output)
            candidate, blocks, checks = proposed_profile(current, evaluation, route['_text'], route['_turn_id'])
            if checks:
                supported = await run_in_threadpool(service.verify_intake, owner, blocks, checks)
                if any((ref['block_id'], ref['excerpt']) not in supported for ref in checks):
                    raise ValueError('Some interpreted details are not supported by your answer. Your message is saved; retry or clarify what you personally did.')
            reply = evaluation.reply
        if candidate != current or command == 'finish':
            body = SkillsProfileWrite(expected_version=current['version'], mutation_id=key(route['id'] + ':profile'),
                status='saved' if command == 'finish' else 'draft', areas=candidate['areas'],
                entries=candidate['entries']).model_dump(mode='json')
            def remember(document):
                action = action_in(document, route['id'])
                service.check_lease(action, token)
                action['_profile_body'] = body
            await run_in_threadpool(service.update, owner, identifier, remember)
    if body:
        await service.authenticate(app, account)
        response = await app.state.profile_client.put('/api/v1/profile/skills-profile',
            headers={'Authorization': account['authorization']}, json=body)
        if response.status_code == 409: raise Conflict('Your skills profile changed. Return to its summary and review the current information before sending a new answer.')
        if response.status_code != 200: raise CvError('Your profile could not be saved. Retry this saved action.', 503)
        candidate = SkillsProfile.model_validate(response.json()).model_dump(mode='json')
    target = next_target(candidate)
    if command == 'finish':
        question = 'Your skills profile is saved. You can return to the summary or add more experience at any time. Unanswered details remain uncertain.'
        target = None
    elif target:
        question_result, _ = await run_in_threadpool(service.route, owner, {
            'task': 'skills_question', 'target': target,
            'instruction': 'Ask one neutral question about this exact field. Accept partial/unknown answers and do not ask other fields.'})
        question = question_result['reply'] if isinstance(question_result, dict) else question_result.reply
    else:
        question = 'You can review and save your profile now, including any unknown details. Add another experience whenever you like.'
    def publish(document):
        action = action_in(document, route['id'])
        service.check_lease(action, token)
        action.update(status='saved', summary='Skills profile saved.' if command == 'finish' else 'Draft checked.',
                      _token=None, _lease_until=0)
        action_message(document, route['id'])['text'] = (reply + '\n\n' if reply else '') + question
        document['intake_target'] = target
        document['intake_profile_version'] = candidate['version']
        document['active_question'] = ({'id': key(str(target)), 'item_id': target.get('entry_id', target['area']),
            'title': target['title'], 'question': question} if target else None)
    await run_in_threadpool(service.update, owner, identifier, publish)
