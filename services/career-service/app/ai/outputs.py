"""Structured output model for every model stage, and the field names their errors may report."""
from app.ai.context_contracts import ContextPlan
from app.ai.contracts import OUTPUTS
from app.ai.discovery_contracts import OUTPUTS as DISCOVERY_OUTPUTS
from app.ai.goal_edit_contracts import GoalEditDecision
from app.ai.goal_summary import GoalSummary
from app.ai.interview_contracts import InterviewFindings
from app.ai.interview_prep import PrepSuggestions
from app.ai.jd_contracts import ExtractedJD, WorkspaceAnswer
from app.ai.jd_scope import JobIdentity
from app.ai.opportunity_contracts import QueryPlan, ReferencedFindings, SkillLevels, StructuredFindings, Triage
from app.ai.passage_scope import PassageScopes
from app.ai.qa_contracts import FocusedAnswer, QuestionRoute
from app.ai.recovery import schema_fields
from app.ai.research_planning import ResearchAssessment, ResearchPlan
from app.ai.brief_contracts import InterviewBriefOutput, RoleBriefOutput
from app.ai.role_summary import RoleDigest
from app.schemas.round_titles import RoundTitles

MODEL_OUTPUTS = {'passage_scope':PassageScopes,'goal_summary':GoalSummary,'interview_prep':PrepSuggestions,'role_summary':RoleDigest,'role_brief':RoleBriefOutput,'interview_brief':InterviewBriefOutput,'interview_round_titles':RoundTitles,'jd_scope':JobIdentity,**OUTPUTS,**DISCOVERY_OUTPUTS,'opportunity_plan':QueryPlan,'opportunity_triage':Triage,'opportunity_structure':ReferencedFindings,'opportunity_skill_levels':SkillLevels,'jd_extraction': ExtractedJD, 'role_guidance': ExtractedJD, 'interview_synthesis': InterviewFindings, 'workspace_chat': WorkspaceAnswer, 'question_route':QuestionRoute, 'focused_answer':FocusedAnswer,'goal_edit':GoalEditDecision,'context_route':ContextPlan,'context_answer':FocusedAnswer,'career_guidance':FocusedAnswer,'research_plan':ResearchPlan,'research_assess':ResearchAssessment}

VALIDATION_FIELDS = set().union(*(schema_fields(model.model_json_schema()) for model in [*MODEL_OUTPUTS.values(),StructuredFindings]))
