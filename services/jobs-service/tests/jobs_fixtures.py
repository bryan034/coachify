"""Synthetic provider records and adapters. No test calls a live provider or reads environment files."""
from datetime import datetime, timezone

NOW = datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc)
GREENHOUSE = {'provider': 'greenhouse', 'board': 'synthetic-gh', 'company': 'Synthetic Bank', 'industry': 'financial_services'}
LEVER = {'provider': 'lever', 'board': 'synthetic-lv', 'company': 'Synthetic Freight', 'industry': 'logistics'}
ASHBY = {'provider': 'ashby', 'board': 'synthetic-ab', 'company': 'Synthetic Labs', 'industry': 'artificial_intelligence'}


def greenhouse_job(identifier=1, title='Software Engineer', location='Singapore', **extra):
    return {'id': identifier, 'title': title, 'location': {'name': location}, 'first_published': '2026-10-08T02:58:03-04:00',
            'updated_at': '2026-11-01T00:00:00-04:00', 'application_deadline': None,
            'absolute_url': f'https://job-boards.greenhouse.io/synthetic-gh/jobs/{identifier}',
            'content': '&lt;p&gt;Build C++ services with Python.&lt;/p&gt;&lt;script&gt;steal()&lt;/script&gt;',
            'departments': [{'name': 'Engineering'}],
            'metadata': [{'name': 'Employment Type', 'value': 'Full-time'}, {'name': 'Workplace Type', 'value': 'Hybrid'}], **extra}


def lever_job(identifier='a1', title='Operations Intern', location='Singapore', **extra):
    return {'id': identifier, 'text': title, 'createdAt': 1785824225174,
            'categories': {'commitment': 'Full-time', 'department': 'Operations', 'location': location, 'allLocations': [location]},
            'workplaceType': 'onsite', 'descriptionPlain': 'Support regional logistics.', 'lists': [{'text': 'Skills', 'content': '<li>SQL</li>'}],
            'hostedUrl': f'https://jobs.lever.co/synthetic-lv/{identifier}', 'applyUrl': f'https://jobs.lever.co/synthetic-lv/{identifier}/apply', **extra}


def ashby_job(identifier='b1', title='Research Scientist', location='SG - Singapore', **extra):
    return {'id': identifier, 'title': title, 'location': location, 'secondaryLocations': [], 'publishedAt': '2026-03-06T04:01:10.215+00:00',
            'employmentType': 'Contract', 'workplaceType': 'Remote', 'isRemote': True, 'isListed': True, 'department': 'Research',
            'descriptionPlain': 'Evaluate language models.', 'address': {'postalAddress': {'addressCountry': 'Singapore'}},
            'jobUrl': f'https://jobs.ashbyhq.com/synthetic-ab/{identifier}', 'applyUrl': f'https://jobs.ashbyhq.com/synthetic-ab/{identifier}/application', **extra}


class SyntheticUpstream:
    """Each bearer maps to one verified account with completed onboarding."""
    async def account(self, token):
        from elo_shared.runtime import Problem
        accounts = {'Bearer owner': 'owner-account', 'Bearer other': 'other-account'}
        if token not in accounts:
            raise Problem('Sign in to continue.', 401, 'session')
        return {'id': accounts[token], 'email_verified': True, 'profile': {'onboarding_complete': True}, 'token': token}
