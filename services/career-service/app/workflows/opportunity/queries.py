"""Five fixed research intents; Gemini owns the role-specific search wording."""
from app.schemas.opportunity import CATEGORIES

ACTIVITIES={
 'interview_intelligence':'searching_interviews',
 'internship_insights':'searching_internship',
 'career_progression':'searching_progression',
 'conversion_outcomes':'searching_conversion',
 'company_intelligence':'searching_company',
}

def planned_queries(plan,limit):
    # Each required category has a nonempty validated QueryPlan list. Keep category
    # boundaries even when two categories happen to use the same public query.
    return {category:list(dict.fromkeys(' '.join(q.split()) for q in getattr(plan,category)))[:limit]
            for category in CATEGORIES}
