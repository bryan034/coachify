import {render, screen} from '@testing-library/react';
import {expect, it} from 'vitest';
import {SkillBaseline} from './skill-baseline';

it('shows supported baselines and hides insufficient-evidence diagnostics and IDs', () => {
 render(<SkillBaseline estimates={[
  {item_id:'private-item',skill_name:'Python',level:'guided_application',explanation:'Personal application with guidance.',evidence_refs:['private-evidence']},
  {item_id:'private-item',skill_name:'SQL',level:'insufficient_evidence',explanation:'Application depth remains unknown.',evidence_refs:['private-evidence']},
 ]}/>);
 expect(screen.getByRole('region',{name:'Baseline skill estimates'})).toBeVisible();
 expect(screen.getByText('Python')).toBeVisible();
 expect(screen.getByText(/guided application/)).toBeVisible();
 expect(screen.queryByText('SQL')).not.toBeInTheDocument();
 expect(screen.queryByText(/insufficient evidence|Application depth remains unknown/)).not.toBeInTheDocument();
 expect(screen.queryByText(/private-evidence|private-item/)).not.toBeInTheDocument();
});


it('renders no baseline section when all estimates are internal diagnostics', () => {
 render(<SkillBaseline estimates={[
  {item_id:'private-item',skill_name:'SQL',level:'insufficient_evidence',explanation:'Application depth remains unknown.',evidence_refs:['private-evidence']},
 ]}/>);
 expect(screen.queryByRole('region',{name:'Baseline skill estimates'})).not.toBeInTheDocument();
 expect(screen.queryByText('SQL')).not.toBeInTheDocument();
});
