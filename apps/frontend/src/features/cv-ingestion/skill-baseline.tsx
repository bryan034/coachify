import type {SkillEstimate} from './types';

export function SkillBaseline({estimates = []}: {estimates?: SkillEstimate[]}) {
 const visible = estimates.filter(estimate => estimate.level !== 'insufficient_evidence');
 if (!visible.length) return null;
 return <section aria-label="Baseline skill estimates">
  <h4>Baseline skill estimates</h4>
  <p className="small">Based on your CV and review answers; practical competence has not been tested.</p>
  <dl>{visible.map(estimate=><div key={estimate.skill_name}>
   <dt><strong>{estimate.skill_name}</strong> · {estimate.level.replaceAll('_',' ')}</dt>
   <dd className="small">{estimate.explanation}</dd>
  </div>)}</dl>
 </section>;
}
