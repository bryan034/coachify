"""Owner/goal-linked reads with fixed MongoDB projections for each question topic."""
from bson import ObjectId
from app.repositories.goals import GoalError

META=('role','field','company','location','seniority_level')
GOAL_FIELDS={
 'role':(*META,'summary','responsibilities'), 'skills':('skills',),
 'requirements':('non_skill_requirements',), 'interview_process':(),
 'opportunity':(), 'interview_skills':(), 'preparation':('skills',),
 'overview':(*META,'summary','responsibilities','skills','non_skill_requirements'),
}
class QuestionStore:
    def __init__(self,workspace,research):self.workspace,self.research=workspace,research

    def goal(self,owner,review_id,fields):
        projection={'record_type':1,'version':1}
        for key in fields:
            projection[key]=1;projection['content.'+key]=1
        row=self.workspace.reviews.rows.find_one({'_id':ObjectId(review_id),'user_id':owner},projection)
        if not row:raise GoalError('Career goal review was not found.',404)
        content=row.get('content',{}) if row.get('record_type')=='requirement_review' else row
        return {key:content[key] for key in fields if key in content}

    def metadata(self,owner,review_id):return self.goal(owner,review_id,META)

    def fetch(self,owner,row,topic,include_evidence=False):
        if topic not in GOAL_FIELDS:raise ValueError('Unsupported question topic')
        w=row['workspace'];goal=self.goal(owner,w['review_id'],GOAL_FIELDS[topic])
        identifier=w.get('research_id')
        if not identifier:return goal,{}
        linked=self.research.linked(owner,str(row['goal_id']))
        if identifier not in linked:raise GoalError('Research reference was not found for this goal.',404)
        fields={'research_status':1,'sources.source_id':1,'sources.url':1,'sources.title':1}
        fields['intelligence.categories']=1
        if topic in ('interview_process','overview'):fields.update({'process':1,'skills.interview_stage':1,'skills.assessment_type':1,'skills.source_ids':1})
        if topic in ('interview_skills','preparation','overview'):fields['skills']=1
        if include_evidence and topic in ('interview_skills','preparation','overview'):
            fields.update({'sources.evidence':1,'summaries.summary_id':1,'summaries.claims':1})
        # Parent projection subsumes nested skill fields; Mongo rejects path collisions.
        if 'skills' in fields:
            fields={k:v for k,v in fields.items() if not k.startswith('skills.')}
        research=self.research.records.database.interview_research.find_one({'_id':ObjectId(identifier)},fields)
        if not research or research.get('research_status') not in ('succeeded','no_findings'):raise GoalError('Interview research needs retry.')
        if research.get('intelligence'):
            from app.workflows.opportunity.domain import compatibility
            from app.schemas.opportunity import CategoryResult
            categories={k:CategoryResult.model_validate(v) for k,v in research['intelligence']['categories'].items()}
            skills,process=compatibility(categories)
            # In-memory question projection only; all citations still resolve through linked research.
            research.update(skills=[s.model_dump(mode='json') for s in skills],process=process.model_dump(mode='json'))
        return goal,research
