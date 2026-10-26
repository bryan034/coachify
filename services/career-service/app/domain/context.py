"""Bounded semantic catalogue and reference selection; no model-authored DB queries."""
import json
import tiktoken
from app.ai.qa_contracts import QuestionRoute
from app.domain.questions import facts_for

INDEX_TOKENS=1800
FACT_TOKENS=1600
PREFIXES={'s':('skills','skills'),'c':('requirements','non_skill_requirements'),
          'i':('interview_skills','skills'),'p':('interview_process','stages')}


def token_count(value):
    return len(tiktoken.get_encoding('o200k_harmony').encode(
        json.dumps(value,ensure_ascii=False,separators=(',',':')),disallowed_special=()))


def context_index(goal,research,pending=None):
    result={'goal':{k:goal[k] for k in ('role','field','company','location','seniority_level') if goal.get(k)},
            'items':[], 'partial':False,
            'sections':{'skills':len(goal.get('skills',[])), 'requirements':len(goal.get('non_skill_requirements',[])),
                        'interview_skills':len(research.get('skills',[])), 'interview_process':bool(research.get('process') or any(s.get('interview_stage') for s in research.get('skills',[])))}}
    if pending:result['pending_edit']={k:str(pending.get(k) or '')[:300] for k in ('intent','question')}
    arrays={'s':goal.get('skills',[]),'c':goal.get('non_skill_requirements',[]),
            'i':research.get('skills',[]),'p':(research.get('process') or {}).get('stages',[])}
    for prefix,items in arrays.items():
        for index,item in enumerate(items):
            value={'ref':f'{prefix}{index}','label':str(item.get('name') or item.get('description') or '')[:120]}
            if item.get('category'):value['category']=str(item['category'])[:40]
            result['items'].append(value)
    while token_count(result)>INDEX_TOKENS and result['items']:
        result['items'].pop();result['partial']=True
    return result


def selected_documents(plan,goal,research):
    """Indices resolve to this immutable snapshot; keep both sides of AND/OR groups."""
    if not plan.item_refs:return goal,research
    goal=dict(goal);research=dict(research)
    for prefix,(_,field) in PREFIXES.items():
        container=goal if prefix in ('s','c') else research
        if prefix=='p':container=dict(research.get('process') or {});research['process']=container
        original=container.get(field,[])
        wanted={int(ref[1:]) for ref in plan.item_refs if ref.startswith(prefix)}
        groups={item['group_id'] for i,item in enumerate(original) if i in wanted and item.get('group_id')}
        container[field]=[item for i,item in enumerate(original) if i in wanted or (item.get('group_id') and item['group_id'] in groups)]
    return goal,research


def selected_facts(plan,goal,research):
    goal,research=selected_documents(plan,goal,research)
    topics=list(dict.fromkeys([plan.topic,*plan.related_topics,*[PREFIXES[ref[0]][0] for ref in plan.item_refs]]))
    if 'overview' in topics:topics=['overview']
    facts=[];links={};partial=False;seen=set()
    for topic in topics:
        if topic in ('edit','off_topic'):continue
        values,sources,cut=facts_for(QuestionRoute(topic=topic),goal,research,plan.include_evidence);partial|=cut
        for value in values:
            digest=json.dumps([value['kind'],value['data']],sort_keys=True,default=str)
            if digest in seen:continue
            seen.add(digest)
            ref=f'f{len(facts)+1}';item={**value,'ref':ref}
            if token_count([*facts,item])>FACT_TOKENS:partial=True;continue
            facts.append(item);links[ref]=sources[value['ref']]
    return facts,links,partial


def merge_projection(target,addition):
    """Mongo projections preserve array order; merge complementary projected fields."""
    if isinstance(target,dict) and isinstance(addition,dict):
        return {key:merge_projection(target.get(key),value) for key,value in {**target,**addition}.items()}
    if isinstance(target,list) and isinstance(addition,list):
        return [merge_projection(target[i] if i<len(target) else None,addition[i] if i<len(addition) else target[i])
                for i in range(max(len(target),len(addition)))]
    return addition
