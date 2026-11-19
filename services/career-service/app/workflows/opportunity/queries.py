"""Five fixed research intents; The model owns the role-specific search wording."""
from app.schemas.opportunity import CATEGORIES

ACTIVITIES={
 'interview_intelligence':'searching_interviews',
 'internship_insights':'searching_internship',
 'career_progression':'searching_progression',
 'conversion_outcomes':'searching_conversion',
 'company_intelligence':'searching_company',
}

# What a person would type after the employer and role: short, without location or year.
BROAD_TOPICS={
 'interview_intelligence':'interview process questions',
 'internship_insights':'internship experience',
 'career_progression':'salary career progression',
 'conversion_outcomes':'return offer conversion rate',
 'company_intelligence':'work culture',
}

def broad_query(public,category):
    """A plain search that runs before the model's targeted queries, which are often too specific to match."""
    if not public:return None
    who=' '.join(' '.join((public.get(key) or '').split()) for key in ('company','role')).strip()
    return f'{who[:140]} {BROAD_TOPICS[category]}' if who else None

def planned_queries(plan,limit,public=None):
    # Each required category has a nonempty validated QueryPlan list. Keep category
    # boundaries even when two categories happen to use the same public query.
    def queries(category):
        broad=broad_query(public,category)
        return list(dict.fromkeys(' '.join(q.split()) for q in [*([broad] if broad else []),*getattr(plan,category)]))[:limit]
    return {category:queries(category) for category in CATEGORIES}
