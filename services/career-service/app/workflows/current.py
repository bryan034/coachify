"""Live workspace fencing for transient chat and its provider quota retries."""
from starlette.concurrency import run_in_threadpool as thread
from app.ai.errors import AIError
from app.repositories.goals import GoalError


def workspace_revision(repository, owner, session, expected_version):
    async def current():
        try:
            row = await thread(repository.check, owner, session, expected_version)
            # Also check the active review's canonical goal.
            identifier = row['workspace'].get('review_id')
            if identifier:
                return str(await thread(repository.reviews.version, identifier, owner))
            return str(row['workspace'].get('revision', expected_version))
        except GoalError as error:
            if error.status not in (404, 409): raise
            raise AIError('stale_input', True) from None
    return current
