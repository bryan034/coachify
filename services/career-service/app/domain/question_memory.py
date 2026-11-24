"""Saved-first public question selection and exact-excerpt presentation."""
from app.domain.questions import opportunity_findings, facts_for
from app.domain.source_scope import SINGAPORE, host, money_figures, target_place, verify
from app.workflows.citations import summary_text,source_links
from app.ai.opportunity_contracts import evidence_passages
from app.ai.passage_scope import MAX_SCOPED_PASSAGES
from app.schemas.opportunity import Finding
from app.schemas.analysis import ResearchSource
from app.repositories.goals import fingerprint,now
from app.workflows.opportunity.sources import pool
from app.ai.qa_contracts import QuestionRoute

MAX_QUESTION_FACTS = 6
MAX_QUESTION_FINDINGS = 6
PASSAGES_PER_SOURCE = 2

MAX_SAVED_REPLY_CHARS = 3700

FOCUS_FIELDS={
 'compensation':{'compensation'},'career_progression':{'conversion_salary','career_path','full_time_role'},
 'conversion':{'conversion_rate','historical_cohort','offer_acceptance'},
 'interviews':{'recruitment_stages','interview_questions','difficulty','application_timeline','preparation_topics','candidate_experience'},
 'workplace':{'company_culture','team_culture','management','work_life_balance','mentorship','projects','benefits'},
}
def focused_saved_facts(focus,goal,research,item_refs=()):
    facts=[];links={}
    def add(kind,data,sources=()):
        ref=f'f{len(facts)+1}';facts.append({'ref':ref,'kind':kind,'data':data})
        links[ref]=[s for s in research.get('sources',[]) if s.get('source_id') in sources]
    if focus=='location' and goal.get('location'):add('job_details',{'location':goal['location']})
    for position,item in enumerate(goal.get('non_skill_requirements',[])):
        if f'c{position}' in item_refs:
            add('job_details',{'value':item['description']})
            links[facts[-1]['ref']]=[{'source_id':'goal-'+str(index),'url':url} for index,url in enumerate(item.get('source_urls',[]))]
    if focus in ('eligibility','role_details'):
        return facts_for(QuestionRoute(topic='requirements' if focus=='eligibility' else 'role'),goal,research)
    if focus=='dates':
        for date in goal.get('job_dates',[]):add('job_details',{'value':date['text']})
    for item in opportunity_findings(research):
        if item.get('field') not in FOCUS_FIELDS.get(focus,set())|{focus}:continue
        add('opportunity_finding',{key:item[key] for key in ('field','value','confidence','scope','evidence_type') if key in item},item.get('source_ids',[]))
    return facts[:MAX_QUESTION_FACTS],{k:v for k,v in links.items() if k in {f['ref'] for f in facts[:MAX_QUESTION_FACTS]}},len(facts)>MAX_QUESTION_FACTS

def passage_finding(focus,text,source,*,verified=False,official=False,scope='general'):
    if verified:
        confidence='high' if official else 'medium'
        evidence='official' if official else 'candidate_reported' if source.platform=='reddit' else 'third_party'
    else:
        confidence='low';evidence='official' if source.platform=='employer' or source.reliability=='official' else 'third_party'
    return Finding(finding_id='f'+fingerprint({'focus':focus,'quote':text,'url':source.url})[:16],
        field=focus,value=text,quotes=[text],source_ids=[source.source_id],confidence=confidence,
        scope='exact' if verified else scope,evidence_type=evidence,last_verified_at=now())

def link_sources(links):
    sources=[]
    for values in links.values():
        for value in values:
            source=ResearchSource.model_validate(value)
            if source.source_id not in {s.source_id for s in sources}:sources.append(source)
    return pool(sources)

def question_passages(links):
    """Retrieved sources and their exact passages, in the order the scope model labels them."""
    sources=link_sources(links)
    return sources,[(sources[passage['source_ref']],passage['text']) for passage in evidence_passages(sources)][:MAX_SCOPED_PASSAGES]

def scope_input(focus,goal,passages,terms=None):
    place=target_place(goal)
    return {'target_market':'Singapore' if place==SINGAPORE else place,'focus':focus,'subject':terms,
            'employer':goal.get('company'),'role':goal.get('role'),
            'passages':[{'ref':ref,'source':host(source.url),'title':source.title,'text':text} for ref,(source,text) in enumerate(passages)]}

def scoped_question_findings(focus,sources,passages,scopes,goal,*,terms=None):
    """Split exact passages into verified job facts and unverified candidates using the scope model's labels.

    Only verified passages may be saved; candidates may inform an answer but are never stored.
    """
    verified=[];candidates=[]
    for ref,(source,text) in enumerate(passages):
        verdict=verify(source.url,source.title,text,goal,scope=scopes[ref],terms=terms,published=source.published_date)
        if verdict.verified:
            if sum(source.source_id in f.source_ids for f in verified)<PASSAGES_PER_SOURCE and len(verified)<MAX_QUESTION_FINDINGS:
                verified.append(passage_finding(focus,text,source,verified=True,official=verdict.official))
            continue
        if sum(source.source_id in f.source_ids for f in candidates)>=PASSAGES_PER_SOURCE or len(candidates)>=MAX_QUESTION_FINDINGS:continue
        candidates.append(passage_finding(focus,text,source,scope='related_location' if verdict.foreign else 'general'))
    def used(findings):
        ids={sid for finding in findings for sid in finding.source_ids}
        return [source for source in sources if source.source_id in ids]
    return verified,used(verified),candidates,used(candidates)

def trusted_fact(fact):
    """JD-sourced details and deterministically verified findings are job facts."""
    return fact.get('kind')=='job_details' or (fact.get('data') or {}).get('scope')=='exact'

def cited_money(reply,references,facts):
    """Every monetary figure in an answer must occur, with the same currency marker, in the facts it cites."""
    claimed=money_figures(reply)
    if not claimed:
        return True
    supported=set()
    for fact in facts:
        if fact['ref'] in references:
            for key in ('value','description'):
                supported|=money_figures(str(fact['data'].get(key) or ''))
    return claimed<=supported

def factual_reply(facts,links):
    """Concise, model-free answer from trusted saved facts with source links."""
    points=[]
    for fact in [f for f in facts if trusted_fact(f)][:3]:
        data=fact['data'];value=data.get('value') or data.get('location') or data.get('description')
        if not value:continue
        sources={s['source_id']:s['url'] for s in links.get(fact['ref'],[]) if s.get('url')}
        citations=source_links(sources,sources)
        label='From the saved job description' if fact.get('kind')=='job_details' and not citations else ''
        point=summary_text(str(value))+(' '+citations if citations else '')+(f' ({label})' if label else '')
        points.append(point)
    if not points:return None
    return points[0] if len(points)==1 else '\n'.join('- '+point for point in points)

def excerpt_facts(findings,sources):
    links={};facts=[]
    for index,finding in enumerate(findings):
        ref=f'web{index}'
        linked=[s for s in sources if s.source_id in finding.source_ids]
        data=finding.model_dump(exclude={'quotes','source_ids','finding_id','last_verified_at','round_number','round_name','conflict_group'})
        data['source']=', '.join(dict.fromkeys(host(s.url) for s in linked))
        titles=list(dict.fromkeys(s.title for s in linked if s.title))
        if titles:data['source_titles']=titles
        data['verified']=finding.scope=='exact'
        facts.append({'ref':ref,'kind':'opportunity_finding','data':data})
        links[ref]=[s.model_dump(mode='json') for s in linked]
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
        if len('\n\n'.join([*points,point]))>MAX_SAVED_REPLY_CHARS:
            partial=True;break
        points.append(point)
    if len(points)==1:return None
    if partial:points.append('**Coverage:** Additional saved details are available in the research view.')
    return '\n\n'.join(points)
