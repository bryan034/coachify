/** Validate the fields used by the JD workspace before they reach React.
 * Additive server fields are allowed; invalid nested records are never coerced.
 * Canonical schemas remain in contracts/api and the Career Pydantic models.
 */
type Check=(value:unknown)=>boolean;
type RecordValue=Record<string,unknown>;
export const record=(value:unknown):value is RecordValue=>typeof value==='object'&&value!==null&&!Array.isArray(value);
const text:Check=value=>typeof value==='string';
const nonempty:Check=value=>typeof value==='string'&&value.trim().length>0;
const boolean:Check=value=>typeof value==='boolean';
const integer:Check=value=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;
const positive:Check=value=>integer(value)&&Number(value)>0;
const nullable=(check:Check):Check=>value=>value===null||check(value);
const optional=(check:Check):Check=>value=>value===undefined||check(value);
const oneOf=(...values:unknown[]):Check=>value=>values.includes(value);
const array=(check:Check,max=1000):Check=>value=>Array.isArray(value)&&value.length<=max&&value.every(check);
const strings=array(text);
const shape=(fields:Record<string,Check>):Check=>value=>record(value)&&Object.entries(fields).every(([key,check])=>check(value[key]));
const priority=oneOf('required','preferred','unspecified','conflicting','suggested');
const origin=oneOf('employer','generated_guidance','user_declaration','market_research');
const group=oneOf('all','any');
const skill=shape({name:nonempty,category:nonempty,priority,origin,
 item_id:optional(nullable(text)),skill_id:optional(nullable(text)),group_id:optional(nullable(text)),group_operator:optional(group),
 evidence:optional(nullable(text)),context:optional(nullable(text)),priority_evidence:optional(nullable(text)),priority_origin:optional(nullable(origin)),
 source_urls:optional(strings),required_proficiency:optional(nullable(oneOf('beginner','intermediate','advanced','expert'))),
 required_experience_months:optional(nullable(integer)),
});
const condition=shape({requirement_id:nonempty,category:oneOf('qualification','experience','eligibility','location','work_condition','other'),
 description:nonempty,priority,evidence:text,group_id:nullable(text),group_operator:group,
 origin:optional(origin),source_urls:optional(strings),minimum_months:optional(nullable(integer)),maximum_months:optional(nullable(integer)),
 completion_status:optional(oneOf('completed','in_progress','unspecified')),
});
const jobDate=shape({kind:oneOf('application_deadline','interview','job_start'),text:nonempty,evidence:nonempty,date:nullable(text)});
const goal=shape({_id:nonempty,version:positive,role:nonempty,field:nonempty,target_type:oneOf('specific_job','career_exploration'),
 company:nullable(text),location:nullable(text),seniority_level:nullable(text),job_url:nullable(text),
 employment_type:optional(oneOf('internship','full_time','part_time','contract','unknown')),
 skills:array(skill,200),non_skill_requirements:optional(array(condition,100)),responsibilities:optional(array(text,20)),
 job_dates:optional(array(jobDate,8)),summary:optional(nullable(text)),interests:strings,preferences:strings,
 readiness:oneOf('pending','ready'),requirements_need_review:optional(boolean),
 exploration_draft_id:nullable(text),exploration_draft_version:nullable(positive),
});
const current=shape({goal:nullable(goal),selection_version:integer,dependent_results_need_review:boolean});
const phase=oneOf('empty','exploring','research_pending','researching','waiting_quota','research_failed','ready','expired');
const retryAfter=optional(nullable(integer));
const errorFields={error:nullable(text),error_code:optional(nullable(text)),retry_after:retryAfter,
 limit_scope:optional(nullable(oneOf('user','provider'))),provider:optional(nullable(text))};
const coverage=shape({platform:text,status:text,useful_sources:optional(nullable(integer)),target_sources:optional(nullable(integer))});
const workspace=shape({session_id:nullable(text),revision:integer,kind:nullable(oneOf('jd','exploration')),phase,current,
 research_id:nullable(text),research_version:nullable(positive),coverage:array(coverage,6),activities:optional(strings),
 expires_at:nullable(text),exploration_id:nullable(text),edit_question:optional(nullable(text)),...errorFields});
const progress=shape({session_id:nullable(text),revision:integer,goal_id:nullable(text),selection_version:integer,phase,
 research_id:nullable(text),activities:strings,result_version:nullable(text),edit_question:optional(nullable(text)),...errorFields});
const operation=shape({operation_id:value=>typeof value==='string'&&/^[0-9a-f]{32}$/.test(value),
 status:oneOf('running','repairing','waiting_quota','succeeded'),activities:optional(strings),retry_after:retryAfter,
 result:nullable(value=>record(value)),
});
const reply=shape({reply:nonempty});
const chat:Check=value=>reply(value)&&record(value)&&
 (value.workspace===undefined||value.workspace===null||workspace(value.workspace))&&
 (value.proposed_skills===undefined||value.proposed_skills===null||array(skill,60)(value.proposed_skills));
const finding=shape({finding_id:nonempty,field:nonempty,value:nonempty,confidence:oneOf('high','medium','low','insufficient_evidence'),
 evidence_type:oneOf('official','candidate_reported','third_party','inferred'),source_ids:strings,scope:text,conflict_group:nullable(text),last_verified_at:text});
const category=shape({status:oneOf('pending','running','completed','partial','failed','not_applicable'),findings:array(finding,20),
 missing_fields:strings,warnings:strings,error_code:nullable(text)});
const categories:Check=value=>record(value)&&Object.entries(value).every(([key,item])=>
 ['interview_intelligence','internship_insights','career_progression','conversion_outcomes','company_intelligence'].includes(key)&&category(item));
const source=shape({source_id:nonempty,platform:nonempty,url:nonempty,title:nullable(text)});
const researchProgress=shape({status:text,finished:boolean,result_version:nullable(text),categories:value=>record(value)&&
 Object.values(value).every(shape({status:text,error_code:nullable(text)}))});
const evidence=shape({finding_id:nonempty,quotes:strings,sources:array(source,30)});
const research=shape({available:boolean,job_id:nullable(text),career_target_id:nonempty,status:oneOf('pending','running','partial','completed','failed'),
 finished:optional(boolean),research_id:optional(nullable(text)),categories,sources:optional(array(source,30)),error_code:nullable(text),
 summary:optional(shape({overview_refs:strings,key_takeaway_refs:strings,consideration_refs:strings})),retry_after:retryAfter});

export const careerPreview=shape({kind:oneOf('url','document'),text:value=>nonempty(value)&&Array.from(value as string).length<=20_000,
 source_name:nonempty,source_url:optional(nullable(text)),notices:strings});

/** Operation envelopes are validated here; their completed result is validated
 * again against the originating endpoint by careerOperation. */
export function validCareerResponse(path:string,value:unknown):boolean{
 const route=path.split('?')[0];
 if(route.startsWith('/workspace/operations/'))return operation(value);
 const asyncRoute=['/workspace/jd','/workspace/summary','/workspace/messages','/workspace/direction'].includes(route);
 if(asyncRoute&&record(value)&&'operation_id' in value)return operation(value);
 if(['/workspace','/workspace/jd','/workspace/retry','/workspace/direction','/workspace/review'].includes(route))return workspace(value);
 if(route==='/workspace/progress')return progress(value);
 if(route==='/workspace/summary')return reply(value);
 if(route==='/workspace/messages')return chat(value);
 if(route==='/goals/current')return current(value);
 if(/^\/goals\/[^/]+\/opportunity-research$/.test(route))return research(value);
 if(/^\/goals\/[^/]+\/opportunity-research\/progress$/.test(route))return researchProgress(value);
 if(/^\/goals\/[^/]+\/opportunity-research\/findings\/[^/]+\/evidence$/.test(route))return evidence(value);
 if(route==='/explorations/cv/document')return careerPreview(value);
 return true;
}
