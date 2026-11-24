"""Deterministic boundaries for public context, citations and interview projections."""
import re
import ipaddress
from pydantic import ValidationError
from app.ai.recovery import issues_for
from urllib.parse import urlsplit,urlunsplit
from app.schemas.analysis import ResearchContext,InterviewSkill,InterviewProcess,InterviewStage,InterviewEvidence
from app.schemas.opportunity import Finding,plain_text
from app.repositories.goals import fingerprint,now
from app.ai.errors import AIError
from app.ai.opportunity_contracts import SkillLevels
from .topics import TOPICS
from types import SimpleNamespace
from app.domain.competence import reference

MIN_ANNUAL_AMOUNT = 1000
MIN_COMPANY_WORD = 3


def public_job_url(value):
    if not value:return None
    parsed=urlsplit(value);host=(parsed.hostname or '').casefold()
    if host=='localhost' or host.endswith(('.local','.localhost','.internal')) or parsed.username or parsed.password:return None
    try:
        if not ipaddress.ip_address(host).is_global:return None
    except ValueError:pass
    return urlunsplit((parsed.scheme,parsed.netloc,parsed.path,'',''))


def public_opportunity(goal):
    text=' '.join([goal.role,*[v.description for v in goal.non_skill_requirements]])
    employment=getattr(goal,'employment_type','unknown')
    employment=employment if employment!='unknown' else next((value for pattern,value in [(r'\bintern(?:ship)?\b','internship'),(r'\bfull[ -]time\b','full_time'),(r'\bpart[ -]time\b','part_time'),(r'\bcontract\b','contract')] if re.search(pattern,text,re.I)),'unknown')
    context={'company':goal.company,'role':goal.role,'field':goal.field,'location':goal.location,'seniority_level':goal.seniority_level,
             'employment_type':employment,'job_url':public_job_url(goal.job_url),
             'skill_hints':sorted({s.name for s in goal.skills if s.origin!='user_declaration'})[:60]}
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


NUMBER=re.compile(r'(?<![\d.,])[-+]?(?:\d+(?:[,.]\d+)*|[.,]\d+)(?:[eE][-+]?\d+)?(?:\s?[KkMm](?!\w))?')


def number_value(token):
    """8k, 8K, 8,000 and 8000 are one amount; years and other plain numbers keep their value."""
    token=token.replace(' ','');scale={'k':1_000,'m':1_000_000}.get(token[-1:].lower(),1)
    digits=token[:-1] if scale>1 else token
    digits=re.sub(r',(?=\d{3}(?!\d))','',digits).replace(',','.')
    try:return round(float(digits)*scale,2)
    except ValueError:return None


def numeric_support(value,evidence,index):
    """Every number shown in digits must come from the cited passage's digits, written in any common format.

    The one derived number allowed is a monthly amount computed from an annual figure in the passage,
    and only when that annual figure is also shown in the value.
    """
    available={number_value(n) for n in NUMBER.findall(evidence)}-{None}
    shown=[number_value(n) for n in NUMBER.findall(plain_text(value))]
    stated={n for n in shown if n in available}
    for number in shown:
        if number in stated:continue
        if number is not None and any(abs(annual/12-number)<=max(1,annual/12*.01) for annual in stated if annual>=MIN_ANNUAL_AMOUNT):continue
        raise citation_error(index,'value','unsupported_number')


def validate_claims(output,category,sources,public=None):
    found=[];stamp=now()
    for index,item in enumerate(output.findings):
        if item.field not in TOPICS:raise citation_error(index,'field','field_not_allowed')
        if len(item.refs)!=len(item.quotes):raise citation_error(index,'refs','quote_reference_count_mismatch')
        if len(set(item.refs))!=len(item.refs):raise citation_error(index,'refs','duplicate_source_reference')
        for ref,quote in zip(item.refs,item.quotes):
            if ref<0 or ref>=len(sources):raise citation_error(index,'refs','source_index_out_of_range')
            if whitespace(quote) not in whitespace(sources[ref].evidence or ''):
                raise citation_error(index,'quotes','quote_not_in_source')
        evidence='\n'.join(item.quotes if output._passage_bound else [sources[ref].evidence or '' for ref in item.refs])
        numeric_support(item.value,evidence,index)
        values=item.model_dump(exclude={'refs'})
        if public:
            cited=' '.join((sources[i].title or '')+' '+(sources[i].evidence or '') for i in item.refs).casefold()
            company=[w for w in re.findall(r'[a-z0-9]+',(public.get('company') or '').casefold()) if len(w)>=MIN_COMPANY_WORD and w not in {'ltd','limited','inc','pte','corp','corporation','company'}]
            if item.scope=='exact' and company and not any(w in cited for w in company):values.update(scope='general',confidence='low')
            if public.get('employment_type')=='internship' and re.search(r'full[ -]time|permanent employee',cited) and not re.search(r'\bintern(?:s|ship)?\b',cited):values.update(scope='related_employment',confidence='low')
        if public and not public.get('company'):values.update(scope='general',confidence='low')
        ids=[sources[i].source_id for i in item.refs]
        if values['evidence_type']=='official' and any(sources[i].reliability!='official' and sources[i].platform!='employer' for i in item.refs):values['evidence_type']='third_party'
        if values['confidence']=='high' and any(sources[i].reliability!='official' for i in item.refs):values['confidence']='medium'
        try:record=Finding(**values,source_ids=ids,finding_id='f'+fingerprint({'category':category,'field':item.field,'value':plain_text(item.value),'sources':sorted(ids),**({'round':values['round_number']} if values.get('round_number') else {})})[:16],last_verified_at=stamp)
        except ValidationError as error:
            issues=issues_for(error,Finding)
            raise AIError('invalid_output',True,reason='schema_validation',
                fields=tuple(dict.fromkeys(v['field'].split('.')[0] for v in issues)),
                violations=[{'field':f'findings.{index}.'+v['field'],'issue':v['issue']} for v in issues]) from None
        if record.finding_id not in {v.finding_id for v in found}:found.append(record)
    return found


def interview_projection(categories,sources=()):
    """Interview skills and stages that questions read, taken from interview findings."""
    skills=[];stages=[]
    for finding in categories['interview_intelligence'].findings:
        if finding.field=='recruitment_stages':
            stages.append(InterviewStage(name=plain_text(finding.value)[:160],evidence=InterviewEvidence(source_ids=finding.source_ids,text=plain_text(finding.value))))
        elif finding.field in ('preparation_topics','interview_questions'):
            skills.append(InterviewSkill(name=plain_text(finding.value)[:160],category='Interview preparation',question_patterns=[plain_text(finding.value)] if finding.field=='interview_questions' else [],source_ids=finding.source_ids,independent_report_count=len({s.report_group for s in sources if s.source_id in finding.source_ids and s.report_group})))
    return skills,InterviewProcess(stages=stages[:8])


def rating_skills(goal):
    """Skill names and the employer's stated expectations for each; never the whole job text, CV or user notes."""
    return [{'name':s.name,'priority':s.priority,'stated_proficiency':s.required_proficiency,'required_experience_months':s.required_experience_months,
             'employer_context':s.context if s.origin=='employer' else None}
            for s in goal.skills if s.origin!='user_declaration'][:60]


def weighted_skills(skills,public,categories):
    """Rating input: each skill with elo's weighted reference score and the weights behind it."""
    role=SimpleNamespace(**{k:public.get(k) for k in ('role','seniority_level','employment_type','field','company')})
    rows=[]
    for s in skills:
        level,factors=reference(SimpleNamespace(name=s['name'],priority=s.get('priority'),required_experience_months=s.get('required_experience_months')),role,categories)
        rows.append({**s,'reference_level':level,'reference_factors':factors})
    return rows


def validated_skill_levels(output,skills,finding_ids):
    """One rating per requested skill, citing only this report's findings."""
    if not isinstance(output,SkillLevels):raise ValueError('Skill ratings have an unexpected shape.')
    wanted={' '.join(s['name'].casefold().split()):s['name'] for s in skills};seen={};problems=[]
    for index,rated in enumerate(output.levels):
        key=' '.join(rated.skill.casefold().split())
        if key not in wanted or key in seen:problems.append({'field':f'levels.{index}.skill','issue':'unknown_or_repeated_skill'});continue
        if any(i not in finding_ids for i in rated.finding_ids):problems.append({'field':f'levels.{index}.finding_ids','issue':'unknown_finding'});continue
        if any(e.finding_id not in finding_ids for e in rated.reported_examples):problems.append({'field':f'levels.{index}.reported_examples','issue':'unknown_finding'});continue
        seen[key]={'skill':wanted[key],'level':rated.level,
                   'employer_demand':plain_text(rated.employer_demand) if rated.employer_demand else None,
                   'reported_examples':[{'text':plain_text(e.text),'finding_id':e.finding_id} for e in rated.reported_examples],
                   'rationale':plain_text(rated.rationale),'finding_ids':list(dict.fromkeys(rated.finding_ids))}
    if problems or len(seen)!=len(wanted):
        raise AIError('invalid_output',True,reason='schema_validation',fields=('levels',),
            violations=problems or [{'field':'levels','issue':'missing_skill'}])
    return list(seen.values())


def summary_input(categories):
    return [{'id':f.finding_id,'category':category,'field':f.field,'value':plain_text(f.value),'confidence':f.confidence,'scope':f.scope,'conflict_group':f.conflict_group}
            for index in range(max((len(result.findings) for result in categories.values()),default=0))
            for category,result in categories.items() if index<len(result.findings)
            for f in [result.findings[index]]][:60]


def dedupe_findings(category,findings):
    """Merge repeated identities before comparing presentation wording; the first identity stays stable."""
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
        key=(finding.field,' '.join(plain_text(finding.value).casefold().split()),finding.scope,finding.conflict_group,finding.evidence_type)
        grouped[key]=combine(grouped[key],finding) if key in grouped else finding
    return list(grouped.values())[:20]


def supported_claims(output,category,sources,public=None):
    """A bad citation cannot erase other independently validated findings."""
    issues=list(output._reference_issues)
    valid=[];rejected=len(issues);reasons=['provenance'] if issues else []
    for index,item in enumerate(output.findings):
        original=output._reference_indexes[index] if output._reference_indexes else index
        try:valid.extend(validate_claims(output.model_copy(update={'findings':[item]}),category,sources,public))
        except AIError as error:
            rejected+=1;reasons.append(error.reason)
            issues.extend({**v,'field':v['field'].replace('findings.0.',f'findings.{original}.',1)} for v in error.violations)
    if (output.findings or issues) and not valid:
        raise AIError('invalid_output',True,reason=reasons[0] if len(set(reasons))==1 else 'provenance',fields=('findings',),violations=issues)
    return valid,rejected
