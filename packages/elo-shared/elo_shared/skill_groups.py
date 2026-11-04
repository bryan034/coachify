"""Display categories for skills, shared by every service that returns skills.

A group only decides where a skill is shown. It is derived on read and never stored,
hashed or used to compare skills: use the canonical registry ID for identity.
Extraction rarely supplies a category, so the name decides first and the supplied
category is only a fallback.
"""
import re
from elo_shared.skills import normalize

OTHER_SKILLS = 'Other skills'


def _words(*terms):
    return re.compile(r'(^|[^a-z0-9+#])(' + '|'.join(terms) + r')($|[^a-z0-9+#])')


# Order matters: the first match wins, so specific groups come before broad ones.
_GROUPS = (
    ('Languages', _words('english', 'mandarin', 'chinese', 'malay', 'tamil', 'hindi', 'japanese', 'korean', 'french',
                         'german', 'spanish', 'cantonese', 'arabic', 'bahasa'), None),
    ('Data & analytics', _words('sql', 'structured query language', 'mysql', 'postgresql', 'postgres', 'mongodb', 'nosql', 'databases?', 'excel',
                                'tableau', 'power ?bi', 'data[a-z -]*', 'statistics', 'statistical', 'analytics',
                                'machine learning', 'ml', 'deep learning', 'pandas', 'numpy', 'etl', 'spark', 'bigquery',
                                'forecasting'), re.compile(r'\bdata|analytic')),
    ('Cloud & DevOps', _words('docker', 'kubernetes', 'k8s', 'aws', 'amazon web services', 'azure', 'gcp', 'google cloud', 'cloud[a-z -]*', 'ci/?cd',
                              'devops', 'linux', 'terraform', 'nginx', 'github actions', 'jenkins', 'deployment'),
     re.compile(r'\bcloud|devops|infrastructure')),
    ('Technical coding', _words('python', 'java', 'javascript', 'typescript', r'c\+\+', 'c#', 'golang', 'rust', 'ruby',
                                'php', 'kotlin', 'swift', 'html', 'css', r'react(\.?js)?', r'next\.?js', r'node\.?js', 'angular',
                                'vue', 'fastapi', 'django', 'flask', 'spring', 'git', 'github', 'rest', 'apis?',
                                '[a-z ]*api design', 'backend', 'frontend', 'full[- ]?stack', 'programming', 'coding',
                                'software (development|engineering)', 'web development', 'unit testing', 'testing',
                                'debugging', 'algorithms'), re.compile(r'programming|coding|software|technical|framework')),
    ('Software & project management', _words('agile', 'scrum', 'kanban', 'jira', 'confluence',
                                             'project (management|planning)', 'product management',
                                             'program management', 'roadmapping', 'planning', 'sprint planning',
                                             'requirements[a-z ]*', 'release management', 'risk management',
                                             'prioriti[sz]ation'), re.compile(r'management|planning')),
    ('Design', _words('figma', 'sketch', 'adobe[a-z ]*', 'photoshop', 'illustrator', 'ui', 'ux', 'ui/ux',
                      'user research', 'wireframing', 'prototyping', '[a-z ]*design'), re.compile(r'design')),
    ('Communication & leadership', _words('[a-z ]*communication', 'teamwork', 'collaboration', 'leadership', 'mentoring',
                                          'presentations?', 'public speaking', 'negotiation', '[a-z ]*writing',
                                          'stakeholder[a-z ]*', 'customer service', 'team management',
                                          'problem[- ]solving', 'critical thinking'),
     re.compile(r'soft|interpersonal|communication|leadership|transferable')),
    ('Business & finance', _words('finance', 'financial[a-z ]*', 'accounting', 'marketing', 'sales', 'business[a-z ]*',
                                  'market research', 'strategy', 'operations', 'procurement', 'seo', 'budgeting',
                                  'consulting'), re.compile(r'business|finance|marketing')),
)
# Short names that would match inside ordinary phrases, so they must be the whole name.
_EXACT_CODING = {'c', 'r', 'go', 'matlab'}


def skill_group(name, category=None):
    skill = normalize(name)
    if skill in _EXACT_CODING:
        return 'Technical coding'
    for group, names, _ in _GROUPS:
        if names.search(skill):
            return group
    hint = normalize(category or '')
    for group, _, hints in _GROUPS:
        if hints and hints.search(hint):
            return group
    return OTHER_SKILLS


def skill_groups(skills):
    """Map each skill's exact displayed name to its group, from (name, category) pairs."""
    return {name: skill_group(name, category) for name, category in skills}
