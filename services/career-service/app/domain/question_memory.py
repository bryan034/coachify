"""Saved-first public question selection and exact-excerpt presentation."""
import re
from app.ai.context_contracts import ContextPlan
from app.domain.questions import blocked_task,opportunity_findings
from app.domain.source_scope import FOREIGN_CURRENCY,TOPIC,foreign_source,foreign_text,target_place,verify
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
    from app.workflows.opportunity.sources import pool
    return pool(sources)

def exact_question_findings(focus,facts,links,*,require_focus=True):
    """Keep only topical verbatim source passages; generated answers are never stored."""
    sources=link_sources(links)
    findings=[]
    for passage in evidence_passages(sources):
        text=passage['text'];source=sources[passage['source_ref']]
        if require_focus and not re.search(FOCUS_WORDS[focus],text,re.I):continue
        if sum(source.source_id in f.source_ids for f in findings)>=2:continue
        findings.append(passage_finding(focus,text,source))
        if len(findings)==6:break
    used={sid for finding in findings for sid in finding.source_ids}
    return findings,[source for source in sources if source.source_id in used]

def scoped_question_findings(focus,links,goal,*,terms=None,require_focus=True):
    """Split exact passages into verified job facts and unverified candidates.

    Only verified passages may be saved; candidates may inform an answer but are never stored.
    """
    sources=link_sources(links)
    verified=[];candidates=[]
    for passage in evidence_passages(sources):
        text=passage['text'];source=sources[passage['source_ref']]
        verdict=verify(focus,source.url,source.title,text,goal,terms=terms,published=source.published_date)
        if verdict.verified:
            if sum(source.source_id in f.source_ids for f in verified)<2 and len(verified)<6:
                verified.append(passage_finding(focus,text,source,verified=True,official=verdict.official))
            continue
        if require_focus:
            source_text=f'{source.title or ""} {text}'
            topical=re.search(FOCUS_WORDS[focus],source_text,re.I)
            if focus=='compensation':
                topical=topical or re.search(TOPIC[focus],source_text,re.I) or FOREIGN_CURRENCY.search(text)
            if not topical:continue
        if sum(source.source_id in f.source_ids for f in candidates)>=2 or len(candidates)>=6:continue
        candidates.append(passage_finding(focus,text,source,scope='related_location' if verdict.foreign else 'general'))
    def used(findings):
        ids={sid for finding in findings for sid in finding.source_ids}
        return [source for source in sources if source.source_id in ids]
    return verified,used(verified),candidates,used(candidates)

def trusted_fact(fact):
    """JD-sourced details and deterministically verified findings are job facts."""
    return fact.get('kind')=='job_details' or (fact.get('data') or {}).get('scope')=='exact'

def market_scoped(fact,goal,sources=()):
    """Saved findings about another market stay usable as labelled context, never as job facts."""
    if fact.get('kind')=='job_details':
        return fact
    data=fact.get('data') or {}
    text=' '.join(str(v) for v in data.values())
    if foreign_text(text,target_place(goal)) or any(
            foreign_source(source.get('url'),source.get('title'),'',goal) for source in sources):
        return {**fact,'data':{**data,'scope':'related_location'}}
    return fact

def cited_foreign_currency(reply,references,facts):
    """Foreign monetary figures must occur in the facts cited by the answer."""
    amount=r'\d+(?:[,.]\d+)*(?:[kKmM]\b)?'
    def figures(text):
        values=set()
        for match in FOREIGN_CURRENCY.finditer(text):
            after=re.match(r'\s*('+amount+')',text[match.end():])
            before=re.search(r'('+amount+r')\s*$',text[:match.start()]) if not after else None
            number=after or before
            values.add((match[0].casefold(),re.sub(r'(?<=\d),(?=\d{3}(?:[,.km]|$))','',number[1].casefold()) if number else None))
        return values
    claimed=figures(reply)
    if not claimed:
        return True
    supported=set()
    for fact in facts:
        if fact['ref'] in references:
            for key in ('value','description'):
                supported.update(figures(str(fact['data'].get(key) or '')))
    return all((currency,amount) in supported if amount else any(code==currency for code,_ in supported)
               for currency,amount in claimed)

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
        from app.domain.source_scope import host
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
        if len('\n\n'.join([*points,point]))>3700:
            partial=True;break
        points.append(point)
    if len(points)==1:return None
    if partial:points.append('**Coverage:** Additional saved details are available in the research view.')
    return '\n\n'.join(points)
