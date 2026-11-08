import type {ReviewFact} from './types';

export function ReviewEvidence({facts = []}: {facts?: ReviewFact[]}) {
 if (!facts.length) return null;
 return <dl className="cv-review-evidence">{facts.map(fact=><div key={JSON.stringify(fact)}>
  <dt>{fact.skill_name ? `${fact.skill_name} · ` : ''}{fact.field.replaceAll('_',' ')}</dt>
  <dd><p>{fact.value ?? fact.status.replaceAll('_',' ')}{fact.value&&fact.status!=='supported'?` · ${fact.status}`:''}</p>
   {fact.attribution&&fact.attribution!=='unknown'&&<span className="pill n">{({personal:'Personal contribution',shared:'Shared contribution',team:'Team contribution',observed:'Observed work',denied:'Not personally performed'} as const)[fact.attribution]}</span>}
   {fact.evidence.map((ref,index)=><blockquote key={`${ref.source_id}:${index}`}>{ref.quote}</blockquote>)}
  </dd>
 </div>)}</dl>;
}
