"""Recover the one-time activation recorded with a CV's first successful extraction."""
from copy import deepcopy
from app.domain.errors import Conflict


def first_ready(previous, document):
    return (document['operation']['status'] == 'ready' and not previous.get('auto_selection_done')
            and not previous.get('original_items'))


def auto_select(repository, files, owner, cv_id):
    with files.lock(cv_id):
        cv = repository.get(owner, cv_id)
        if not cv or 'auto_selection_revision' not in cv:
            return
        previous = repository.selection(owner)
        unchanged = previous.get('revision', 0) == cv['auto_selection_revision']
        newest = not any(other['_id'] != cv_id and other['created_at'] > cv['created_at']
                         and other['operation']['status'] == 'ready' for other in repository.list(owner))
        if (unchanged and newest and cv['operation']['status'] == 'ready'
                and cv['original_items'] and previous['selected_cv_id'] != cv_id):
            selection = deepcopy(previous)
            selection.update(selected_cv_id=cv_id, version=previous['version'] + 1,
                             revision=previous.get('revision', 0) + 1)
            try:
                repository.select(previous, selection)
            except Conflict:
                return
        finished = deepcopy(cv)
        finished.pop('auto_selection_revision')
        finished['auto_selection_done'] = True
        finished['revision'] += 1
        try:
            repository.replace(cv, finished)
        except Conflict:
            pass
