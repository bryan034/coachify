"""Apply narrow chat changes to an owned snapshot, preserving all other values."""
from uuid import uuid4
from pydantic import ValidationError
from app.ai.adapter import AIError
from app.ai.recovery import issues_for
from app.domain.review import prepare
from app.repositories.goals import GoalError
from app.schemas.jd import JDExtraction

FIELDS={
    'goal':{'role','field','employment_type','company','location','seniority_level','job_url','summary'},
    'skills':{'name','category','priority','required_proficiency','required_experience_months','context','group_id','group_operator'},
    'conditions':{'category','description','priority','minimum_months','maximum_months','completion_status','group_id','group_operator'},
    'responsibilities':{'text'},
}
KEYS={'skills':'skills','conditions':'non_skill_requirements','responsibilities':'responsibilities'}
PREFIX={'skills':'s','conditions':'c','responsibilities':'r'}


def invalid(field='changes'):
    raise AIError('invalid_output',True,reason='schema_validation',fields=(field,))


def edit_context(content,pending=None):
    """No evidence blobs, record/item IDs, interview research or full chat history."""
    data={key:getattr(content,key) for key in FIELDS['goal']}
    data['skills']=[{'ref':f's{i}',**{k:getattr(s,k) for k in FIELDS['skills'] if getattr(s,k) is not None}}
        for i,s in enumerate(content.skills)]
    data['conditions']=[{'ref':f'c{i}',**{k:getattr(c,k) for k in FIELDS['conditions'] if getattr(c,k) is not None}}
        for i,c in enumerate(content.non_skill_requirements)]
    data['responsibilities']=[{'ref':f'r{i}','text':v} for i,v in enumerate(content.responsibilities)]
    return {'goal':data,'pending_edit':pending}


def apply_changes(content,changes,message):
    data=content.model_dump(mode='python')
    references={name:{f'{PREFIX[name]}{i}':v for i,v in enumerate(data[key])} for name,key in KEYS.items()}
    responsibility_values={f'r{i}':v for i,v in enumerate(content.responsibilities)}
    responsibility_order=list(responsibility_values)
    added={};touched={};seen=set();groups={};cleared=set()
    for change in changes:
        area,action,ref,field,value=change.collection,change.action,change.reference,change.field,change.value
        if action=='clear':
            if area=='goal' or area in cleared or ref is not None or field is not None or value is not None or any(k[0]==area for k in seen):invalid()
            data[KEYS[area]]=[];cleared.add(area)
            if area=='responsibilities':responsibility_values.clear();responsibility_order.clear()
            continue
        if area in cleared and action!='add':invalid()
        if action=='remove':
            if area=='goal' or field is not None or value is not None or ref not in references[area]:invalid()
            target=references[area][ref]
            if (area,ref,None) in seen or any(k[0]==area and k[1]==ref for k in seen):invalid()
            seen.add((area,ref,None))
            if area=='responsibilities':
                # Original refs remain stable even after another list item is removed.
                del responsibility_values[ref]
            else:data[KEYS[area]]=[v for v in data[KEYS[area]] if v is not target]
            continue
        if field not in FIELDS[area] or (area,ref,field) in seen or (area,ref,None) in seen:invalid()
        seen.add((area,ref,field))
        if area=='goal':
            if action!='set' or ref is not None:invalid()
            data[field]=value;continue
        if area=='responsibilities':
            if not isinstance(value,str) or not value.strip():invalid('responsibilities')
            if action=='add':
                if not ref or not ref.startswith('new') or (area,ref) in added:invalid()
                added[(area,ref)]=True;responsibility_values[ref]=value;responsibility_order.append(ref)
            elif action=='set':
                if ref not in references[area]:invalid()
                responsibility_values[ref]=value
            else:invalid()
            continue
        if action=='add':
            if not ref or not ref.startswith('new'):invalid()
            if (area,ref) not in added:
                item={'origin':'user_declaration','priority':'unspecified','evidence':message}
                if area=='conditions':item['requirement_id']=str(uuid4())
                added[(area,ref)]=item;data[KEYS[area]].append(item)
            target=added[(area,ref)]
        elif action=='set':
            if ref not in references[area]:invalid()
            target=references[area][ref]
        else:invalid()
        if field=='group_id' and value is not None:
            existing={v.group_id for v in [*content.skills,*content.non_skill_requirements] if v.group_id}
            if value not in existing:
                if not isinstance(value,str) or not value.startswith('new'):invalid('group_id')
                groups.setdefault(value,str(uuid4()));value=groups[value]
        target[field]=value
        if field=='priority':
            target['priority_evidence']=message
            if target.get('origin')=='generated_guidance' or value=='suggested':touched[id(target)]=target
        if field not in ('priority','group_id','group_operator'):
            touched[id(target)]=target
    for item in touched.values():
        item['origin']='user_declaration';item['evidence']=message
    data['responsibilities']=[responsibility_values[ref] for ref in responsibility_order if ref in responsibility_values]
    try:
        updated=JDExtraction.model_validate(data)
        if not updated.role or not updated.field:invalid('role' if not updated.role else 'field')
        return prepare(updated,content)
    except ValidationError as error:
        issues=issues_for(error,JDExtraction)
        raise AIError('invalid_output',True,reason='schema_validation',fields=tuple(v['field'].split('.')[0] for v in issues),violations=issues) from None
    except GoalError:
        invalid('changes')
