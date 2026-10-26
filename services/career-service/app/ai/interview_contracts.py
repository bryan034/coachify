"""Compact model output; trusted evidence links are restored by the backend."""
from typing import Literal
from pydantic import Field
from app.schemas.analysis import Contract,Text,Evidence,InterviewProcess,InterviewEvidence,InterviewStage
from app.schemas.research import SourcedTopics,Topic


def evidence_items(request):
    items=[]
    for source in request.sources:
        if source.evidence:
            items.append({'ref':f'e{len(items)+1}','origin':'source_excerpt','text':source.evidence,
                'source_ids':[source.source_id],'summary_id':None})
    known={s.source_id for s in request.sources}
    for summary in request.summaries:
        for claim in summary.claims:
            ids=list(dict.fromkeys(s for s in claim.source_ids if s in known))[:3]
            if ids:
                items.append({'ref':f'e{len(items)+1}','origin':'brave_summary','text':claim.text,
                    'source_ids':ids,'summary_id':summary.summary_id})
    return items


def interview_input(request):
    context=request.public_context
    if hasattr(context,'model_dump'):context=context.model_dump(mode='json',exclude_none=True)
    return {'stage':'interview_synthesis','public_context':context,
        'evidence':[{'ref':v['ref'],'origin':v['origin'],'text':v['text']} for v in evidence_items(request)]}


class Finding(Contract):
    name: Text
    category: Text
    interview_stage: Text | None = None
    assessment_type: Text | None = None
    difficulty: Literal['introductory','intermediate','advanced','unknown'] = 'unknown'
    question_patterns: list[Evidence] = Field(default_factory=list,max_length=8)
    evidence_ref: Text


class StageFinding(Contract):
    name: Text
    assessment_type: Text | None=None
    evidence_ref: Text

class ProcessFinding(Contract):
    round_count: int | None=Field(default=None,ge=1,le=20,strict=True)
    count_evidence_ref: Text | None=None
    stages: list[StageFinding]=Field(default_factory=list,max_length=8)

class InterviewFindings(Contract):
    process: ProcessFinding | None=None
    topics: list[Finding] = Field(max_length=20)

    def to_domain(self,request):
        evidence={v['ref']:v for v in evidence_items(request)}
        topics=[]
        for finding in self.topics:
            item=evidence.get(finding.evidence_ref)
            if item is None:raise ValueError('Unknown interview evidence reference')
            topics.append(Topic(**finding.model_dump(exclude={'evidence_ref'}),
                evidence_origin=item['origin'],summary_id=item['summary_id'],
                source_ids=item['source_ids'],quotes=[item['text'] for _ in item['source_ids']]))
        process=InterviewProcess()
        if self.process:
            def link(ref):
                item=evidence.get(ref)
                if not item:raise ValueError('Unknown process evidence reference')
                return InterviewEvidence(evidence_origin=item['origin'],summary_id=item['summary_id'],source_ids=item['source_ids'],text=item['text'])
            if self.process.round_count is not None:
                count_link=link(self.process.count_evidence_ref)
                from app.domain.interview import supported_round_count
                if not supported_round_count(self.process.round_count,count_link.text):raise ValueError('Unsupported round count')
                process.round_count=self.process.round_count
                process.round_count_evidence=count_link
            elif self.process.count_evidence_ref is not None:raise ValueError('Count reference without a count')
            for stage in self.process.stages:
                stage_link=link(stage.evidence_ref)
                if stage.name.casefold() not in stage_link.text.casefold():raise ValueError('Unsupported interview stage')
                assessment=stage.assessment_type if stage.assessment_type and stage.assessment_type.casefold() in stage_link.text.casefold() else None
                process.stages.append(InterviewStage(name=stage.name,assessment_type=assessment,evidence=stage_link))
        return SourcedTopics(topics=topics,process=process)
