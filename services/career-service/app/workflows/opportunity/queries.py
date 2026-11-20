"""Per-topic search wording: the model owns role-specific queries, with plain employer-and-role fallbacks."""
from app.schemas.opportunity import CATEGORIES
from .topics import TOPICS,topic_query

ACTIVITIES={
 'interview_intelligence':'searching_interviews',
 'internship_insights':'searching_internship',
 'career_progression':'searching_progression',
 'conversion_outcomes':'searching_conversion',
 'company_intelligence':'searching_company',
}


def planned_queries(plan,searches,public=None):
    """Up to `searches` distinct queries per topic: the planner's wording first, then plain fallbacks."""
    def queries(topic):
        planned=list(getattr(plan,topic,None) or []) if plan is not None else []
        fallbacks=[topic_query(public,topic,attempt) for attempt in range(searches)]
        values=[' '.join(q.split())[:180] for q in [*planned,*fallbacks] if q]
        return list(dict.fromkeys(values))[:searches]
    return {topic:queries(topic) for topic in TOPICS}


def topic_map(value):
    """Per-topic job state; jobs saved before per-topic research hold per-category lists instead."""
    return {k:v for k,v in (value or {}).items() if k not in CATEGORIES} if isinstance(value,dict) else {}
