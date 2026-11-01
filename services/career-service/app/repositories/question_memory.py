"""Immutable focused research plus owner/version-bound pointers in existing collections."""
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from app.repositories.goals import GoalError,fingerprint,now
from app.schemas.analysis import InterviewResearch,Generation
from app.domain.review import MAPPING_VERSION
from app.workflows.opportunity.domain import public_opportunity


class QuestionMemory:
    def __init__(self,workspace,research):
        self.workspace,self.research=workspace,research
        self.rows=research.cache

    def context(self,owner,row):
        w=row['workspace']
        self.workspace.check(owner,w['session_id'],w['revision'])
        goal=self.research.goal(owner,str(row['goal_id']),w['revision'])
        return public_opportunity(goal)[1]

    def entries(self,owner,row):
        context=self.context(owner,row);w=row['workspace']
        pointers=self.rows.find({'kind':'question_result','owner':owner,'goal_id':str(row['goal_id']),
            'goal_version':w['revision'],'context_key':context.reuse_key()}).limit(9)
        records=[]
        for pointer in pointers:
            record=self.research.records.get_research(pointer['research_id'])
            if record and record.question_focus and record.question_findings:records.append(record)
        self.workspace.check(owner,w['session_id'],w['revision'])
        return records

    def save(self,owner,row,focus,findings,sources):
        if not findings:return
        context=self.context(owner,row);w=row['workspace'];stamp=now()
        # Separate public context for focused snapshots: never replace the main
        # report cache or compete for its context/version uniqueness constraint.
        focused=context.model_copy(update={'details_fingerprint':fingerprint({'base':context.reuse_key(),'question_focus':focus})})
        pointer_id='question-result:'+fingerprint({'owner':owner,'goal':str(row['goal_id']),'version':w['revision'],'focus':focus})
        for attempt in range(4):
            previous=self.rows.find_one({'_id':pointer_id})
            old=self.research.records.get_research(previous['research_id']) if previous else None
            merged={f.finding_id:f for f in (old.question_findings if old else [])}
            merged.update({f.finding_id:f for f in findings});kept=list(merged.values())[-12:]
            used={sid for f in kept for sid in f.source_ids}
            source_map={s.source_id:s for s in [*(old.sources if old else []),*sources]}
            original={}
            for source in [*(old.sources if old else []),*sources]:
                original.setdefault(source.source_id,[]).append(source.evidence or '')
            for finding in kept:
                if finding.field!=focus or any(not any(quote in text for text in original.get(sid,[]))
                    for sid,quote in zip(finding.source_ids,finding.quotes)):
                    raise GoalError('Question evidence did not match the retrieved public source.',503)
            # Store exact retained passages, not entire pages; merging another
            # excerpt from the same URL must preserve earlier cited passages.
            retained=[source.model_copy(update={'evidence':'\n'.join(dict.fromkeys(
                quote for f in kept for sid,quote in zip(f.source_ids,f.quotes) if sid==identifier))})
                for identifier,source in source_map.items() if identifier in used]
            counter=self.rows.find_one_and_update({'_id':'question-version:'+focused.reuse_key()},
                {'$inc':{'version':1},'$setOnInsert':{'kind':'question_version'}},upsert=True,return_document=ReturnDocument.AFTER)
            record=InterviewResearch(_id=str(ObjectId()),version=counter['version'],skill_mapping_version=MAPPING_VERSION,
                created_at=stamp,updated_at=stamp,**focused.model_dump(),question_focus=focus,question_findings=kept,
                sources=retained,research_status='succeeded',last_researched_at=stamp,
                generation=Generation(provider='python',model='exact-public-excerpts',prompt_version='saved-question-evidence-v1',generated_at=stamp))
            record=self.research.records.save_research(record,trusted_sources={s.source_id:s for s in retained})
            self.workspace.check(owner,w['session_id'],w['revision'])
            pointer={'kind':'question_result','owner':owner,'goal_id':str(row['goal_id']),'goal_version':w['revision'],
                'context_key':context.reuse_key(),'focus':focus,'research_id':record.id,'updated_at':stamp}
            if previous:
                result=self.rows.update_one({'_id':pointer_id,'research_id':previous['research_id']},{'$set':pointer})
                if not result.matched_count:continue
            else:
                try:self.rows.insert_one({'_id':pointer_id,**pointer})
                except DuplicateKeyError:continue
            self.workspace.check(owner,w['session_id'],w['revision'])
            return record
        raise GoalError('New question findings arrived concurrently. Retry to load the saved evidence.')
