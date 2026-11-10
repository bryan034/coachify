from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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
class Batch(Contract):
    outcomes:list[Interpreted]=Field(min_length=1,max_length=8)

class InputVersions(Contract):
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
    score_status:Literal['estimated','not_reviewed','insufficient_evidence']='insufficient_evidence'
    score_explanation:str|None=None
    scoring_rubric_version:str|None=None
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
class Context(Contract):
    ready:bool
    issues:list[dict]|None=None
    goal:dict|None=None
    cv:dict|None=None
    input_hash:str|None=None
    inputs:InputVersions|None=None
    research_coverage:str|None=None
    evidence:dict[str,dict]|None=None
    model_available:bool
class Current(Contract):
    version:int
    operation:dict|None
    result:Result|None
    stale:bool
    ready:bool
    issues:list[dict]

class DashboardSource(Contract):
    version:int
    workspace_updated_at:str|None=None
    operation:dict|None=None
    result:Result|None=None
    freshness:Literal['current','stale','missing','unavailable','not_ready','conflict']
    ready:bool|None=None
    issues:list[dict]=Field(default_factory=list)
    input_hash:str|None=None
    inputs:InputVersions|None=None
