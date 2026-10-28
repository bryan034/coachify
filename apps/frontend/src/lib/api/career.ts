import { ApiError } from './profile';
export type CareerPreview = { kind: 'url' | 'document'; text: string; source_name: string; source_url?: string | null; notices: string[] };
export async function importCareer(path: 'url' | 'document', body: string | FormData, token: string, signal: AbortSignal): Promise<CareerPreview> {
 const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1'}/career/imports/${path}`, {
  method: 'POST', body, signal, cache: 'no-store',
  headers: { Authorization: `Bearer ${token}`, ...(typeof body === 'string' ? { 'Content-Type': 'application/json' } : {}) },
 });
 const result = await response.json().catch(() => ({}));
 if (!response.ok) {
  if (response.status === 401) window.dispatchEvent(new CustomEvent('coachify:expired', { detail: token }));
  throw new ApiError(typeof result.detail === 'string' ? result.detail : response.status === 413 ? 'Choose a file up to 10 MiB.' : 'The preview service is unavailable. Retry or paste the description.', response.status);
 }
 if (!result.text || typeof result.text !== 'string' || Array.from(result.text).length > 20_000 || !['url','document'].includes(result.kind) || !Array.isArray(result.notices))
  throw new Error('The source returned an invalid preview. Retry or paste the description.');
 return result;
}

export type RoleSuggestion = { role: string; field: string; rationale: string; uncertainty: string };
export type GoalDraft = {
 _id: string; version: number; answers: Record<string,{status:string;value:string|null}>;
 turns: { question: string; answer: {status:string;value:string|null}; reply: string }[];
 interests: string[]; preferences: string[]; suggestions: RoleSuggestion[];
 total_turns?:number;focus?:string|null;agent_question?:string|null;
 next_question: string | null; question_text: string | null; context_complete: boolean;
 cv: {mode:'none'|'temporary'|'saved';filename:string|null;cv_id:string|null;version:number|null;extraction_version:string|null};
};
export type DiscoveryEvidence={research_id:string;selected_area:string;related_roles:string[];specificity:'field'|'role_area'|'specialisation';listings_analysed:number;employers_analysed:number;coverage:'good'|'limited'|'insufficient';source_ids:string[];researched_at:string};
export type SavedGoal = {discovery?:DiscoveryEvidence|null; _id:string; version:number; target_type:'specific_job'|'career_exploration';role:string;field:string;
 employment_type?:'internship'|'full_time'|'part_time'|'contract'|'unknown';company:string|null;location:string|null;seniority_level:string|null;job_url:string|null;
 summary?:string|null;responsibilities?:string[];non_skill_requirements?:ReviewCondition[];
 skills:ReviewSkill[];interests:string[];preferences:string[];readiness:'pending'|'ready';
 source_review_id?:string|null;source_review_version?:number|null;requirements_need_review?:boolean; exploration_draft_id:string|null;exploration_draft_version:number|null };
export type CurrentGoal = {review_selection?:{id:string;version:number}|null;selection_version:number;goal:SavedGoal|null;dependent_results_need_review:boolean};
export type CareerContext = {cvs:{id:string;filename:string;status:string;version:number;extraction_version:string}[];cv_service_available:boolean;ai_available:boolean};
export class CareerApiError extends ApiError {
 retryAt:number|null;
 constructor(message:string,status:number,public code?:string,retryAfter?:number){
  super(message,status);this.retryAt=typeof retryAfter==='number'&&Number.isFinite(retryAfter)&&retryAfter>0?Date.now()+retryAfter*1000:null;
 }
}
export async function careerApi<T>(path:string,token:string, options:RequestInit={}):Promise<T>{
 const response=await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1'}/career${path}`,{
  ...options,cache:'no-store',headers:{Authorization:`Bearer ${token}`,...(typeof options.body==='string'?{'Content-Type':'application/json'}:{}),...options.headers},
 });
 const body=await response.json().catch(()=>({}));
 if(!response.ok){
  if(response.status===401)window.dispatchEvent(new CustomEvent('coachify:expired',{detail:token}));
  throw new CareerApiError(typeof body.detail==='string'?body.detail:'Career Goal is unavailable. Please retry.',response.status,body.code,body.retry_after);
 }
 return body as T;
}
export async function importExplorationCV(file:File,token:string,signal:AbortSignal):Promise<CareerPreview>{
 const body=new FormData();body.set('file',file);
 return careerApi<CareerPreview>('/explorations/cv/document',token,{method:'POST',body,signal});
}

export type ReviewSkill={item_id?:string|null;skill_id?:string|null;group_id?:string|null;group_operator?:'all'|'any';correction?:'extracted'|'user';source_urls?:string[];name:string;category:string;priority:'required'|'preferred'|'unspecified'|'conflicting'|'suggested';priority_evidence?:string|null;priority_origin?:'employer'|'generated_guidance'|'user_declaration'|'market_research'|null;required_proficiency?:string|null;required_experience_months?:number|null;context?:string|null;evidence?:string|null;origin:'employer'|'generated_guidance'|'user_declaration'|'market_research'};
export type ReviewCondition={requirement_id:string;category:string;description:string;priority:string;priority_evidence?:string|null;priority_origin?:'employer'|'generated_guidance'|'user_declaration'|'market_research'|null;evidence:string;group_id:string|null;group_operator:'all'|'any';origin?:'employer'|'generated_guidance'|'user_declaration'|'market_research';correction?:'extracted'|'user';source_urls?:string[];minimum_months?:number|null;maximum_months?:number|null;completion_status?:'completed'|'in_progress'|'unspecified'};
export type JDExtraction={role:string|null;field:string|null;employment_type?:'internship'|'full_time'|'part_time'|'contract'|'unknown';company:string|null;location:string|null;seniority_level:string|null;job_url:string|null;
 summary:string|null;responsibilities:string[];non_skill_requirements:ReviewCondition[];skills:ReviewSkill[]};
export type SavedReview={current:{goal:SavedGoal}};
export type JDReview=SavedReview&{turns:{message:string;reply:string}[];proposals:ReviewSkill[]|null};

export type ResearchSource={source_id:string;platform:string;url:string;title:string|null;evidence?:string|null;retrieved_at?:string|null;published_date:string|null;reported_date:string|null;role_match:string;reliability:string;report_group:string|null};
export type InterviewSummary={summary_id:string;provider:string;text:string;source_ids:string[];claims:{text:string;source_ids:string[]}[]};
export type InterviewTopic={evidence_origin?:'source_excerpt'|'brave_summary';summary_id?:string|null;skill_id:string|null;name:string;category:string;interview_stage:string|null;assessment_type:string|null;difficulty:string;question_patterns:string[];independent_report_count:number;source_ids:string[]};
export type InterviewEvidence={source_ids:string[];text:string};
export type InterviewProcess={round_count:number|null;round_count_evidence?:InterviewEvidence|null;stages:{name:string;assessment_type:string|null;evidence?:InterviewEvidence}[]};
export type ResearchCoverage={platform:string;status:string;round?:number;useful_sources?:number|null;target_sources?:number|null;limit_reached?:boolean};
export type ResearchView={status:string;research:{_id:string;version:number;intelligence?:{categories:Partial<Record<IntelligenceCategory,IntelligenceResult>>};process?:InterviewProcess;summaries?:InterviewSummary[];skills:InterviewTopic[];sources:ResearchSource[];last_researched_at:string;research_status:string}|null;context:{role:string;field:string;company:string|null;location:string|null;seniority_level:string|null};stale:boolean;reused:boolean;historical:boolean;general:boolean;note:string;history?:string[]};

export type CareerWorkspace={activities?:string[];session_id:string|null;revision:number;kind:'jd'|'exploration'|null;phase:string;current:CurrentGoal;research_id:string|null;research_version:number|null;coverage:ResearchCoverage[];edit_question?:string|null;error_code?:string|null;error:string|null;limit_scope?:'user'|'provider'|null;provider?:string|null;retry_after:number|null;expires_at:string|null;exploration_id:string|null};

export type AssessmentStatus={status:'no_cv'|'not_evaluated'|'evaluated'|'unavailable';cv_uploaded:boolean|null;skills_evaluated:boolean|null};

export type IntelligenceCategory='interview_intelligence'|'internship_insights'|'career_progression'|'conversion_outcomes'|'company_intelligence';
export type IntelligenceFinding={finding_id:string;field:string;value:string;confidence:'high'|'medium'|'low'|'insufficient_evidence';evidence_type:'official'|'candidate_reported'|'third_party'|'inferred';source_ids:string[];quotes?:string[];scope:string;conflict_group:string|null;last_verified_at:string};
export type ResearchOutcome='findings_found'|'no_relevant_sources'|'information_not_found'|'validation_failed'|'provider_failed';
export type IntelligenceResult={source_ids?:string[];outcome?:ResearchOutcome|null;status:'pending'|'running'|'completed'|'partial'|'failed'|'not_applicable';findings:IntelligenceFinding[];missing_fields:string[];warnings:string[];error_code:string|null;researched_at:string|null;expires_at:string|null;searches:number;model_calls:number;latency_ms:number;estimated_cost_usd:number|null};
export type IntelligenceSummary={overview_refs:string[];key_takeaway_refs:string[];consideration_refs:string[]};
export type OpportunityAvailabilityIssue='research_disabled'|'reasoning_disabled'|'gemini_not_configured'|'brave_not_configured'|'brave_llm_context_required';
export type OpportunityView={available:boolean;availability_issues?:OpportunityAvailabilityIssue[];job_id:string|null;career_target_id:string;status:'pending'|'running'|'partial'|'completed'|'failed';finished?:boolean;categories:Partial<Record<IntelligenceCategory,IntelligenceResult>>;sources?:ResearchSource[];summary?:IntelligenceSummary;research_id?:string|null;research_version?:number|null;updated_at?:string|null;error_code:string|null;retry_after?:number|null};

export type WorkspaceProgress=Pick<CareerWorkspace,'session_id'|'phase'|'revision'|'activities'|'error'|'error_code'|'retry_after'|'limit_scope'|'provider'|'research_id'>&{goal_id:string|null;selection_version:number;result_version:string|null};
export async function refreshWorkspace(previous:CareerWorkspace,token:string,signal:AbortSignal):Promise<CareerWorkspace>{
 const progress=await careerApi<WorkspaceProgress>('/workspace/progress',token,{signal});
 if(progress.session_id!==previous.session_id||progress.goal_id!==previous.current.goal?._id||progress.revision!==previous.current.goal?.version||progress.selection_version!==previous.current.selection_version||progress.research_id!==previous.research_id)
  return careerApi<CareerWorkspace>('/workspace',token,{signal});
 return {...previous,...progress};
}
