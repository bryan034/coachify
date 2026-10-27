"""Assess manual-to-CV relationships without changing either source of truth."""
from app.domain.capabilities import digest, effective_items, skill_id, skills_for


def source_fingerprint(item):
    fields = ('id', 'kind', 'title', 'description', 'removed', 'skill_ids', 'skill_names',
              'proficiency', 'experience_months', 'support_uncertain', 'skill_claims',
              'start_date', 'end_date', 'ongoing', 'supporting_item_ids')
    return digest({key: item.get(key) for key in fields})


def assess_links(repository, owner, declarations, selected_cv_id):
    documents = {}
    links = []
    for declaration in declarations:
        attached = declaration.get('attached_to')
        result = {'declaration_id': declaration['id'], 'status': 'standalone',
                  'selected': False, 'current_cv_version': None}
        if attached:
            identifier = attached['cv_id']
            result['selected'] = identifier == selected_cv_id
            if identifier not in documents:
                documents[identifier] = repository.get(owner, identifier)
            document = documents[identifier]
            result['status'] = 'unavailable'
            if document:
                result['current_cv_version'] = document['version']
                items = effective_items(document)
                item = next((row for row in items if row['id'] == attached['item_id']), None)
                canonical = declaration.get('skill_id') or skill_id(declaration['name'])
                matching = any(row['skill_id'] == canonical and attached['item_id'] in row['item_ids'] for row in skills_for(items))
                if not item or item['removed'] or not matching:
                    result['status'] = 'removed'
                elif document['operation']['status'] == 'ready' and not document.get('candidate'):
                    saved = declaration.get('attached_source_fingerprint')
                    result['status'] = ('unverified' if not saved else
                                        'current' if saved == source_fingerprint(item) else 'changed')
        links.append(result)
    return links
