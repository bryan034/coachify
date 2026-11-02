import type {ReviewFact} from './types';

export function ReviewEvidence({facts = []}: {facts?: ReviewFact[]}) {
 if (!facts.length) return null;
 return <dl className="cv-review-evidence">{facts.map(fact=><div key={`${fact.field}:${fact.skill_name??''}`}>
  <dt>{fact.skill_name ? `${fact.skill_name} · ` : ''}{fact.field.replaceAll('_',' ')}</dt>
  <dd><p>{fact.value ?? fact.status.replaceAll('_',' ')}{fact.value&&fact.status!=='supported'?` · ${fact.status}`:''}</p>
   {fact.evidence.map((ref,index)=><blockquote key={`${ref.source_id}:${index}`}>{ref.quote}</blockquote>)}
  </dd>
 </div>)}</dl>;
}
