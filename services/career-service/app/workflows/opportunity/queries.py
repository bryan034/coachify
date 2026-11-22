"""Search wording: the model writes one query per search group; topic gap searches use plain employer-and-role wording."""
from app.schemas.opportunity import CATEGORIES
from .topics import GROUPS,TOPICS,group_query,topic_query

ACTIVITIES={
 'interview_intelligence':'searching_interviews',
 'internship_insights':'searching_internship',
 'career_progression':'searching_progression',
 'conversion_outcomes':'searching_conversion',
 'company_intelligence':'searching_company',
}


def planned_queries(plan,public=None):
    def query(group):
        value=(getattr(plan,group,None) if plan is not None else None) or group_query(public,group)
        return ' '.join(value.split())[:180] if value else None
    return {group:value for group in GROUPS if (value:=query(group))}


def topic_queries(public,searches):
    def queries(topic):
        values=[topic_query(public,topic,attempt) for attempt in range(searches)]
        return list(dict.fromkeys(' '.join(q.split())[:180] for q in values if q))
    return {topic:queries(topic) for topic in TOPICS}


def topic_map(value):
    """Per-topic job state; jobs saved before per-topic research hold per-category lists instead."""
    return {k:v for k,v in (value or {}).items() if k not in CATEGORIES} if isinstance(value,dict) else {}
