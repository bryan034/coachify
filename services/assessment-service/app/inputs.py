"""Versioned snapshots read only through the owning services' APIs."""
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from elo_shared.runtime import Problem, digest
from elo_shared.skills import identity, MAPPING_VERSION

async def capture(upstream,account):
    token=account['token']
    career,listing,manual=await asyncio.gather(
        upstream.read('career','/api/v1/career/assessment-input',token),
        upstream.read('cv','/api/v1/cv',token),
        upstream.read('profile','/api/v1/profile/capabilities',token))
    selection=listing.get('selection') or {}; cv_id=selection.get('cv_id')
    issues=[]
    if not career.get('ready'):issues.append({'source':'career','message':career.get('reason') or 'Extract and review a Career goal first.','href':'/career-goal'})
    if not cv_id: issues.append({'source':'cv','message':'Upload, extract and select a CV before planning.','href':'/cv'})
    if issues:return {'ready':False,'issues':issues,'goal':career.get('goal'),'cv':None}
    cv=await upstream.read('cv','/api/v1/cv/'+cv_id,token)
    if cv.get('status')!='ready':return {'ready':False,'issues':[{'source':'cv','message':'Finish or retry the selected CV extraction.','href':'/cv'}],'goal':career.get('goal'),'cv':{'id':cv_id,'status':cv.get('status')}}
    source=await upstream.read('cv','/api/v1/cv/'+cv_id+'/assessment-input',token,params={
        'expected_version':cv['version'],'expected_selection_version':selection['version'],
        'expected_declarations_version':manual['version']})
    goal=career['goal']; research=career.get('research')
    coverage='unavailable'
    if research:
        intelligence=research.get('intelligence')
        interview=(intelligence or {}).get('categories',{}).get('interview_intelligence',{})
        if intelligence:
            expires=interview.get('expires_at') or intelligence.get('expires_at')
            stale=bool(expires and datetime.fromisoformat(expires.replace('Z','+00:00'))<=datetime.now(timezone.utc))
            if stale:coverage='stale'
            elif interview.get('status')=='completed': coverage='available' if interview.get('findings') else 'no_findings'
            elif interview.get('status')=='partial':coverage='partial'
        elif research.get('research_status') in ('succeeded','no_findings'):
            coverage='available' if research.get('skills') else 'no_findings'
    # Evidence records keep exact source attribution and the original literal explanations.
    evidence={}
    for item in source['items']:
        if item.get('removed'):continue
        ref='cv:'+item['id']
        evidence[ref]={'ref':ref,'kind':item['kind'],'name':item['title'],'text':item['description'],
            'attribution':'unknown','assistance':'unknown','unscoped_item':bool(item.get('skill_claims')),'support_uncertain':item.get('support_uncertain',False),
            'start_date':item.get('start_date'),'end_date':item.get('end_date'),'ongoing':item.get('ongoing',False),
            'provenance':item.get('provenance'),'evidence':item.get('evidence',[])}
        for index,claim in enumerate(item.get('skill_claims',[])):
            key=ref+':claim:'+str(index)
            evidence[key]={'ref':key,'kind':'skill','name':claim['name'],'text':'\n'.join(e['excerpt'] for e in claim.get('evidence',[])),
                **{k:claim.get(k) for k in ('attribution','assistance','proficiency','experience_months','support_uncertain','evidence_type')},**identity(claim['name'])}
    for declaration in source['declarations']:
        ref='declaration:'+declaration['id']
        evidence[ref]={'ref':ref,'kind':'user_declaration','name':declaration['name'],
            'text':'\n'.join([declaration['description'],*[c['description'] for c in declaration.get('contributions',[])]]),
            'attribution':'personal','assistance':'unknown','support_uncertain':False,
            'attachment':declaration.get('attached_to'),**identity(declaration['name'])}
    # Background supports qualification context; it cannot establish capability by status.
    education=account['profile'].get('education')
    if education:
        import json
        evidence['profile:education']={'ref':'profile:education','kind':'education','name':'Declared education',
            'text':json.dumps(education,ensure_ascii=False),'attribution':'personal','support_uncertain':False}
    requirements=[]
    for index,skill in enumerate(goal['skills']):
        ref='job:'+str(skill.get('item_id') or index)
        requirements.append({**skill,'ref':ref,'kind':'job_skill','name':skill['name'],**identity(skill['name'],skill.get('category'))})
    for condition in goal.get('non_skill_requirements',[]):
        requirements.append({**condition,'ref':'condition:'+condition['requirement_id'],'kind':'constraint','name':condition['description']})
    if research and coverage in ('available','partial'):
        category=(research.get('intelligence') or {}).get('categories',{}).get('interview_intelligence',{})
        findings=category.get('findings',[]) or research.get('skills',[])
        for index,f in enumerate(findings):
            # Only preparation-bearing fields enter skill comparison; timelines/stage counts stay context.
            if f.get('field') and f['field'] not in ('preparation_topics','interview_questions','difficulty'):continue
            name=f.get('value') or f.get('name')
            requirements.append({**f,'ref':'interview:'+str(f.get('finding_id') or index),'kind':'interview_preparation',
                'name':name,'priority':'suggested','origin':'interview_research',**identity(name)})
    time_sensitive=bool(goal.get('non_skill_requirements') or any(item.get('ongoing') for item in source['items']))
    vector={'as_of_date':datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat() if time_sensitive else None,'cv_id':cv_id,'cv_version':source['cv_version'],'extraction_version':source['extraction_version'],
        'effective_version':source['effective_version'],'cv_selection_version':source['selection_version'],
        'declarations_version':source['declarations_version'],'profile_version':account['profile']['version'],
        'goal_id':goal['_id'],'goal_version':goal['version'],'goal_selection_version':career['selection_version'],
        'research_id':research['_id'] if research else None,'research_version':research['version'] if research else None,
        'research_coverage':coverage,'registry_version':MAPPING_VERSION}
    return {'ready':True,'issues':[],'goal':goal,'cv':{'id':cv_id,'name':cv['file_name']},'inputs':vector,
        'input_hash':digest(vector),'requirements':requirements,'evidence':evidence,
        'source_snapshot':{'capabilities':source,'goal':goal,'research':research,'education':education},'research_coverage':coverage}
