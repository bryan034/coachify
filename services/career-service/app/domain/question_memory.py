"""Saved-first public question selection and exact-excerpt presentation."""
import re
from app.ai.context_contracts import ContextPlan
from app.domain.questions import blocked_task,opportunity_findings
from app.workflows.citations import summary_text,source_links
from app.ai.opportunity_contracts import evidence_passages
from app.schemas.opportunity import Finding
from app.schemas.analysis import ResearchSource
from app.repositories.goals import fingerprint,now

FOCUS_FIELDS={
 'compensation':{'compensation'},'career_progression':{'conversion_salary','career_path','full_time_role'},
 'conversion':{'conversion_rate','historical_cohort','offer_acceptance'},
 'interviews':{'recruitment_stages','interview_questions','difficulty','application_timeline','preparation_topics','candidate_experience'},
 'workplace':{'company_culture','team_culture','management','work_life_balance','mentorship','projects','benefits'},
}
FOCUS_WORDS={
 'compensation':r'\b(salary|salaries|stipend|compensation|pay|paid|remuneration|benefits?)\b|(?:SGD|S\$|USD|\$)\s*\d',
 'location':r'\b(location|located|based|office|remote|hybrid|singapore)\b',
 'eligibility':r'\b(eligib\w*|qualifications?|degree|diploma|citizen\w*|authorization|requirements?)\b',
 'dates':r'\b(deadline|start date|duration|application|closing|\d{4})\b',
 'role_details':r'\b(role|responsibilit\w*|requirements?|skills?|duties|work)\b',
 'interviews':r'\b(interview\w*|assessments?|screening|coding|rounds?|tests?)\b',
 'workplace':r'\b(culture|team|mentors?\w*|hours|overtime|balance|projects?|management|benefits?)\b',
 'career_progression':r'\b(career|progression|graduate|full.time|salary|conversion|return offer)\b',
 'conversion':r'\b(conversion|cohort|return offers?|acceptance|full.time)\b',
}

def direct_public_plan(message):
    """Only unambiguous, single-topic questions bypass model routing."""
    if blocked_task(message):return None
    text=message.casefold().strip().rstrip('?.!')
    match=re.fullmatch(r'(?:(?:what(?: is| are|\'s)?|tell me(?: about)?|how much(?: is| are)?)\s+)?(?:the |this (?:job|role)\'s )?(salary|pay|stipend|compensation|location)(?: (?:for|of) (?:this|the) (?:job|role|internship))?',text)
    if not match:return None
    focus='location' if match[1]=='location' else 'compensation'
    return ContextPlan(topic='role' if focus=='location' else 'opportunity',research_focus=focus,resolved_question=message)

def focused_saved_facts(focus,goal,research):
    facts=[];links={}
    def add(kind,data,sources=()):
        ref=f'f{len(facts)+1}';facts.append({'ref':ref,'kind':kind,'data':data})
        links[ref]=[s for s in research.get('sources',[]) if s.get('source_id') in sources]
    if focus=='location' and goal.get('location'):add('job_details',{'location':goal['location']})
    if focus=='compensation':
        for item in goal.get('non_skill_requirements',[]):
            if re.search(FOCUS_WORDS['compensation'],item.get('description',''),re.I):
                add('job_details',{'value':item['description']})
                links[facts[-1]['ref']]=[{'source_id':'goal-'+str(index),'url':url} for index,url in enumerate(item.get('source_urls',[]))]
    if focus in ('eligibility','role_details'):
        from app.domain.questions import facts_for
        from app.ai.qa_contracts import QuestionRoute
        return facts_for(QuestionRoute(topic='requirements' if focus=='eligibility' else 'role'),goal,research)
    if focus=='dates':
        for date in goal.get('job_dates',[]):add('job_details',{'value':date['text']})
    for item in opportunity_findings(research):
        if item.get('field') not in FOCUS_FIELDS.get(focus,set())|{focus}:continue
        add('opportunity_finding',{key:item[key] for key in ('field','value','confidence','scope','evidence_type') if key in item},item.get('source_ids',[]))
    return facts[:6],{k:v for k,v in links.items() if k in {f['ref'] for f in facts[:6]}},len(facts)>6

def exact_question_findings(focus,facts,links,*,require_focus=True):
    """Keep only topical verbatim source passages; generated answers are never stored."""
    sources=[]
    for values in links.values():
        for value in values:
            source=ResearchSource.model_validate(value)
            if source.source_id not in {s.source_id for s in sources}:sources.append(source)
    from app.workflows.opportunity.sources import pool
    sources=pool(sources)
    findings=[]
    for passage in evidence_passages(sources):
        text=passage['text'];source=sources[passage['source_ref']]
        if require_focus and not re.search(FOCUS_WORDS[focus],text,re.I):continue
        if sum(source.source_id in f.source_ids for f in findings)>=2:continue
        findings.append(Finding(finding_id='f'+fingerprint({'focus':focus,'quote':text,'url':source.url})[:16],
            field=focus,value=text,quotes=[text],source_ids=[source.source_id],confidence='low',
            scope='general',evidence_type='official' if source.platform=='employer' or source.reliability=='official' else 'third_party',last_verified_at=now()))
        if len(findings)==6:break
    used={sid for finding in findings for sid in finding.source_ids}
    return findings,[source for source in sources if source.source_id in used]

def excerpt_facts(findings,sources):
    links={};facts=[]
    for index,finding in enumerate(findings):
        ref=f'web{index}'
        facts.append({'ref':ref,'kind':'opportunity_finding','data':finding.model_dump(exclude={'quotes','source_ids'})})
        links[ref]=[s.model_dump(mode='json') for s in sources if s.source_id in finding.source_ids]
    return facts,links

def saved_fact_reply(facts,links,partial=False):
    points=['### Saved information']
    for fact in facts[:6]:
        data=fact['data'];value=data.get('value') or data.get('location') or data.get('description')
        if not value:continue
        qualifiers=[]
        if data.get('scope') and data['scope']!='exact':qualifiers.append('related or general context')
        if data.get('confidence'):qualifiers.append(data['confidence'].replace('_',' ')+' confidence')
        sources={s['source_id']:s['url'] for s in links.get(fact['ref'],[])}
        citations=source_links(sources,sources)
        point='- '+summary_text(str(value))+(' ('+', '.join(qualifiers)+')' if qualifiers else '')+(' '+citations if citations else '')
        if len('\n\n'.join([*points,point]))>3700:
            partial=True;break
        points.append(point)
    if len(points)==1:return None
    if partial:points.append('**Coverage:** Additional saved details are available in the research view.')
    return '\n\n'.join(points)
