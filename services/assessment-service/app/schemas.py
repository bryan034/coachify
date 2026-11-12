from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model
from elo_shared.skill_groups import GROUP_NAMES

Text=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=2000)]
class Contract(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Generate(Contract):
    expected_version:int=Field(strict=True,ge=0)
    mutation_id:UUID
    allow_partial:bool=False
class Component(Contract):
    dimension:Literal['capability','proficiency','duration','independence','qualification','eligibility','other']
    status:Literal['supported','uncertain','confirmed_shortfall']
    explanation:Text
    evidence_refs:list[str]=Field(max_length=30)
    # A shortfall needs an explicit limitation/negative declaration, not missing proof.
    limitation_quote:str|None=Field(default=None,max_length=1000)
    support_quote:str|None=Field(default=None,max_length=1000)
class Interpreted(Contract):
    requirement_ref:str
    components:list[Component]=Field(min_length=1,max_length=8)
    recommendation:Text|None=None
    mapping_method:Literal['canonical','semantic','unresolved']
    mapping_reason:Text
    # Job skills only: the model's whole-number levels on one 0–10 scale (3 guided, 6 independent, 9 complex).
    demonstrated_level:int|None=Field(default=None,ge=1,le=10)
    required_level:int|None=Field(default=None,ge=1,le=10)
    score_explanation:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=600)]|None=None
class Batch(Contract):
    outcomes:list[Interpreted]=Field(min_length=1,max_length=8)

def batch_schema(requirements, evidence):
    """Bind the private model response schema to this captured batch's references.

    Nested source IDs are context, not evidence handles. Enumerating the permitted
    handles makes that distinction explicit in the prompt and schema validation.
    The public API and persisted evidence continue to use the original schemas.
    """
    evidence_type=Literal[tuple(evidence)] if evidence else str
    component=create_model('EvidenceComponent',__base__=Component,
        evidence_refs=(list[evidence_type],Field(max_length=30 if evidence else 0)))
    outcome=create_model('RequirementOutcome',__base__=Interpreted,
        requirement_ref=(Literal[tuple(r['ref'] for r in requirements)],...),
        components=(list[component],Field(min_length=1,max_length=8)))
    return create_model('EvidenceBatch',__base__=Batch,
        outcomes=(list[outcome],Field(min_length=1,max_length=8)))

Short=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=600)]
Label=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=40)]
Category=Literal[GROUP_NAMES]
Relevance=Literal['high','medium','low','none']
class SkillJudgement(Contract):
    """One model judgement of a profile skill against the goal. Validated before it is saved."""
    skill_key:str
    category:Category
    subcategory:Label|None=None
    relevance:Relevance
    competence_score:int|None=Field(default=None,ge=0,le=10)
    required_score:int|None=Field(default=None,ge=0,le=10)
    explanation:Short
    evidence_refs:list[str]=Field(default_factory=list,max_length=20)
    requirement_refs:list[str]=Field(default_factory=list,max_length=10)
class SkillBatch(Contract):
    skills:list[SkillJudgement]=Field(min_length=1,max_length=15)
class EvaluatedSkill(Contract):
    name:str
    canonical_skill_id:str|None=None
    category:Category
    subcategory:str|None=None
    relevance:Relevance
    competence_score:int|None=None
    required_score:int|None=None
    explanation:str
    evidence_refs:list[str]
    requirement_refs:list[str]
class SkillProfile(Contract):
    status:Literal['evaluated','partial','failed','empty']
    rubric_version:str
    skills:list[EvaluatedSkill]

class InputVersions(Contract):
    evidence_hash:str|None=None
    as_of_date:str|None=None
    source_mode:Literal['cv_and_profile','profile_only']='cv_and_profile'
    cv_id:str|None
    cv_version:int|None
    extraction_version:int|None
    effective_version:int|None
    cv_selection_version:int
    declarations_version:int
    profile_version:int
    goal_id:str
    goal_version:int
    goal_selection_version:int
    research_id:str|None
    research_version:int|None
    research_coverage:Literal['available','no_findings','unavailable','stale','partial']
    registry_version:str
class Outcome(Contract):
    model_config=ConfigDict(extra='allow')
    ref:str
    kind:Literal['job_skill','interview_preparation','constraint']
    name:str
    match_status:Literal['supported','partial','uncertain','confirmed_shortfall']
    components:list[Component]
    recommendation:str|None
    mapping_method:Literal['canonical','semantic','unresolved']
    mapping_reason:str
    relevance:Literal['high','medium','low','none']|None=None
    competence_score:float|None=Field(default=None,ge=0,le=10)
    required_score:float|None=Field(default=None,ge=0,le=10)
    score_status:Literal['estimated','not_reviewed','insufficient_evidence']='insufficient_evidence'
    score_confidence:Literal['low','medium','high']|None=None
    score_explanation:str|None=None
    scoring_rubric_version:str|None=None
    demonstrated_score:float|None=Field(default=None,ge=0,le=10)
    # Skills Profile skills the per-skill evaluation linked to this requirement.
    profile_skills:list[dict]=Field(default_factory=list)
class Result(Contract):
    schema_version:Literal['assessment-v1']
    id:str
    request_hash:str
    created_at:str
    inputs:InputVersions
    input_hash:str
    source_snapshot:dict
    evidence:dict[str,dict]
    target_type:Literal['specific_job','career_exploration']
    role:str
    job_skill_gaps:list[Outcome]
    interview_prep_gaps:list[Outcome]
    constraints:list[Outcome]
    groups:list[dict]
    priorities:list[str]
    analysis_status:Literal['succeeded','partial']
    research_coverage:Literal['available','no_findings','unavailable','stale','partial']
    # Absent on results saved before per-skill evaluation existed.
    skill_profile:SkillProfile|None=None
class EvaluationStatus(Contract):
    freshness:Literal['missing','current','outdated','unavailable']
    processing:Literal['idle','evaluating','failed']
    completeness:Literal['complete','partial']|None=None
    evaluated_at:str|None=None
    reasons:list[str]=Field(default_factory=list)
class Context(Contract):
    evaluation:EvaluationStatus
    ready:bool
    issues:list[dict]|None=None
    goal:dict|None=None
    cv:dict|None=None
    input_hash:str|None=None
    inputs:InputVersions|None=None
    research_coverage:str|None=None
    evidence:dict[str,dict]|None=None
    # Setup state for the evaluate banner; null until a goal and skills source both exist.
    cv_reviewed:bool|None=None
    research_pending:bool|None=None
    model_available:bool
class Current(Contract):
    evaluation:EvaluationStatus
    version:int
    operation:dict|None
    result:Result|None
    stale:bool
    ready:bool
    issues:list[dict]

SkillName=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=120)]
class SkillRatingInput(Contract):
    """The person's own level for a skill elo could not rate. A null score removes it."""
    expected_version:int=Field(strict=True,ge=0)
    name:SkillName
    canonical_skill_id:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]|None=None
    score:int|None=Field(default=None,strict=True,ge=1,le=10)
class SkillRating(Contract):
    key:str
    name:str
    canonical_skill_id:str|None=None
    score:int=Field(ge=1,le=10)
    updated_at:str
class SkillRatings(Contract):
    version:int
    ratings:list[SkillRating]

class DashboardSource(Contract):
    evaluation:EvaluationStatus
    version:int
    workspace_updated_at:str|None=None
    operation:dict|None=None
    result:Result|None=None
    freshness:Literal['current','stale','missing','unavailable','not_ready','conflict']
    ready:bool|None=None
    issues:list[dict]=Field(default_factory=list)
    input_hash:str|None=None
    inputs:InputVersions|None=None
