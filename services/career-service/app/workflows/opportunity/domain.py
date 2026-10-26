"""Deterministic boundaries for public context, citations and compatibility findings."""
import re
import ipaddress
from urllib.parse import urlsplit,urlunsplit
from datetime import timedelta
from app.schemas.analysis import ResearchContext,InterviewSkill,InterviewProcess,InterviewStage,InterviewEvidence
from app.schemas.opportunity import Finding,FIELDS,CATEGORIES
from app.repositories.goals import fingerprint,now
from app.ai.adapter import AIError


def public_job_url(value):
    if not value:return None
    parsed=urlsplit(value);host=(parsed.hostname or '').casefold()
    if host=='localhost' or host.endswith(('.local','.localhost','.internal')) or parsed.username or parsed.password:return None
    try:
        if not ipaddress.ip_address(host).is_global:return None
    except ValueError:pass
    # The public research context never needs tracking/access parameters or fragments.
    return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))


def public_opportunity(goal):
    # Employment is unknown unless explicitly present in saved role/conditions.
    text=' '.join([goal.role,*[v.description for v in goal.non_skill_requirements]])
    employment=getattr(goal,'employment_type','unknown')
    employment=employment if employment!='unknown' else next((value for pattern,value in [(r'\bintern(?:ship)?\b','internship'),(r'\bfull[ -]time\b','full_time'),(r'\bpart[ -]time\b','part_time'),(r'\bcontract\b','contract')] if re.search(pattern,text,re.I)),'unknown')
    context={'company':goal.company,'role':goal.role,'field':goal.field,'location':goal.location,'seniority_level':goal.seniority_level,
             'employment_type':employment,'job_url':public_job_url(goal.job_url),
             'skill_hints':sorted({s.name for s in goal.skills if s.origin!='user_declaration'})[:8]}
    # Never send interests, preferences, CV, account details, raw JD or chat to shared research.
    canonical={k:' '.join(v.casefold().split()) if isinstance(v,str) else v for k,v in context.items()}
    canonical['requirements_hash']=fingerprint({'responsibilities':goal.responsibilities,'conditions':[v.model_dump(mode='json') for v in goal.non_skill_requirements]})
    digest=fingerprint(canonical)
    return context,ResearchContext(**{k:context[k] for k in ('company','role','field','location','seniority_level')},details_fingerprint=digest)


def validate_claims(output,category,sources,public=None):
    found=[];stamp=now()
    for item in output.findings:
        if item.field not in FIELDS[category] or len(item.refs)!=len(item.quotes) or len(set(item.refs))!=len(item.refs):raise AIError('invalid_output',True,reason='provenance')
        if any(i<0 or i>=len(sources) or quote not in (sources[i].evidence or '') or item.value not in quote for i,quote in zip(item.refs,item.quotes)):
            raise AIError('invalid_output',True,reason='provenance')
        values=item.model_dump(exclude={'refs'})
        if public:
            cited=' '.join((sources[i].title or '')+' '+(sources[i].evidence or '') for i in item.refs).casefold()
            company=[w for w in re.findall(r'[a-z0-9]+',(public.get('company') or '').casefold()) if len(w)>2 and w not in {'ltd','limited','inc','pte','corp','corporation','company'}]
            if item.scope=='exact' and company and not any(w in cited for w in company):values.update(scope='general',confidence='low')
            if public.get('employment_type')=='internship' and re.search(r'full[ -]time|permanent employee',cited) and not re.search(r'\bintern(?:s|ship)?\b',cited):values.update(scope='related_employment',confidence='low')
        ids=[sources[i].source_id for i in item.refs]
        if values['evidence_type']=='official' and any(sources[i].reliability!='official' and sources[i].platform!='employer' for i in item.refs):values['evidence_type']='third_party'
        if values['confidence']=='high' and any(sources[i].reliability!='official' for i in item.refs):values['confidence']='medium'
        try:record=Finding(**values,source_ids=ids,finding_id='f'+fingerprint({'category':category,'field':item.field,'value':item.value,'sources':sorted(ids)})[:16],last_verified_at=stamp)
        except ValueError:raise AIError('invalid_output',True,reason='schema_validation') from None
        if record.finding_id not in {v.finding_id for v in found}:found.append(record)
    return found


def compatibility(categories,sources=()):
    """Keep existing interview chat/read consumers working without another model call."""
    skills=[];stages=[]
    for finding in categories['interview_intelligence'].findings:
        if finding.field=='recruitment_stages':
            stages.append(InterviewStage(name=finding.value[:160],evidence=InterviewEvidence(source_ids=finding.source_ids,text=finding.value)))
        elif finding.field in ('preparation_topics','interview_questions'):
            skills.append(InterviewSkill(name=finding.value[:160],category='Interview preparation',question_patterns=[finding.value] if finding.field=='interview_questions' else [],source_ids=finding.source_ids,independent_report_count=len({s.report_group for s in sources if s.source_id in finding.source_ids and s.report_group})))
    return skills,InterviewProcess(stages=stages[:8])


def summary_input(categories):
    return [{'id':f.finding_id,'category':category,'field':f.field,'value':f.value,'confidence':f.confidence,'scope':f.scope,'conflict_group':f.conflict_group}
            for category,result in categories.items() for f in result.findings][:60]


def dedupe_findings(category,findings):
    grouped={};ranks={'insufficient_evidence':0,'low':1,'medium':2,'high':3}
    for finding in findings:
        key=(finding.field,' '.join(finding.value.casefold().split()),finding.scope,finding.conflict_group,finding.evidence_type)
        if key not in grouped:grouped[key]=finding;continue
        old=grouped[key];pairs=dict(zip(old.source_ids,old.quotes))
        pairs.update(zip(finding.source_ids,finding.quotes));pairs=dict(list(pairs.items())[:3])
        confidence=min((old.confidence,finding.confidence),key=ranks.get)
        grouped[key]=old.model_copy(update={'source_ids':list(pairs),'quotes':list(pairs.values()),'confidence':confidence,
            'finding_id':'f'+fingerprint({'category':category,'field':old.field,'value':old.value,'sources':sorted(pairs)})[:16]})
    return list(grouped.values())[:20]


def supported_claims(output,category,sources,public=None):
    """A bad citation cannot erase other independently validated findings."""
    valid=[];rejected=0
    for item in output.findings:
        try:valid.extend(validate_claims(output.model_copy(update={'findings':[item]}),category,sources,public))
        except AIError:rejected+=1
    if output.findings and not valid:raise AIError('invalid_output',True,reason='provenance')
    return valid,rejected
