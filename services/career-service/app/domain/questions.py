"""Deterministic narrow routes and bounded facts for scoped career Q&A."""
import re
from app.ai.qa_contracts import QuestionRoute

REFUSAL='I can help with this career goal, its job requirements and interview preparation. I cannot carry out unrelated tasks here.'
MISSING='That information was not found in the saved JD interpretation or the completed interview research. You can ask about the recorded role, skills, requirements or interview findings.'
TOKENS=re.compile(r'[a-z0-9+#]+')
STOP={'what','which','how','are','the','a','an','is','in','for','to','of','and','do','does','this','that','it','i','my','me','about','please','explain','required','requirements','skills','skill','job','role','interview','interviews','need','needs'}

def words(text):return set(TOKENS.findall(text.casefold()))-STOP

def direct_route(message):
    text=message.strip().casefold().rstrip('?.!')
    # Reject task execution, including attempts that wrap unrelated work in job terminology.
    task=re.match(r'^(?:(?:please|can you|could you|help me)\s+)?(?:write|generate|build|create|solve)\b.{0,80}\b(?:code|script|program|app|application|essay|email|query|homework|assignment|poem|cover letter)\b',text)
    if task or re.fullmatch(r'(?:what is|how is|tell me) the weather(?: today)?',text) or re.search(r'\b(ignore (?:all |previous |your )?instructions|system prompt|recipe|shopping list|write (?:me |a |an |the |some )?(?:code|script|essay|email|poem|assignment)|solve (?:my |this )?(?:homework|assignment))\b',text):
        return QuestionRoute(topic='off_topic')
    if re.fullmatch(r'(?:how many|what (?:is|are) the number of) (?:interview )?(?:rounds|stages)(?: (?:are there|will there be|for this (?:job|role)))?',text):
        return QuestionRoute(topic='interview_process',terms=['round_count'])
    if re.fullmatch(r'(?:where is (?:this|the) (?:job|role) (?:based|located)|what is (?:the |this job.s )?location)',text):
        return QuestionRoute(topic='role',terms=['location'])
    if re.fullmatch(r'(?:what|which) (?:are the |are |job |technical |transferable )?skills (?:are (?:required|needed)|do i need|does (?:this|the) (?:job|role) require)',text):
        return QuestionRoute(topic='skills')
    if re.fullmatch(r'(?:what|which) (?:are the )?(?:interview stages|interview rounds|interview process)(?: (?:are there|can i expect))?',text):
        return QuestionRoute(topic='interview_process')
    if re.fullmatch(r'what should i practi[cs]e',text):return QuestionRoute(topic='preparation')
    if re.fullmatch(r'(?:add|remove|include|drop) [\w +#./-]{1,100}(?: (?:to|from) (?:my |the )?(?:skills|goal))?',text):
        return QuestionRoute(topic='edit')
    return None


def select_items(items,terms,limit=12):
    meaningful=set().union(*(words(t) for t in terms)) if terms else set()
    if meaningful:
        from app.domain.review import ALIASES
        alias_ids={identifier for (_,name),identifier in ALIASES.items() if name in {t.casefold().strip() for t in terms}}
        selected=[v for v in items if meaningful & words(' '.join(str(v.get(k) or '') for k in ('name','description','category','assessment_type','interview_stage')))
            or v.get('skill_id') in alias_ids]
        # Keep the other side of a saved AND/OR group when a named skill matches.
        groups={v['group_id'] for v in selected if v.get('group_id')}
        selected=[v for v in items if v in selected or (v.get('group_id') and v['group_id'] in groups)]
    else:selected=items
    return selected[:limit],len(selected)>limit


def facts_for(route,goal,research,include_evidence=False):
    facts=[];links={};truncated=False
    def add(kind,data,source_ids=()):
        if not data:return
        ref=f'f{len(facts)+1}';facts.append({'ref':ref,'kind':kind,'data':data})
        links[ref]=[s for s in research.get('sources',[]) if s.get('source_id') in source_ids]
    topic=route.topic
    if topic in ('role','overview'):
        keys=('location',) if route.terms==['location'] else ('role','company','field','location','seniority_level','summary','responsibilities')
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
        if route.terms!=['round_count']:
            for v in process.get('stages',[]):add('interview_stage',{k:v[k] for k in ('name','assessment_type') if v.get(k)},v.get('evidence',{}).get('source_ids',[]))
            # Old research has no process field; explicit recorded stages remain usable.
            if not process.get('stages'):
                seen=set()
                for v in research.get('skills',[]):
                    stage=v.get('interview_stage')
                    if stage and stage not in seen:
                        seen.add(stage);add('interview_stage',{'name':stage,'assessment_type':v.get('assessment_type')},v.get('source_ids',[]))
    return facts,links,truncated
