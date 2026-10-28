"""Public, factual activity events; never model thoughts or provider response prose."""
from contextvars import ContextVar

activity_observer=ContextVar('career_activity',default=None)
LABELS={
 'understanding_question':'Understanding your question about this goal…',
 'searching_question':'Searching public sources for your question…',
 'answering_question':'Structuring an answer from the available evidence…',
 'identifying_job':'Identifying the job title, employer, location and position…',
 'extracting_requirements':'Extracting skills, responsibilities and other requirements…',
 'searching_interviews':'Searching for relevant interview experiences…',
 'searching_internship':'Searching for relevant workplace and internship experiences…',
 'searching_company':'Looking up company context and career opportunities…',
 'checking_sources':'Checking sources against this career goal…',
 'saving_goal':'Saving your career goal and its category cards…',
 'preparing_summary':'Preparing your career-goal summary…',
 'research_complete':'Research is complete. Available findings have been saved.',
}

def activity(stage):
    observer=activity_observer.get()
    if observer and stage in LABELS:observer(stage)
