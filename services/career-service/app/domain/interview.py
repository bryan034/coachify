"""Validate original excerpts and explicitly attributed Brave synthesis separately."""
from app.ai.adapter import AIError
from app.domain.review import ALIASES
from app.domain.skills import canonical_skill_id
from app.schemas.analysis import InterviewSkill


def topics_from(output,sources,summaries=()):
    lookup={s.source_id:s for s in sources};answers={s.summary_id:s for s in summaries};skills=[]
    for topic in output.topics:
        if len(topic.source_ids)!=len(topic.quotes) or len(set(topic.source_ids))!=len(topic.source_ids) or any(s not in lookup for s in topic.source_ids):
            raise AIError('invalid_output',True,reason='provenance')
        summary=answers.get(topic.summary_id) if topic.evidence_origin=='brave_summary' else None
        if topic.evidence_origin=='brave_summary':
            if not summary or not any(set(topic.source_ids)<=set(c.source_ids) for c in summary.claims):raise AIError('invalid_output',True,reason='provenance')
            evidence={s:[c.text for c in summary.claims if s in c.source_ids] for s in topic.source_ids}
        else:
            if topic.summary_id is not None:raise AIError('invalid_output',True,reason='provenance')
            evidence={s:[lookup[s].evidence or ''] for s in topic.source_ids}
        if any(not quote.strip() or not any(quote in text for text in evidence[s]) for s,quote in zip(topic.source_ids,topic.quotes)):
            raise AIError('invalid_output',True,reason='provenance')
        if any(not pattern.strip() or not any(pattern in text for texts in evidence.values() for text in texts) for pattern in topic.question_patterns):
            raise AIError('invalid_output',True,reason='provenance')
        cited=' '.join(text for texts in evidence.values() for text in texts).casefold()
        try:skill_id=canonical_skill_id(topic.name,topic.category,ALIASES)
        except ValueError:skill_id=None
        data=topic.model_dump(exclude={'quotes'})
        for field in ('interview_stage','assessment_type'):
            if data[field] and data[field].casefold() not in cited:data[field]=None
        if data['difficulty'] not in cited:data['difficulty']='unknown'
        if skill_id and any(s.skill_id==skill_id for s in skills):continue
        skills.append(InterviewSkill(**data,skill_id=skill_id,independent_report_count=len({lookup[s].report_group for s in topic.source_ids if lookup[s].report_group})))
    return skills


def supported_round_count(count,text):
    import re
    words=('one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty')
    token=rf'(?:{count}|{words[count-1]})'
    return bool(re.search(rf'\b{token}[-\s]+(?:interview\s+)?(?:rounds?|stages?)\b|\b(?:rounds?|stages?)\s*:\s*{token}\b',text,re.I))
