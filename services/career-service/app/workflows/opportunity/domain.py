"""Deterministic boundaries for public context, citations and compatibility findings."""
import re
import ipaddress
from pydantic import ValidationError
from app.ai.recovery import issues_for
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


def whitespace(value):
    """Only whitespace is normalized: case, punctuation and numbers stay exact."""
    return ' '.join(value.split())


def citation_error(index,field,issue):
    return AIError('invalid_output',True,reason='provenance',fields=(field,),
        violations=({'field':f'findings.{index}.{field}','issue':issue},))


def numeric_support(value,evidence,index):
    """Numbers must be present verbatim in the cited source excerpts."""
    numbers=lambda text:re.findall(r'(?<![\d.,])[-+]?(?:\d+(?:[,.]\d+)*|[.,]\d+)(?:[eE][-+]?\d+)?(?:[KkMm](?!\w))?',text)
    available=set(numbers(evidence))
    if any(number not in available for number in numbers(value)):
        raise citation_error(index,'value','unsupported_number')


def validate_claims(output,category,sources,public=None):
    found=[];stamp=now()
    for index,item in enumerate(output.findings):
        if item.field not in FIELDS[category]:raise citation_error(index,'field','field_not_allowed')
        if len(item.refs)!=len(item.quotes):raise citation_error(index,'refs','quote_reference_count_mismatch')
        if len(set(item.refs))!=len(item.refs):raise citation_error(index,'refs','duplicate_source_reference')
        for ref,quote in zip(item.refs,item.quotes):
            if ref<0 or ref>=len(sources):raise citation_error(index,'refs','source_index_out_of_range')
            if whitespace(quote) not in whitespace(sources[ref].evidence or ''):
                raise citation_error(index,'quotes','quote_not_in_source')
        evidence='\n'.join(sources[ref].evidence or '' for ref in item.refs)
        numeric_support(item.value,evidence,index)
        values=item.model_dump(exclude={'refs'})
        if public:
            cited=' '.join((sources[i].title or '')+' '+(sources[i].evidence or '') for i in item.refs).casefold()
            company=[w for w in re.findall(r'[a-z0-9]+',(public.get('company') or '').casefold()) if len(w)>2 and w not in {'ltd','limited','inc','pte','corp','corporation','company'}]
            if item.scope=='exact' and company and not any(w in cited for w in company):values.update(scope='general',confidence='low')
            if public.get('employment_type')=='internship' and re.search(r'full[ -]time|permanent employee',cited) and not re.search(r'\bintern(?:s|ship)?\b',cited):values.update(scope='related_employment',confidence='low')
        if public and not public.get('company'):values.update(scope='general',confidence='low')
        ids=[sources[i].source_id for i in item.refs]
        if values['evidence_type']=='official' and any(sources[i].reliability!='official' and sources[i].platform!='employer' for i in item.refs):values['evidence_type']='third_party'
        if values['confidence']=='high' and any(sources[i].reliability!='official' for i in item.refs):values['confidence']='medium'
        try:record=Finding(**values,source_ids=ids,finding_id='f'+fingerprint({'category':category,'field':item.field,'value':item.value,'sources':sorted(ids)})[:16],last_verified_at=stamp)
        except ValidationError as error:
            issues=issues_for(error,Finding)
            raise AIError('invalid_output',True,reason='schema_validation',
                fields=tuple(dict.fromkeys(v['field'].split('.')[0] for v in issues)),
                violations=[{'field':f'findings.{index}.'+v['field'],'issue':v['issue']} for v in issues]) from None
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
    # Interleave categories so the bounded summary cannot lose later categories
    # when interview/internship evidence fills the first sixty slots.
    return [{'id':f.finding_id,'category':category,'field':f.field,'value':f.value,'confidence':f.confidence,'scope':f.scope,'conflict_group':f.conflict_group}
            for index in range(max((len(result.findings) for result in categories.values()),default=0))
            for category,result in categories.items() if index<len(result.findings)
            for f in [result.findings[index]]][:60]


def dedupe_findings(category,findings):
    """Merge repeated identities before comparing presentation wording.

    Keep the first identity stable when citations grow, so later occurrences of
    the same extract cannot reappear under an ID discarded during an earlier merge.
    """
    ranks={'insufficient_evidence':0,'low':1,'medium':2,'high':3}
    def combine(old,finding):
        pairs=dict(zip(old.source_ids,old.quotes))
        for source,quote in zip(finding.source_ids,finding.quotes):pairs.setdefault(source,quote)
        pairs=dict(list(pairs.items())[:3])
        return old.model_copy(update={'source_ids':list(pairs),'quotes':list(pairs.values()),
            'confidence':min((old.confidence,finding.confidence),key=ranks.get)})
    identities={}
    for finding in findings:
        previous=identities.get(finding.finding_id)
        identities[finding.finding_id]=combine(previous,finding) if previous else finding
    grouped={}
    for finding in identities.values():
        key=(finding.field,' '.join(finding.value.casefold().split()),finding.scope,finding.conflict_group,finding.evidence_type)
        grouped[key]=combine(grouped[key],finding) if key in grouped else finding
    return list(grouped.values())[:20]


def supported_claims(output,category,sources,public=None):
    """A bad citation cannot erase other independently validated findings."""
    valid=[];rejected=0;issues=[];reasons=[]
    for index,item in enumerate(output.findings):
        try:valid.extend(validate_claims(output.model_copy(update={'findings':[item]}),category,sources,public))
        except AIError as error:
            rejected+=1;reasons.append(error.reason)
            issues.extend({**v,'field':v['field'].replace('findings.0.',f'findings.{index}.',1)} for v in error.violations)
    if output.findings and not valid:
        raise AIError('invalid_output',True,reason=reasons[0] if len(set(reasons))==1 else 'provenance',fields=('findings',),violations=issues)
    return valid,rejected
