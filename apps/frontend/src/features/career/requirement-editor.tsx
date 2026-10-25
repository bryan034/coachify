"use client";
import {useState,type FormEvent} from 'react';
import type {JDExtraction,ReviewSkill,ReviewCondition,SavedReview} from '@/lib/api/career';
const metadata=['role','field','company','location','seniority_level','job_url'] as const;
const labels={role:'Role',field:'Field',company:'Company',location:'Location',seniority_level:'Seniority',job_url:'Job URL'};
const copy=<T,>(v:T):T=>structuredClone(v);
export function RequirementEditor({review,busy,onSave,onCancel}:{review:SavedReview;busy:boolean;onSave:(content:JDExtraction,ack:boolean)=>void;onCancel:()=>void}){
 const [content,setContent]=useState(()=>copy(review.extraction));const [ack,setAck]=useState(false);
 function skill(index:number,changes:Partial<ReviewSkill>){setContent(p=>({...p,skills:p.skills.map((s,i)=>i===index?{...s,...changes}:s)}));}
 function condition(index:number,changes:Partial<ReviewCondition>){setContent(p=>({...p,non_skill_requirements:p.non_skill_requirements.map((r,i)=>i===index?{...r,...changes}:r)}));}
 function moveSkill(index:number){setContent(p=>{const s=p.skills[index];return {...p,skills:p.skills.filter((_,i)=>i!==index),non_skill_requirements:[...p.non_skill_requirements,{requirement_id:s.item_id||crypto.randomUUID(),description:[s.name,s.context,s.required_proficiency?`Required proficiency: ${s.required_proficiency}`:null].filter(Boolean).join('. '),category:'other',priority:s.priority,evidence:s.evidence||'',origin:s.origin,group_id:s.group_id||null,group_operator:s.group_operator||'all',minimum_months:s.required_experience_months??null}]};});}
 function moveCondition(index:number){setContent(p=>{const r=p.non_skill_requirements[index];return {...p,non_skill_requirements:p.non_skill_requirements.filter((_,i)=>i!==index),skills:[...p.skills,{item_id:r.requirement_id,name:r.description.length<=160?r.description:'',category:'Technical',priority:r.priority as ReviewSkill['priority'],origin:r.origin||'employer',evidence:r.evidence,context:[r.description,r.minimum_months!=null||r.maximum_months!=null?`Experience: ${r.minimum_months??'unspecified'}–${r.maximum_months??'unspecified'} months`:null,r.completion_status&&r.completion_status!=='unspecified'?`Completion: ${r.completion_status}`:null].filter(Boolean).join('. '),group_id:r.group_id,group_operator:r.group_operator}]};});}
 function submit(e:FormEvent){e.preventDefault();onSave(content,ack);}
 const changed=metadata.filter(k=>k!=='job_url').some(k=>content[k]!==review.extraction[k]);
 return <form className="requirement-editor" onSubmit={submit} aria-label="Edit career goal review">
  <fieldset disabled={busy}><legend>Role and context</legend>
   {metadata.map(key=><label key={key}>{labels[key]}<input aria-label={labels[key]} aria-describedby={`review-${key}-origin`} type={key==='job_url'?'url':'text'} maxLength={key==='job_url'?2048:160} value={content[key]||''} onChange={e=>setContent(p=>({...p,[key]:e.target.value.trim()?e.target.value:null}))}/><span className="small" id={`review-${key}-origin`}>{review.metadata_origins[key]==='user'?'Previously edited by you':'From extraction'}</span></label>)}
   <button className="btn ghost sm" type="button" onClick={()=>setContent(p=>({...p,...Object.fromEntries(metadata.map(k=>[k,review.baseline[k]]))}))}>Reset role details</button>
  </fieldset>
  <fieldset disabled={busy}><legend>Skills</legend>
   {content.skills.map((s,i)=><article className="requirement-item" key={s.item_id||i}><h3>Skill {i+1}</h3>
    <label>Skill name<input required maxLength={160} value={s.name} onChange={e=>skill(i,{name:e.target.value})}/></label>
    <label>Skill category<input required maxLength={160} value={s.category} onChange={e=>skill(i,{category:e.target.value})}/></label>
    <label>Priority<select value={s.priority} onChange={e=>skill(i,{priority:e.target.value as ReviewSkill['priority']})}><option value="required">Required</option><option value="preferred">Preferred</option><option value="suggested">Suggested</option></select></label>
    <label>Source<select value={s.origin} onChange={e=>skill(i,{origin:e.target.value as ReviewSkill['origin'],...(e.target.value==='generated_guidance'?{priority:'suggested',evidence:null}:{})})}><option value="employer">Job description</option><option value="user_declaration">Added by me</option><option value="generated_guidance">Suggested guidance</option></select></label>
    <label>Required proficiency<select value={s.required_proficiency||''} onChange={e=>skill(i,{required_proficiency:e.target.value||null})}><option value="">Not specified</option>{['beginner','intermediate','advanced','expert'].map(v=><option key={v}>{v}</option>)}</select></label>
    <label>Required experience (months)<input type="number" min={0} max={1200} step={1} value={s.required_experience_months??''} onChange={e=>skill(i,{required_experience_months:e.target.value===''?null:Number(e.target.value)})}/></label>
    <label>Scope and conditions<textarea maxLength={600} value={s.context||''} onChange={e=>skill(i,{context:e.target.value||null})}/></label>
    <label>Supporting context<textarea maxLength={600} disabled={s.origin==='generated_guidance'} value={s.evidence||''} onChange={e=>skill(i,{evidence:e.target.value||null})}/></label>
    <label>Requirement group<input maxLength={160} value={s.group_id||''} onChange={e=>skill(i,{group_id:e.target.value||null})}/></label>
    <label>Group rule<select value={s.group_operator||'all'} onChange={e=>skill(i,{group_operator:e.target.value as 'all'|'any'})}><option value="all">All items (AND)</option><option value="any">Any item (OR)</option></select></label>
    <div className="row"><button className="btn ghost sm" type="button" onClick={()=>moveSkill(i)}>Move {s.name||'skill'} to conditions</button><button className="btn ghost sm" type="button" onClick={()=>setContent(p=>({...p,skills:p.skills.filter((_,n)=>n!==i)}))}>Remove {s.name||'skill'}</button></div>
   </article>)}
   <button type="button" className="btn ghost sm" onClick={()=>setContent(p=>({...p,skills:[...p.skills,{item_id:crypto.randomUUID(),name:'',category:'Technical',priority:'suggested',origin:'user_declaration',evidence:null}]}))}>Add skill</button>
  </fieldset>
  <fieldset disabled={busy}><legend>Qualifications and other requirements</legend><p className="small">Keep alternatives in the same named group. These conditions describe the role; they do not determine your eligibility.</p>
   {content.non_skill_requirements.map((r,i)=><article className="requirement-item" key={r.requirement_id}><h3>Condition {i+1}</h3>
    <label>Condition<textarea required maxLength={600} value={r.description} onChange={e=>condition(i,{description:e.target.value})}/></label>
    <label>Condition category<select value={r.category} onChange={e=>condition(i,{category:e.target.value})}>{['qualification','experience','eligibility','location','work_condition','other'].map(v=><option key={v} value={v}>{v.replace('_',' ')}</option>)}</select></label>
    <label>Condition priority<select value={r.priority} onChange={e=>condition(i,{priority:e.target.value})}>{['required','preferred','suggested'].map(v=><option key={v}>{v}</option>)}</select></label>
    <label>Condition source<select value={r.origin||'employer'} onChange={e=>condition(i,{origin:e.target.value as ReviewCondition['origin'],...(e.target.value==='generated_guidance'?{priority:'suggested'}:{})})}><option value="employer">Job description</option><option value="user_declaration">Added by me</option><option value="generated_guidance">Suggested guidance</option></select></label>
    <label>Condition supporting context<textarea required maxLength={600} value={r.evidence} onChange={e=>condition(i,{evidence:e.target.value})}/></label>
    <label>Minimum experience (months)<input type="number" min={0} max={1200} step={1} value={r.minimum_months??''} onChange={e=>condition(i,{minimum_months:e.target.value===''?null:Number(e.target.value)})}/></label>
    <label>Maximum experience (months)<input type="number" min={0} max={1200} step={1} value={r.maximum_months??''} onChange={e=>condition(i,{maximum_months:e.target.value===''?null:Number(e.target.value)})}/></label>
    <label>Completion requirement<select value={r.completion_status||'unspecified'} onChange={e=>condition(i,{completion_status:e.target.value as ReviewCondition['completion_status']})}><option value="unspecified">Not specified</option><option value="completed">Completed</option><option value="in_progress">In progress accepted</option></select></label>
    <label>Condition group<input maxLength={160} value={r.group_id||''} onChange={e=>condition(i,{group_id:e.target.value||null})}/></label>
    <label>Condition group rule<select value={r.group_operator} onChange={e=>condition(i,{group_operator:e.target.value as 'all'|'any'})}><option value="all">All items (AND)</option><option value="any">Any item (OR)</option></select></label>
    <div className="row"><button type="button" className="btn ghost sm" onClick={()=>moveCondition(i)}>Move condition {i+1} to skills</button><button type="button" className="btn ghost sm" onClick={()=>setContent(p=>({...p,non_skill_requirements:p.non_skill_requirements.filter((_,n)=>n!==i)}))}>Remove condition {i+1}</button></div>
   </article>)}
   <button type="button" className="btn ghost sm" onClick={()=>setContent(p=>({...p,non_skill_requirements:[...p.non_skill_requirements,{requirement_id:crypto.randomUUID(),description:'',category:'other',priority:'required',origin:'user_declaration',evidence:'',group_id:null,group_operator:'all'}]}))}>Add condition</button>
  </fieldset>
  {(changed||review.requirements_need_review)&&<label className="review-confirm"><input type="checkbox" checked={ack} disabled={busy} onChange={e=>setAck(e.target.checked)}/>I have reviewed the requirements for the updated role and context.</label>}
  <div className="row"><button className="btn pri" disabled={busy}>Save review</button><button type="button" className="btn ghost" disabled={busy} onClick={onCancel}>Cancel edits</button><button type="button" className="btn ghost" disabled={busy} onClick={()=>{setContent(copy(review.baseline));setAck(false);}}>{review.target_type==='career_exploration'?'Reset all to starting values':'Reset all to extraction'}</button></div>
 </form>;
}
