"""One account workspace; goal selection and workspace pointers change atomically."""
from datetime import timedelta
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.repositories.goals import GoalError,now,stable_id
from app.schemas.analysis import mongo_document
from app.schemas.goals import SaveGoal

class WorkspaceStore:
    def __init__(self,goals,reviews):self.goals,self.reviews,self.rows=goals,reviews,goals.state

    def row(self,owner):
        return self.rows.find_one({'_id':owner}) or {}

    def ensure(self,owner):
        try:self.rows.update_one({'_id':owner},{'$setOnInsert':{'version':0,'goal_id':None,'receipts':[]}},upsert=True)
        except DuplicateKeyError:pass

    def claim_input(self,owner,key,digest):
        self.ensure(owner);row=self.row(owner)
        for receipt in row.get('workspace_inputs',[]):
            if receipt['key']==key:
                if receipt['hash']!=digest:raise GoalError('This input key was used for another description.')
                return False
        incoming=row.get('incoming',{})
        if incoming.get('key')==key and incoming.get('until',now())>now():raise GoalError('This description is already being extracted. Retry shortly.')
        self.rows.update_one({'_id':owner},{'$set':{'incoming':{'key':key,'hash':digest,'until':now()+timedelta(seconds=75)}}})
        return True

    def activate(self,owner,session,review,*,input_key=None,digest=None,keep_run=False,chat_receipt=None):
        row=self.row(owner);workspace=row.get('workspace',{})
        query={'_id':owner,'version':row.get('version',0)}
        if input_key:query['incoming.key']=input_key
        else:query['workspace.session_id']=session
        if input_key and row.get('incoming',{}).get('key')!=input_key:raise GoalError('A newer description replaced this input.')
        if not input_key and workspace.get('session_id')!=session:raise GoalError('This conversation was replaced by a new job description.')
        if not review.content.role or not review.content.field:raise GoalError('The description needs an identifiable role and field. Add more detail and retry.',422)
        selected=row.get('selected_review',{}) or {}
        if not input_key and selected=={'id':review.id,'version':review.version}:return row
        command=SaveGoal(target_type=review.target_type,role=review.content.role,field=review.content.field,company=review.content.company,
            location=review.content.location,seniority_level=review.content.seniority_level,job_url=review.content.job_url,employment_type=review.content.employment_type,
            review_id=review.id,expected_review_version=review.version,expected_selection_version=row.get('version',0),replace_current=True)
        goal=self.reviews.goal(review,owner,stable_id(owner,session+':'+str(review.version)+review.id,'auto-goal'),command,allow_pending_context=True)
        payload=self.goals.persist_target(goal)
        stamp=now()
        workspace={**({} if input_key else workspace),'session_id':session,'kind':'jd' if review.target_type=='specific_job' else 'exploration',
            'review_id':review.id,'revision':review.version,'research_id':None,'coverage':[],'phase':'research_pending','error':None,'retry_after':None,
            'expires_at':stamp+timedelta(hours=24),'updated_at':stamp,'run_id':workspace.get('run_id') if keep_run else str(ObjectId())}
        workspace.pop('edit_draft',None)
        if not keep_run:workspace.pop('worker_until',None)
        update={'$set':{'goal_id':ObjectId(goal.id),'workspace':workspace,'selected_review':{'id':review.id,'version':review.version},'dependent_results_need_review':True},'$inc':{'version':1}}
        if input_key:
            update['$unset']={'incoming':''}
            update['$push']={'workspace_inputs':{'$each':[{'key':input_key,'hash':digest}],'$slice':-100}}
        if chat_receipt:
            update.setdefault('$push',{})['chat_receipts']={'$each':[chat_receipt],'$slice':-100}
        if not self.rows.update_one(query,update).matched_count:raise GoalError('Newer career-goal changes arrived. Reload the current conversation.')
        return self.row(owner)

    def check(self,owner,session,review_version=None):
        row=self.row(owner);workspace=row.get('workspace',{})
        if workspace.get('session_id')!=session:raise GoalError('This conversation was replaced. Open your current career goal.')
        if review_version and workspace.get('revision')!=review_version:raise GoalError('Your career goal changed. Reload its latest version.')
        return row

    def phase(self,owner,session,expected_run,phase,**changes):
        values={'workspace.phase':phase,'workspace.updated_at':now(),**{'workspace.'+k:v for k,v in changes.items()}}
        if not self.rows.update_one({'_id':owner,'workspace.session_id':session,'workspace.run_id':expected_run},{'$set':values}).matched_count:
            raise GoalError('A newer career goal replaced this work.')

    def touch(self,owner,session):
        row=self.check(owner,session);w=row['workspace']
        thread_id=owner+':'+session+':'+w['run_id']
        for collection in ('career_checkpoints','career_checkpoint_writes'):
            self.goals.db[collection].update_many({'thread_id':thread_id},{'$set':{'created_at':now()}})
        self.rows.update_one({'_id':owner,'workspace.session_id':session},{'$set':{'workspace.expires_at':now()+timedelta(hours=24)}})


    def edit_draft(self,owner,session,version,draft):
        query={'_id':owner,'workspace.session_id':session,'workspace.revision':version}
        change={'$set':{'workspace.edit_draft':draft}} if draft else {'$unset':{'workspace.edit_draft':''}}
        if not self.rows.update_one(query,change).matched_count:
            raise GoalError('Your career goal changed. Reload its latest version.')

    def chat_replay(self,owner,key,digest,session):
        row=self.row(owner)
        for receipt in row.get('chat_receipts',[]):
            if receipt['key']==key:
                if receipt['hash']!=digest:raise GoalError('This message key was used with different content.')
                if row.get('workspace',{}).get('session_id')!=session:raise GoalError('This conversation was replaced.')
                return True
        return False
