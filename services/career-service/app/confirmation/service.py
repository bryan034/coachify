"""Version-bound operational acknowledgement; canonical goals remain authoritative."""
import unicodedata
import re
from uuid import uuid5, NAMESPACE_URL
from bson import ObjectId
from app.repositories.goals import GoalError, fingerprint, now
from app.schemas.analysis import CareerGoal
from app.schemas.cv_confirmation import CvConfirmedContext, CvConfirmationView


def identity(state):
    return state.get('goal_id'), state.get('version', 0)


def canonical_name(name):
    return 'skill:' + ' '.join(unicodedata.normalize('NFKC', name).split()).casefold()


QUALIFICATION_WORDS={'degree','degrees','diploma','diplomas','bachelor','bachelors','master','masters','phd','certificate','certificates','certification','certifications','qualification','qualifications'}
SUBJECT_BOUNDARIES=QUALIFICATION_WORDS|{'a','an','the','in','of','or','and','either','equivalent','related','field','fields','discipline','disciplines',
    'relevant','recognized','recognised','education','academic','university','college','institution','institutions','from','with','at','to','for',
    'is','are','be','must','have','hold','holder','holders','completion','completed','obtained','obtaining','awarded','required','require',
    'requirements','preferred','desirable','minimum','least','above'}


def qualification_terms(description):
    """Source-derived subject phrases establish relevance, never equivalence.

    A CV may name Computer Science without naming the requested diploma. Retain
    that exact subject so its unresolved qualification can be clarified. Fixed
    function words and credential names bound phrases; no subjects are invented.
    """
    text=unicodedata.normalize('NFKC',description)
    subjects=[];start=None;end=None
    def flush():
        nonlocal start,end
        if start is not None:
            phrase=' '.join(text[start:end].split())
            if len(phrase)>=2:subjects.append(phrase)
        start=end=None
    for match in re.finditer(r"[^\W\d_]+(?:['’][^\W\d_]+)?",text):
        word=match.group().casefold()
        stem=re.sub(r"['’]s$",'',word)
        if start is not None and re.search(r'[/&;,()]',text[end:match.start()]):flush()
        if stem in SUBJECT_BOUNDARIES or len(stem)<2:flush();continue
        if start is None:start=match.start()
        end=match.end()
    flush()
    nouns=[word for word in ('degree','diploma','bachelor','master','phd','certificate','certification') if word in text.casefold()]
    # Derived search phrases are bounded; the complete original condition remains
    # separately preserved in description/evidence and is never truncated.
    return list(dict.fromkeys(subjects))[:7] or nouns or [description]


def project(goal, selection_version):
    conditions=[]
    for requirement in goal.non_skill_requirements:
        qualification=requirement.category == 'qualification'
        # Generic requirements are retained, but exact text matching cannot infer
        # eligibility, location or work-condition claims from unrelated CV items.
        terms=[requirement.description]
        if qualification:
            terms=qualification_terms(requirement.description)
        conditions.append({'id':str(uuid5(NAMESPACE_URL, 'elo:canonical-requirement:'+goal.id+':'+requirement.requirement_id)),
            'kind':'qualification' if qualification else 'requirement',
            'label':requirement.category.replace('_',' ').capitalize()+' requirement',
            'description':requirement.description, 'item_kinds':['education'] if qualification else ['education','experience','project','skill'],
            'match_terms':terms, 'evidence':requirement.evidence,
            'origin':'user_reviewed_jd' if requirement.origin=='employer' else 'user_guidance',
            'source_requirement_id':requirement.requirement_id,'source_category':requirement.category,
            'source_priority':requirement.priority,'source_origin':requirement.origin,
            'group_id':requirement.group_id,'group_operator':requirement.group_operator})
    # This identity is a name-based relevance key, not a claimed registry mapping
    # or an assessment of the user's competence. Preserve every requirement above.
    skills=list(dict.fromkeys(canonical_name(skill.name) for skill in goal.skills))
    return CvConfirmedContext(id=goal.id,version=goal.version,type=goal.target_type,skill_ids=skills,
        selection_version=selection_version,role=goal.role,field=goal.field,conditions=conditions).model_dump(mode='json')


class CvConfirmationService:
    def __init__(self, goals):
        self.goals,self.state=goals,goals.state

    def snapshot(self, owner):
        for _ in range(3):
            state=self.state.find_one({'_id':owner}) or {'version':0,'goal_id':None}
            raw=self.goals.goals.find_one({'_id':state['goal_id'],'user_id':owner}) if state.get('goal_id') else None
            again=self.state.find_one({'_id':owner}) or {'version':0,'goal_id':None}
            if identity(state)!=identity(again): continue
            goal=CareerGoal.model_validate({k:v for k,v in raw.items() if k in CareerGoal.model_fields or k=='_id'}) if raw else None
            return again,goal
        raise GoalError('Your Career goal changed while loading. Reload and review it again.')

    def view(self, owner):
        state,goal=self.snapshot(owner)
        value={'goal_id':goal.id if goal else None,'goal_version':goal.version if goal else None,
            'selection_version':state.get('version',0),'confirmed':False,'context':None,'reason':None}
        if goal is None: value['reason']='Save a Career goal before confirming it for CV clarification.'
        elif goal.requirements_need_review: value['reason']='Review the changed Career requirements before confirming this goal.'
        elif not goal.skills and not goal.non_skill_requirements: value['reason']='Add or clarify at least one skill or requirement before confirming this goal.'
        elif state.get('version',0)<1: value['reason']='Select the current Career goal before confirming it.'
        else:
            context=project(goal,state['version'])
            stamp=state.get('cv_confirmation') or {}
            expected={'goal_id':goal.id,'goal_version':goal.version,'selection_version':state['version'],
                      'projection_hash':fingerprint(context),'goal_hash':fingerprint(goal.model_dump(mode='json',by_alias=True))}
            if all(stamp.get(key)==item for key,item in expected.items()):
                value.update(confirmed=True,context=context)
        return CvConfirmationView.model_validate(value).model_dump(mode='json')

    def confirm(self, owner, mutation):
        body=mutation.model_dump(mode='json'); key=body['mutation_id']; digest=fingerprint(body)
        before=self.view(owner)
        expected=(body['expected_goal_id'],body['expected_goal_version'],body['expected_selection_version'])
        actual=(before['goal_id'],before['goal_version'],before['selection_version'])
        if expected!=actual: raise GoalError('Your Career goal changed. Reload and confirm the current version.')
        if before['reason']: raise GoalError(before['reason'],422)
        state,goal=self.snapshot(owner)
        for receipt in state.get('cv_confirmation_receipts',[]):
            if receipt['key']==key:
                if receipt['hash']!=digest: raise GoalError('This confirmation key was used with different details.')
                # Re-read instead of replaying an obsolete context after a goal edit.
                current=self.view(owner)
                if not current['confirmed']: raise GoalError('Your Career goal changed. Review it again before confirming.')
                return current
        context=project(goal,state['version'])
        if (goal.id,goal.version,state['version'])!=expected:
            raise GoalError('Your Career goal changed. Reload and confirm the current version.')
        stamp={'goal_id':goal.id,'goal_version':goal.version,'selection_version':state['version'],
               'projection_hash':fingerprint(context),'goal_hash':fingerprint(goal.model_dump(mode='json',by_alias=True)),'confirmed_at':now()}
        receipt={'key':key,'hash':digest}
        result=self.state.update_one({'_id':owner,'goal_id':ObjectId(goal.id),'version':state['version'],
            'cv_confirmation_receipts.key':{'$ne':key}},
            {'$set':{'cv_confirmation':stamp},'$push':{'cv_confirmation_receipts':{'$each':[receipt],'$slice':-100}}})
        if not result.matched_count:
            latest=self.state.find_one({'_id':owner}) or {}
            prior=next((r for r in latest.get('cv_confirmation_receipts',[]) if r['key']==key),None)
            if prior!=receipt: raise GoalError('Your Career goal changed. Reload and review it again.')
        after=self.view(owner)
        if (after['goal_id'],after['goal_version'],after['selection_version'])!=expected or not after['confirmed']:
            raise GoalError('Your Career goal changed while confirming. Review the current version.')
        return after

    def context(self, owner, identifier=None, version=None):
        value=self.view(owner)
        context=value['context']
        if identifier is not None and (not context or context['id']!=identifier or context['version']!=version):
            raise GoalError('This Career goal is no longer the current confirmed version.')
        return context
