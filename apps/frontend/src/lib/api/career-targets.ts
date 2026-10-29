import { ApiError } from './profile';
import type { CareerTarget, CreateTargetInput, TargetCondition, TargetList, TargetSelection, TargetSkill } from '@/features/career/target-types';

type Guard<T> = (value: unknown) => value is T;
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string';
const nullableText = (value: unknown) => value === null || text(value);
const revision = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const list = <T>(value: unknown, guard: Guard<T>, max = 1000): value is T[] => Array.isArray(value) && value.length <= max && value.every(guard);
const date = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));
const source = (value: unknown) => value === 'user_reviewed_jd' || value === 'user_guidance';
const boundedText = (value: unknown, max: number, min = 1): value is string => text(value) && Array.from(value).length >= min && Array.from(value).length <= max && Boolean(value.trim());
const itemKind = (value: unknown): value is TargetCondition['item_kinds'][number] => value === 'education' || value === 'experience' || value === 'project' || value === 'skill';
const condition: Guard<TargetCondition> = (value): value is TargetCondition => record(value) && boundedText(value.id,100) && (value.kind === 'qualification' || value.kind === 'date') && boundedText(value.label,200) && boundedText(value.description,500) && list(value.item_kinds,itemKind,4) && value.item_kinds.length > 0 && new Set(value.item_kinds).size === value.item_kinds.length && list(value.match_terms,(term): term is string => boundedText(term,120,2),5) && value.match_terms.length > 0 && (value.evidence === null || boundedText(value.evidence,500)) && source(value.origin);
const skill: Guard<TargetSkill> = (value): value is TargetSkill => record(value) && text(value.skill_id) && text(value.name) && text(value.category) && text(value.priority) && nullableText(value.required_proficiency) && (value.required_experience_months === null || revision(value.required_experience_months)) && nullableText(value.context) && nullableText(value.evidence) && source(value.origin) && list(value.source_urls,text,20);
const target: Guard<CareerTarget> = (value): value is CareerTarget => record(value) && text(value.id) && text(value.user_id) && ['specific_job','career_exploration'].includes(String(value.target_type)) && text(value.role) && text(value.field) && ['company','location','seniority_level','job_url'].every(key=>nullableText(value[key])) && list(value.interests,text) && list(value.preferences,text) && list(value.skills,skill,40) && (value.conditions === undefined || list(value.conditions,condition,20)) && source(value.requirements_source) && text(value.generation_version) && ['draft','confirmed'].includes(String(value.status)) && revision(value.version) && value.version > 0 && date(value.created_at) && date(value.updated_at) && (value.confirmed_at === null || date(value.confirmed_at));
const selection: Guard<TargetSelection> = (value): value is TargetSelection => record(value) && nullableText(value.career_target_id) && (value.career_target_version === null || revision(value.career_target_version)) && revision(value.version);
async function request<T>(path: string, token: string, signal: AbortSignal, guard: Guard<T>, body?: unknown, method='POST'): Promise<T> {
 const response=await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1'}/career/targets${path}`,{method:body===undefined?'GET':method,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.any([signal,AbortSignal.timeout(30_000)]),cache:'no-store',headers:{Authorization:`Bearer ${token}`,...(body===undefined?{}:{'Content-Type':'application/json'})}});
 const value:unknown=await response.json().catch(()=>null);
 if(!response.ok){if(response.status===401)window.dispatchEvent(new CustomEvent('coachify:expired',{detail:token}));const detail=record(value)?value.detail:null;throw new ApiError(text(detail)?detail:record(detail)&&text(detail.message)?detail.message:response.status===409?'The target or selection changed. Refresh saved targets, review the current choice and retry.':response.status===422?'Check the target fields and exact source excerpts. Your draft is still here.':'Saved career targets are unavailable. Your input is retained; retry when the service is available.',response.status);}
 if(!guard(value))throw new Error('Coachify returned incomplete target information. Refresh saved targets before continuing.');
 return value;
}
export const targetApi={
 list:(token:string,signal:AbortSignal,cursor?:string)=>request(cursor?`?cursor=${encodeURIComponent(cursor)}`:'',token,signal,(value):value is TargetList=>record(value)&&list(value.targets,target,20)&&selection(value.selection)&&(value.next_cursor===null||(text(value.next_cursor)&&value.next_cursor.length>0&&value.next_cursor.length<=512))&&(value.selected_target===null?value.selection.career_target_id===null&&value.selection.career_target_version===null:target(value.selected_target)&&value.selected_target.status==='confirmed'&&value.selected_target.id===value.selection.career_target_id&&value.selected_target.version===value.selection.career_target_version)),
 create:(body:CreateTargetInput,token:string,signal:AbortSignal)=>request('',token,signal,target,body),
 confirm:(id:string,body:{expected_version:number;mutation_id:string},token:string,signal:AbortSignal)=>request(`/${encodeURIComponent(id)}/confirm`,token,signal,target,body),
 select:(body:{expected_version:number;mutation_id:string;career_target_id:string;career_target_version:number},token:string,signal:AbortSignal)=>request('/selection',token,signal,selection,body,'PUT'),
};
