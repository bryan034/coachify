"""Versioned account-embedded intake; receipts share the existing operational ledger."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from pydantic import ValidationError
from elo_shared.skills_profile import SkillsProfile, SKILL_FIELDS
from app.domain.capabilities import CapabilityConflict, skill_id


class SkillsProfileRepository:
    def __init__(self, capabilities):
        self.capabilities = capabilities
        self.accounts, self.receipts = capabilities.accounts, capabilities.receipts

    def current(self, owner):
        return self.parse(self.capabilities.account(owner)).model_dump(mode='json')

    @staticmethod
    def parse(account):
        try:
            return SkillsProfile.model_validate(account.get('skills_profile', {}))
        except ValidationError:
            raise HTTPException(503, 'Saved skills profile is unavailable. Retry without replacing your existing information.') from None

    def seal(self, account):
        last = account.get('skills_profile_last_mutation')
        if last:
            self.receipts.update_one({'user_id': account['id'], 'mutation_id': last}, {'$set': {'completed': True}})

    def save(self, owner, request):
        body = request.model_dump(mode='json')
        encoded = json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
        if len(encoded) > 384 * 1024:
            raise HTTPException(413, 'This profile is too large. Shorten its descriptions; your saved profile remains available.')
        fingerprint = hashlib.sha256(encoded).hexdigest()
        mutation = 'skills-profile:' + str(request.mutation_id)
        account = self.capabilities.account(owner)
        query = {'user_id': account['id'], 'mutation_id': mutation}
        receipt = self.receipts.find_one(query)
        if receipt and receipt['fingerprint'] != fingerprint:
            raise CapabilityConflict('This request key was used for different profile changes.')
        self.seal(account)
        if receipt and (receipt.get('completed') or account.get('skills_profile_last_mutation') == mutation):
            return self.current(owner)
        previous = self.parse(account)
        if previous.version != request.expected_version:
            latest = self.capabilities.account(owner)
            replay = self.receipts.find_one(query)
            if replay and replay['fingerprint'] == fingerprint and (replay.get('completed') or latest.get('skills_profile_last_mutation') == mutation):
                return self.current(owner)
            raise CapabilityConflict('Your skills profile changed elsewhere. Reload and review your draft.')
        timestamp = datetime.now(timezone.utc).isoformat()
        profile = SkillsProfile(version=previous.version + 1, status=request.status,
            saved_at=timestamp if request.status == 'saved' else previous.saved_at,
            areas=request.areas, entries=request.entries).model_dump(mode='json', exclude={'skill_groups','skill_subgroups'})
        declarations = deepcopy(account.get('capability_declarations', []))
        if request.status == 'saved':
            # Publish confirmed manual skills through the existing declaration authority.
            # Preserve ordinary declarations; intake skills retain stable entry identities.
            generated = []
            for entry in request.entries:
                for skill in entry.skills:
                    identifier = str(uuid5(NAMESPACE_URL, account['id'] + ':intake:' + str(entry.id) + ':' + skill_id(skill.name)))
                    description = entry.title + ': ' + skill.description
                    if len(description) > 2000:
                        raise HTTPException(422, 'Shorten this skill description to fit 2000 characters including the experience title.')
                    old = next((d for d in declarations if d['id'] == identifier), None)
                    contributions = deepcopy((old or {}).get('contributions', []))
                    own_contribution = {'id': identifier, 'description': description,
                                        'created_at': (old or {}).get('created_at', timestamp)}
                    dimension_ids = {field: str(uuid5(NAMESPACE_URL, identifier + ':dimension:' + field)) for field in SKILL_FIELDS}
                    owned_ids = {identifier, *dimension_ids.values()}
                    dimensions = []
                    for field, value in skill.dimensions.items():
                        statement = field.capitalize() + ': ' + (value.value or value.status.replace('_', ' '))
                        if len(statement) > 2000:
                            raise HTTPException(422, 'Shorten this skill dimension to fit 2000 characters including its field label.')
                        old_dimension = next((c for c in contributions if c['id'] == dimension_ids[field]), None)
                        dimensions.append({'id': dimension_ids[field], 'description': statement,
                            'created_at': (old_dimension or {}).get('created_at', timestamp)})
                    contributions = [own_contribution] + dimensions + [c for c in contributions if c['id'] not in owned_ids]
                    if len(contributions) > 10:
                        raise HTTPException(422, 'This skill has more than ten supporting descriptions. Review its existing manual descriptions before saving.')
                    generated.append({**(old or {}), 'id': identifier, 'name': skill.name, 'description': description,
                        'skill_id': skill_id(skill.name), 'provenance': 'user_declared',
                        'proficiency': None, 'experience_months': None, 'independence': None,
                        'source_entry_id': str(entry.id), 'contributions': contributions,
                        'attached_to': (old or {}).get('attached_to'),
                        'attached_source_fingerprint': (old or {}).get('attached_source_fingerprint'),
                        'attachment_history': (old or {}).get('attachment_history', []),
                        'created_at': (old or {}).get('created_at', timestamp),
                        'updated_at': old['updated_at'] if old and old['description'] == description and old['contributions'] == contributions else timestamp})
            generated_ids = {d['id'] for d in generated}
            retained = [d for d in declarations if not d.get('source_entry_id')]
            for old in declarations:
                if not old.get('source_entry_id') or old['id'] in generated_ids: continue
                owned = {old['id'], *(str(uuid5(NAMESPACE_URL, old['id'] + ':dimension:' + field)) for field in SKILL_FIELDS)}
                independent = [c for c in old['contributions'] if c['id'] not in owned]
                if independent:
                    retained.append({**old, 'source_entry_id': None, 'description': independent[0]['description'],
                                     'contributions': independent, 'updated_at': timestamp})
            declarations = retained + generated
            if len(declarations) > 100:
                raise HTTPException(422, 'A profile can contain up to 100 manual skills. Combine repeated descriptions before saving.')
        declaration_version = account.get('declarations_version', 0)
        values = {'skills_profile': profile, 'skills_profile_last_mutation': mutation,
                  'capability_declarations': declarations,
                  'declarations_version': declaration_version + int(declarations != account.get('capability_declarations', []))}
        candidate = {**query, 'fingerprint': fingerprint, 'completed': False, 'values': values,
                     'base_declarations_version': declaration_version,
                     'base_capability_mutation': account.get('capability_last_mutation'),
                     'base_profile_mutation': account.get('skills_profile_last_mutation'),
                     'created_at': datetime.now(timezone.utc)}
        try:
            self.receipts.insert_one(candidate)
        except DuplicateKeyError:
            candidate = self.receipts.find_one(query)
            if candidate['fingerprint'] != fingerprint:
                raise CapabilityConflict('This request key was used for different profile changes.')
            if candidate.get('completed'): return self.current(owner)
            values = candidate['values']
        # Account revision marker also fences two first writes when no profile exists.
        declaration_version = candidate['base_declarations_version']
        result = self.accounts.update_one({'id': account['id'],
            'skills_profile_last_mutation': candidate['base_profile_mutation'],
            'capability_last_mutation': candidate['base_capability_mutation'],
            **({'$or': [{'declarations_version': 0}, {'declarations_version': {'$exists': False}}]}
               if declaration_version == 0 else {'declarations_version': declaration_version})}, {'$set': values})
        latest = self.capabilities.account(owner)
        if not result.modified_count and latest.get('skills_profile_last_mutation') != mutation:
            replay = self.receipts.find_one(query)
            if not replay.get('completed'):
                raise CapabilityConflict('Your skills or profile changed elsewhere. Reload before saving again.')
        self.seal(latest)
        return self.current(owner)
