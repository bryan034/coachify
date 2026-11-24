"""Bounded facts for scoped career Q&A."""
import re
from app.domain.review import ALIASES

MAX_LISTED_FINDINGS = 12

REFUSAL='I can help with this career goal, its job requirements and interview preparation. I cannot carry out unrelated tasks here.'
MISSING='That information was not found in the saved JD interpretation or the completed interview research. You can ask about the recorded role, skills, requirements or interview findings.'
TOKENS=re.compile(r'[a-z0-9+#]+')
STOP={'what','which','how','are','the','a','an','is','in','for','to','of','and','do','does','this','that','it','i','my','me','about','please','explain','required','requirements','skills','skill','job','role','interview','interviews','need','needs'}

def words(text):return set(TOKENS.findall(text.casefold()))-STOP

def select_items(items,terms,limit=12):
    meaningful=set().union(*(words(t) for t in terms)) if terms else set()
    if meaningful:
        alias_ids={identifier for (_,name),identifier in ALIASES.items() if name in {t.casefold().strip() for t in terms}}
        selected=[v for v in items if meaningful & words(' '.join(str(v.get(k) or '') for k in ('name','description','category','assessment_type','interview_stage')))
            or v.get('skill_id') in alias_ids]
        groups={v['group_id'] for v in selected if v.get('group_id')}
        selected=[v for v in items if v in selected or (v.get('group_id') and v['group_id'] in groups)]
    else:selected=items
    return selected[:limit],len(selected)>limit


def opportunity_findings(research):
    if 'opportunity_findings' in research:return research['opportunity_findings']
    return [{**finding,'category':category} for category,result in (research.get('intelligence') or {}).get('categories',{}).items() for finding in result.get('findings',[])]


def facts_for(route,goal,research,include_evidence=False):
    facts=[];links={};truncated=False
    def add(kind,data,source_ids=()):
        if not data:return
        ref=f'f{len(facts)+1}';facts.append({'ref':ref,'kind':kind,'data':data})
        links[ref]=[s for s in research.get('sources',[]) if s.get('source_id') in source_ids]
    topic=route.topic
    if topic in ('role','overview'):
        keys=('role','company','field','location','seniority_level','summary','responsibilities')
        add('job_details',{k:goal[k] for k in keys if goal.get(k)})
    if topic in ('skills','preparation','overview'):
        items,cut=select_items(goal.get('skills',[]),route.terms,4 if include_evidence else 12);truncated|=cut
        for v in items:add('jd_skill',{k:v[k] for k in ('name','category','priority','origin','group_id','group_operator','required_proficiency','required_experience_months','context',*(['evidence','priority_evidence'] if include_evidence else [])) if v.get(k) is not None})
    if topic in ('requirements','overview'):
        items,cut=select_items(goal.get('non_skill_requirements',[]),route.terms);truncated|=cut
        for v in items:add('jd_requirement',{k:v[k] for k in ('category','description','priority','group_id','group_operator','minimum_months','maximum_months','completion_status') if v.get(k) is not None})
    if topic in ('interview_skills','preparation','overview'):
        items,cut=select_items(research.get('skills',[]),route.terms,4 if include_evidence else 12);truncated|=cut
        for v in items:
            data={k:v[k] for k in ('name','category','interview_stage','assessment_type','difficulty','question_patterns','evidence_origin') if v.get(k) is not None}
            if include_evidence:
                if v.get('evidence_origin')=='brave_summary':
                    quotes=[c['text'] for summary in research.get('summaries',[]) if summary.get('summary_id')==v.get('summary_id') for c in summary.get('claims',[]) if set(v.get('source_ids',[]))<=set(c.get('source_ids',[]))]
                else:quotes=[s['evidence'] for s in research.get('sources',[]) if s.get('source_id') in v.get('source_ids',[]) and s.get('evidence')]
                data['supporting_evidence']=quotes[:2]
            add('interview_finding',data,v.get('source_ids',[]))
    if topic in ('interview_process','overview'):
        process=research.get('process') or {}
        if process.get('round_count') is not None:
            add('interview_round_count',{'round_count':process['round_count']},(process.get('round_count_evidence') or {}).get('source_ids',[]))
        for v in process.get('stages',[]):add('interview_stage',{k:v[k] for k in ('name','assessment_type') if v.get(k)},v.get('evidence',{}).get('source_ids',[]))
        if not process.get('stages'):
            seen=set()
            for v in research.get('skills',[]):
                stage=v.get('interview_stage')
                if stage and stage not in seen:
                    seen.add(stage);add('interview_stage',{'name':stage,'assessment_type':v.get('assessment_type')},v.get('source_ids',[]))
    if topic in ('opportunity','overview'):
        items=opportunity_findings(research)
        if route.terms:
            wanted=set().union(*(words(term) for term in route.terms))
            items=[item for item in items if wanted & words(str(item.get('field',''))+' '+str(item.get('value','')))]
        truncated|=len(items)>MAX_LISTED_FINDINGS
        for item in items[:MAX_LISTED_FINDINGS]:
            data={key:item[key] for key in ('field','value','category','confidence','scope','evidence_type') if key in item}
            if include_evidence:data['supporting_evidence']=item.get('quotes',[])[:3]
            add('opportunity_finding',data,item.get('source_ids',[]))
    return facts,links,truncated
