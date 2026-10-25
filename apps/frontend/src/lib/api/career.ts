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
export type SavedGoal = { _id:string; version:number; target_type:'specific_job'|'career_exploration';role:string;field:string;
 company:string|null;location:string|null;seniority_level:string|null;job_url:string|null;
 skills:{name:string;priority:string;origin:string}[];interests:string[];preferences:string[];readiness:'pending'|'ready';
 exploration_draft_id:string|null;exploration_draft_version:number|null };
export type CurrentGoal = {selection_version:number;goal:SavedGoal|null;dependent_results_need_review:boolean};
export type CareerContext = {cvs:{id:string;filename:string;status:string;version:number;extraction_version:string}[];cv_service_available:boolean;ai_available:boolean};
export async function careerApi<T>(path:string,token:string, options:RequestInit={}):Promise<T>{
 const response=await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1'}/career${path}`,{
  ...options,cache:'no-store',headers:{Authorization:`Bearer ${token}`,...(typeof options.body==='string'?{'Content-Type':'application/json'}:{}),...options.headers},
 });
 const body=await response.json().catch(()=>({}));
 if(!response.ok){
  if(response.status===401)window.dispatchEvent(new CustomEvent('coachify:expired',{detail:token}));
  throw new ApiError(typeof body.detail==='string'?body.detail:'Career Goal is unavailable. Please retry.',response.status);
 }
 return body as T;
}
export async function importExplorationCV(file:File,token:string,signal:AbortSignal):Promise<CareerPreview>{
 const body=new FormData();body.set('file',file);
 return careerApi<CareerPreview>('/explorations/cv/document',token,{method:'POST',body,signal});
}

export type ReviewSkill={name:string;category:string;priority:'required'|'preferred'|'suggested';required_proficiency?:string|null;required_experience_months?:number|null;context?:string|null;evidence?:string|null;origin:'employer'|'generated_guidance'|'user_declaration'};
export type JDExtraction={role:string|null;field:string|null;company:string|null;skills:ReviewSkill[]};
export type JDReview={extraction:JDExtraction;generation:unknown;turns:{message:string;reply:string}[];proposals:ReviewSkill[]|null};
