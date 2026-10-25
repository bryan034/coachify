"""Read only through CV APIs, forwarding the owner's revocable session."""
import httpx
from app.repositories.goals import GoalError
from app.schemas.analysis import CvSnapshot
from app.schemas.goals import CvSummary


class CvClient:
    def __init__(self, client):
        self.client = client

    async def list(self, token):
        try:
            response = await self.client.get('/api/v1/cv', headers={'Authorization': token})
            if response.status_code != 200:
                raise ValueError
            body = response.json()
            return [CvSummary.model_validate(row) for row in body['items']]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise GoalError('Saved CVs are unavailable. Retry or continue without a CV.', 503) from None

    async def get(self, identifier, token, owner):
        try:
            response = await self.client.get('/api/v1/cv/' + identifier, headers={'Authorization': token})
            if response.status_code == 404:
                raise GoalError('That CV is unavailable. Choose another or continue without it.', 409)
            if response.status_code != 200:
                raise ValueError
            cv = CvSnapshot.model_validate(response.json())
            if cv.user_id != owner or cv.extraction_status != 'succeeded':
                raise GoalError('Choose a successfully processed CV owned by this account.')
            return cv
        except (httpx.HTTPError, ValueError):
            raise GoalError('The CV service is unavailable. Retry or continue without a CV.', 503) from None
