import type { CvItemKind, TargetCondition, TargetConditionInput, TargetType } from './target-types';

export type ConditionDraft = { id: string; kind: TargetConditionInput['kind']; label: string; description: string; itemKind: CvItemKind; terms: string; evidence: string };
export const emptyCondition = (): ConditionDraft => ({ id: crypto.randomUUID(), kind: 'qualification', label: '', description: '', itemKind: 'education', terms: '', evidence: '' });
export const conditionTerms = (value: string) => value.split(',').map(term => term.trim()).filter(Boolean);
const normalized = (value: string) => value.normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase();
export function conditionValid(condition: ConditionDraft, type: TargetType, source: string) {
 const terms = conditionTerms(condition.terms);
 const content = normalized([condition.label, condition.description, condition.evidence].join(' '));
 return Boolean(condition.label.trim() && condition.description.trim() && terms.length > 0 && terms.length <= 5
  && terms.every(term => Array.from(term).length >= 2 && Array.from(term).length <= 120 && content.includes(normalized(term)))
  && new Set(terms.map(normalized)).size === terms.length
  && (type === 'career_exploration' || (condition.evidence.trim() && source.includes(condition.evidence.trim()) && terms.every(term => normalized(condition.evidence).includes(normalized(term))))));
}

export function ConditionFields({conditions,type,source,busy,onChange}:{conditions:ConditionDraft[];type:TargetType;source:string;busy:boolean;onChange:(conditions:ConditionDraft[])=>void}) {
 const change = (id:string, patch:Partial<ConditionDraft>) => onChange(conditions.map(condition => condition.id === id ? {...condition,...patch} : condition));
 return <section aria-label="Qualification and date conditions" className="target-skills">
  <h3>Qualification and date conditions</h3>
  <p className="small">Add these only when they matter to this target. They guide clarification and do not establish eligibility or a skill gap.</p>
  {conditions.map((condition,index)=><fieldset key={condition.id}>
   <legend>Condition {index+1}</legend>
   <label>Condition type {index+1}<select value={condition.kind} disabled={busy} onChange={event=>change(condition.id,{kind:event.target.value as ConditionDraft['kind']})}><option value="qualification">Qualification</option><option value="date">Date or timing</option></select></label>
   <label>Condition name {index+1}<input value={condition.label} maxLength={200} required disabled={busy} onChange={event=>change(condition.id,{label:event.target.value})}/></label>
   <label>{type==='specific_job'?'Requirement':'Personal guidance'} {index+1}<textarea value={condition.description} rows={2} maxLength={500} required disabled={busy} onChange={event=>change(condition.id,{description:event.target.value})}/></label>
   <label>Relevant CV section {index+1}<select value={condition.itemKind} disabled={busy} onChange={event=>change(condition.id,{itemKind:event.target.value as CvItemKind})}><option value="education">Education</option><option value="experience">Work experience</option><option value="project">Projects</option><option value="skill">Skills</option></select></label>
   <label>Relevant subject phrases {index+1}<input value={condition.terms} maxLength={608} required disabled={busy} aria-describedby={`condition-subject-${condition.id}`} onChange={event=>change(condition.id,{terms:event.target.value})}/></label>
   <p className="small" id={`condition-subject-${condition.id}`}>Use up to five specific qualification or activity phrases, separated by commas, such as “Computer Science”. Each phrase must appear in this condition{type==='specific_job'?' and its JD excerpt':''}. Only matching CV records can receive a related question.</p>
   {type==='specific_job'&&<label>Condition JD excerpt {index+1}<textarea aria-label={`Condition JD excerpt ${index+1}`} aria-describedby={`condition-evidence-${condition.id}`} value={condition.evidence} rows={3} maxLength={500} required disabled={busy} onChange={event=>change(condition.id,{evidence:event.target.value})} aria-invalid={Boolean(condition.evidence.trim())&&!source.includes(condition.evidence.trim())}/><span id={`condition-evidence-${condition.id}`} className="small">Copy the exact supporting wording, up to 500 characters.</span></label>}
   {Boolean(condition.label||condition.description||condition.terms||condition.evidence)&&!conditionValid(condition,type,source)&&<p className="small target-warning">Complete this condition and use specific subject phrases supported by its wording{type==='specific_job'?' and the exact JD excerpt':''}.</p>}
   <button type="button" className="btn ghost sm" disabled={busy} onClick={()=>onChange(conditions.filter(item=>item.id!==condition.id))}>Remove condition {index+1}</button>
  </fieldset>)}
  <div className="row"><button type="button" className="btn ghost sm" disabled={busy||conditions.length>=20} onClick={()=>onChange([...conditions,emptyCondition()])}>Add qualification or date condition</button><span className="small">{conditions.length} / 20 conditions</span></div>
 </section>;
}

export function ConditionSummary({conditions}:{conditions:TargetCondition[]}) {
 if(!conditions.length)return null;
 return <div aria-label="Saved qualification and date conditions"><h4>Qualification and date conditions</h4><ul>{conditions.map(condition=><li key={condition.id}>
  <strong>{condition.label}</strong><p className="small">{condition.kind==='date'?'Date or timing':'Qualification'} · {condition.origin==='user_guidance'?'Personal exploration guidance':'Requirement reviewed against the JD'}</p>
  <p>{condition.description}</p>{condition.evidence&&<blockquote>{condition.evidence}</blockquote>}
  <p className="small">Relevant CV subjects: {condition.match_terms.join(' · ')}. Clarification does not verify eligibility.</p>
 </li>)}</ul></div>;
}
