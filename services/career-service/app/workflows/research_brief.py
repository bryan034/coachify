"""Version 2 research briefs: the model condenses the goal and saved research into short structured, cited data."""
import json
import logging
import re
from urllib.parse import urlsplit
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import Operation
from app.ai.contracts import AIInput
from app.ai.errors import AIError
from app.ai.recovery import validation_feedback
from app.ai.routing import chat_models
from app.repositories.goals import now
from app.schemas.opportunity import FIELDS,plain_text
from app.schemas.research_brief import FORMAT,WORD_LIMITS,InterviewBrief,RoleBrief
from app.workflows.structured import structured_node

CATEGORIES={'role':('internship_insights','career_progression','conversion_outcomes','company_intelligence'),
            'interview':('interview_intelligence',)}
STAGES={'role':'role_brief','interview':'interview_brief'}
MAX_SOURCES=40
FILLER=re.compile(r"\b(?:it(?: is|'s) worth noting(?: that)?|please note(?: that)?|it should be noted(?: that)?|"
    r"some details may[^.;]*[.;]?|details may be inaccurate[^.;]*[.;]?|in summary,?|overall,)\s*",re.I)
DANGLING={'and','or','but','with','to','of','the','a','an','for','in','on','at','by','from','as','than','that','which','who','while','via','about','into','per','including','like','such'}
SUFFIXES={'com','sg','org','net','gov','edu','co','io','test','uk','au'}
SITES={'glassdoor':'Glassdoor','reddit':'Reddit'}
log=logging.getLogger('uvicorn.error.ai_usage')


def findings_for(record,tab):
    categories=record.intelligence.categories if record and getattr(record,'intelligence',None) else {}
    return [f for category in CATEGORIES[tab] if (result:=categories.get(category)) for f in result.findings]


def site_name(url,platform=None):
    if platform in SITES:return SITES[platform]
    labels=(urlsplit(url).hostname or '').split('.')
    while len(labels)>1 and labels[-1] in SUFFIXES:labels.pop()
    name=labels[-1]
    return name[:1].upper()+name[1:] if name else 'Source'


def catalogue(goal,record,tab):
    """Source keys S1..Sk for this request: the job description first, then every research page the tab's findings cite."""
    entries=[]
    by_url={}
    def add(url,title,site):
        if not url or url in by_url or len(entries)>=MAX_SOURCES:return by_url.get(url)
        key=f'S{len(entries)+1}'
        by_url[url]=key
        entries.append({'key':key,'url':str(url),'title':title,'site':site})
        return key
    job=str(goal.job_url) if getattr(goal,'job_url',None) else None
    if job:add(job,f'{goal.role} job description' if goal.role else 'Job description',site_name(job))
    for requirement in goal.non_skill_requirements or []:
        for url in getattr(requirement,'source_urls',None) or []:add(str(url),'Job requirements',site_name(str(url)))
    pages={s.source_id:s for s in (getattr(record,'sources',None) or [])}
    findings=[]
    for f in findings_for(record,tab):
        keys=[add(str(pages[i].url),pages[i].title,site_name(str(pages[i].url),pages[i].platform)) for i in f.source_ids if i in pages]
        findings.append({'topic':f.field,'text':plain_text(f.value),'evidence':f.evidence_type,'sources':[k for k in keys if k],
            'conflicting':bool(f.conflict_group),**({'round':f.round_number,'round_name':f.round_name} if f.round_number else {})})
    return entries,findings


def context_for(goal,record,tab):
    entries,findings=catalogue(goal,record,tab)
    job=entries[0]['key'] if entries and getattr(goal,'job_url',None) else None
    covered={f['topic'] for f in findings}
    uncovered=sorted({field for c in CATEGORIES[tab] for field in FIELDS[c]}-covered)
    return {'goal':{'role':goal.role,'company':goal.company,'field':goal.field,'location':goal.location,
                    'employment_type':goal.employment_type,'seniority_level':goal.seniority_level,
                    'summary':goal.summary,'responsibilities':list(goal.responsibilities or [])[:20],
                    'requirements':[str(r.description) for r in (goal.non_skill_requirements or [])][:20],
                    'job_description_source':job},
            'sources':[{'key':e['key'],'title':e['title'],'site':e['site']} for e in entries],
            'findings':findings,'uncovered_topics':uncovered},entries


def word_count(text):return len((text or '').split())


def truncate(text,limit):
    """Cut at a word boundary, dropping dangling joiners and trailing punctuation; keep the closing mark."""
    parts=text.split()
    if len(parts)<=limit:return text
    end=text.rstrip()[-1:] if text.rstrip()[-1:] in '.?!' else ''
    cut=parts[:limit]
    while len(cut)>1 and cut[-1].lower().strip(',;:–-') in DANGLING:cut.pop()
    return ' '.join(cut).rstrip(',;:–-—( ')+end


def strip_filler(text):
    cleaned=FILLER.sub('',text).strip()
    if cleaned==text or not cleaned:return text
    return cleaned[:1].upper()+cleaned[1:]


def slots(output,tab):
    """Every text field with its word limit, as (path, limit name, read, write)."""
    def attr(obj,name,path,limit):
        return (path,limit,lambda:getattr(obj,name),lambda v:setattr(obj,name,v))
    def item(values,index,path,limit):
        return (path,limit,lambda:values[index],lambda v:values.__setitem__(index,v))
    found=[attr(output,'summary','summary','summary' if tab=='role' else 'interview.summary')]
    found+=[item(output.not_found,i,f'not_found.{i}','not_found') for i in range(len(output.not_found))]
    for i,label in enumerate(output.sources):
        found+=[attr(label,'title',f'sources.{i}.title','source.title'),attr(label,'domain',f'sources.{i}.domain','source.domain')]
    if tab=='role':
        for i,fact in enumerate(output.facts):
            found+=[attr(fact,n,f'facts.{i}.{n}',f'fact.{n}') for n in ('label','value','note') if getattr(fact,n)]
        found+=[item(output.duties,i,f'duties.{i}','duty') for i in range(len(output.duties))]
        for i,topic in enumerate(output.topics):
            found+=[attr(topic,'title',f'topics.{i}.title','topic.title'),attr(topic,'takeaway',f'topics.{i}.takeaway','topic.takeaway')]
            found+=[attr(r,'text',f'topics.{i}.reports.{j}.text','report') for j,r in enumerate(topic.reports)]
        for i,pay in enumerate(output.pay):
            found+=[attr(pay,n,f'pay.{i}.{n}',f'pay.{n}') for n in ('label','value','caveat') if getattr(pay,n)]
        return found
    for i,step in enumerate(output.process):
        found+=[attr(step,n,f'process.{i}.{n}',f'process.{n}') for n in ('title','when','detail') if getattr(step,n)]
    found.append(attr(output.difficulty,'reason','difficulty.reason','difficulty.reason'))
    for i,q in enumerate(output.questions):
        found+=[attr(q,'question',f'questions.{i}.question','question'),attr(q,'prep',f'questions.{i}.prep','prep')]
    reports=output.candidate_reports
    found+=[attr(a,'label',f'candidate_reports.asked_about.{i}.label','asked_about') for i,a in enumerate(reports.asked_about)]
    for name in ('situational','tone'):
        if getattr(reports,name):found.append(attr(getattr(reports,name),'text',f'candidate_reports.{name}.text',name))
    found+=[attr(r,'text',f'candidate_reports.reports.{j}.text','report') for j,r in enumerate(reports.reports)]
    return found


def shared_run(a,b,size=5):
    """True when a takeaway repeats a run of consecutive report words (the whole report when it is shorter)."""
    words=lambda t:re.findall(r"[\w$%/'-]+(?:[.,]\d+)*",t.lower())
    first,second=words(a),words(b)
    size=max(4,min(size,len(second)))
    runs={tuple(first[i:i+size]) for i in range(len(first)-size+1)}
    return any(tuple(second[i:i+size]) in runs for i in range(len(second)-size+1))


def style_violations(output,tab):
    """Word limits, hedging filler and takeaways that copy report wording: retried once, then repaired."""
    found=[]
    for path,limit,read,_ in slots(output,tab):
        text=read()
        if word_count(text)>WORD_LIMITS[limit]:found.append({'field':path,'issue':f'over_{WORD_LIMITS[limit]}_words'})
        elif FILLER.search(text):found.append({'field':path,'issue':'hedging_filler'})
    if tab=='role':
        for i,topic in enumerate(output.topics):
            if any(shared_run(topic.takeaway,r.text) for r in topic.reports):found.append({'field':f'topics.{i}.takeaway','issue':'repeats_report_wording'})
    return found


def repair(output,tab):
    for _,limit,read,write in slots(output,tab):
        write(truncate(strip_filler(read()),WORD_LIMITS[limit]))


def cited_lists(output,tab):
    """Every citation list in reading order, which is the order sources are numbered in."""
    if tab=='role':
        return [f.citations for f in output.facts]+[r.citations for t in output.topics for r in t.reports]+[p.citations for p in output.pay]
    reports=output.candidate_reports
    return ([s.citations for s in output.process]+[a.citations for a in reports.asked_about]
            +[c.citations for c in (reports.situational,reports.tone) if c]+[r.citations for r in reports.reports])


def validator(tab,entries):
    keys={e['key'] for e in entries}
    def fail(field,issue):
        return AIError('invalid_output',True,reason='provenance',fields=(field.split('.')[0],),violations=({'field':field,'issue':issue},))
    def validate(output):
        for index,citations in enumerate(cited_lists(output,tab)):
            if set(citations)-keys:raise fail(f'citations.{index}','unknown_source')
        for index,label in enumerate(output.sources):
            if label.key not in keys:raise fail(f'sources.{index}.key','unknown_source')
        if tab=='role':
            ids=[t.id for t in output.topics]
            if len(ids)!=len(set(ids)):raise fail('topics','repeated_topic')
            labels=[f.label.casefold() for f in output.facts]
            if len(labels)!=len(set(labels)):raise fail('facts','repeated_fact')
    return validate


def dedupe(values):
    seen=set();kept=[]
    for value in values:
        if value.casefold() not in seen:
            seen.add(value.casefold());kept.append(value)
    return kept


def publish(output,tab,entries,researched_at):
    """Number sources 1..N in first-cited reading order and resolve every citation to that number."""
    numbers={}
    def cite(keys):
        for key in dict.fromkeys(keys):numbers.setdefault(key,len(numbers)+1)
        return sorted({numbers[k] for k in keys})
    by_key={e['key']:e for e in entries}
    labels={label.key:label for label in output.sources}
    base={'researched_at':researched_at,'summary':output.summary,'not_found':dedupe(output.not_found)}
    if tab=='role':
        facts=[{'label':f.label,'value':f.value,'note':f.note,'citations':cite(f.citations)} for f in output.facts]
        topics=[]
        for t in output.topics:
            reports=[{'text':r.text,'citations':cite(r.citations)} for r in t.reports]
            topics.append({'id':t.id,'title':t.title,'tone':t.tone,'takeaway':t.takeaway,'estimated':t.estimated or not reports,
                           'conflicting':t.conflicting,'reports':reports})
        pay=[{'label':p.label,'value':p.value,'caveat':p.caveat,'citations':cite(p.citations)} for p in output.pay]
        body={**base,'facts':facts,'duties':dedupe(output.duties),'topics':topics,'pay':pay}
    else:
        process=[{'step':i+1,'title':s.title,'when':s.when,'detail':s.detail,'citations':cite(s.citations)} for i,s in enumerate(output.process)]
        reports=output.candidate_reports
        seen=set();asked=[]
        for a in reports.asked_about:
            if a.label.casefold() in seen:continue
            seen.add(a.label.casefold());asked.append({'label':a.label,'citations':cite(a.citations)})
        candidate={'asked_about':asked,
            'situational':{'text':reports.situational.text,'citations':cite(reports.situational.citations)} if reports.situational else None,
            'tone':{'text':reports.tone.text,'citations':cite(reports.tone.citations)} if reports.tone else None,
            'reports':[{'text':r.text,'citations':cite(r.citations)} for r in reports.reports]}
        body={**base,'process':process,'difficulty':output.difficulty.model_dump(),
              'questions':[q.model_dump() for q in output.questions],'candidate_reports':candidate}
    sources=[]
    for key,index in sorted(numbers.items(),key=lambda pair:pair[1]):
        entry,label=by_key[key],labels.get(key)
        title=label.title if label else truncate(re.split(r'\s+[|–—-]\s+',entry['title'] or entry['site'])[0],WORD_LIMITS['source.title'])
        sources.append({'index':index,'title':title,'domain':label.domain if label else entry['site'],'url':entry['url']})
    model=RoleBrief if tab=='role' else InterviewBrief
    return model.model_validate({**body,'sources':sources,'source_count':len(sources)})


def researched_at(record,tab):
    categories=record.intelligence.categories if record and getattr(record,'intelligence',None) else {}
    stamps=[r.researched_at for c in CATEGORIES[tab] if (r:=categories.get(c)) and r.researched_at]
    return max(stamps) if stamps else getattr(record,'updated_at',None) or now()


def collection(request):
    return request.app.state.goal_store.goals.database['research_briefs']


def key_for(account,goal,tab):return f'{account}:{goal.id}:{tab}'


def research_key(record):return getattr(record,'id',None)


async def read_saved(request,account,goal,record,tab):
    row=await thread(collection(request).find_one,{'_id':key_for(account,goal,tab)})
    if not row or row.get('format')!=FORMAT or row.get('goal_version')!=goal.version or row.get('research_id')!=research_key(record):return None
    return (RoleBrief if tab=='role' else InterviewBrief).model_validate(row['brief'])


async def generate(request,account,goal,record,tab):
    context,entries=context_for(goal,record,tab)
    encoded=json.dumps(jsonable_encoder(context),separators=(',',':'),ensure_ascii=False)
    revision=f'{goal.id}:{goal.version}'
    stage=STAGES[tab]
    async def current():
        state=await thread(request.app.state.goal_store.current,account)
        saved=state['goal']
        if not saved or saved.id!=goal.id or saved.version!=goal.version:raise AIError('stale_input',True)
        return revision
    validate=validator(tab,entries)
    @structured_node
    async def present(state):
        token=validation_feedback.set(state['feedback']) if state.get('feedback') and validation_feedback.get() is None else None
        try:
            result=await chat_models(request.app.state).generate(AIInput(stage=stage,context=encoded),
                Operation(account,revision,stage),current_revision=current,validate_output=validate)
        finally:
            if token is not None:validation_feedback.reset(token)
        validate(result.data)
        return result.data
    output=await present({})
    issues=style_violations(output,tab)
    if issues:
        log.info('brief_style_retry stage=%s issues=%s',stage,len(issues))
        output=await present({'feedback':{'reason':'word_limit','fields':sorted({i['field'].split('.')[0] for i in issues}),'violations':issues[:12]}})
        if style_violations(output,tab):repair(output,tab)
    brief=publish(output,tab,entries,researched_at(record,tab))
    await thread(collection(request).replace_one,{'_id':key_for(account,goal,tab)},
        {'_id':key_for(account,goal,tab),'format':FORMAT,'goal_version':goal.version,'research_id':research_key(record),
         'brief':jsonable_encoder(brief,by_alias=False)},True)
    return brief
