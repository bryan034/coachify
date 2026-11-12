import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ExtractedResults } from './extracted-results';
import { savedCv } from '../../../tests/fixtures/cv';
import type { CvDetail } from './types';

function reviewedCv(): CvDetail {
 const base = savedCv('cv-results');
 const project = base.items[0];
 const skill = (id: string, name: string, itemIds: string[]) => ({ ...base.skills[0], skill_id: id, name, item_ids: itemIds });
 return {
  ...base, display_name: 'Synthetic Resume',
  skill_groups: { python: 'Technical coding', excel: 'Business and finance', agentic: 'AI and ML' },
  skill_subgroups: { python: 'Languages' },
  items: [
   { ...project, skill_ids: ['python', 'excel'], start_date: '2026-06', end_date: '2026-08' },
   { ...project, id: 'work-1', kind: 'experience', title: 'Analyst at Synthetic Co', description: 'Built models.', skill_ids: ['excel'], start_date: '2025', ongoing: true },
   { ...project, id: 'skipped-1', kind: 'project', title: 'Side project', description: 'Built an app.', skill_ids: ['react'] },
   { ...base.items[1], id: 'removed-skill', title: 'Tableau', removed: true },
  ],
  skills: [skill('python', 'Python', [project.id]), skill('excel', 'Excel', [project.id, 'work-1']), skill('agentic', 'Agentic AI', ['work-1']), skill('react', 'React', ['skipped-1'])],
  clarifications: [{ id: 'q1', item_id: 'skipped-1', status: 'skipped' } as CvDetail['clarifications'][number], { id: 'q2', item_id: project.id, status: 'answered' } as CvDetail['clarifications'][number]],
  review_summary: { answered_questions: 1, experiences: 3, skills_added: 1, skills_corrected: 1, skills_removed: 1, added_skill_ids: ['agentic'], skill_notes: { python: 'Level corrected: scripts, not production code.' } },
 };
}

describe('ExtractedResults', () => {
 it('summarises what elo read and what the review changed', () => {
  render(<ExtractedResults cv={reviewedCv()} onBack={vi.fn()} />);
  expect(screen.getByRole('heading', { name: 'Extracted results' })).toBeInTheDocument();
  expect(screen.getByText(/Synthetic Resume/)).toBeInTheDocument();
  expect(screen.getByText(/Your review added 1 and removed 1/)).toBeInTheDocument();
  expect(screen.getByText('1 question answered, 1 skipped')).toBeInTheDocument();
 });

 it('marks skills added, removed and from skipped topics, and explains the selected one', () => {
  render(<ExtractedResults cv={reviewedCv()} onBack={vi.fn()} />);
  const skills = screen.getByRole('region', { name: 'Skills by category' });
  expect(within(skills).getByRole('button', { name: '+ Agentic AI' })).toHaveClass('is-add');
  expect(within(skills).getByRole('button', { name: 'Tableau' })).toHaveClass('is-rem');
  expect(within(skills).getByRole('button', { name: 'React' })).toHaveClass('is-skip');
  const detail = screen.getByRole('complementary');
  expect(within(detail).getByRole('heading', { name: 'Python' })).toBeInTheDocument();
  expect(within(detail).getByText('Level corrected: scripts, not production code.')).toBeInTheDocument();
  expect(within(detail).getByText('Team dashboard')).toBeInTheDocument();
  fireEvent.click(within(skills).getByRole('button', { name: 'Tableau' }));
  expect(within(detail).getByRole('heading', { name: 'Tableau' })).toBeInTheDocument();
  expect(within(detail).getByText('Removed after your answers.')).toBeInTheDocument();
 });

 it('regroups skills by where they came from', () => {
  render(<ExtractedResults cv={reviewedCv()} onBack={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Where it came from' }));
  const skills = screen.getByRole('region', { name: 'Skills by where they came from' });
  expect(within(skills).getByText('Added in review', { selector: 'p' })).toBeInTheDocument();
  expect(within(skills).getByText('Not in your CV, from your answers')).toBeInTheDocument();
 });

 it('lists experiences with dates, wording and the skills found in each', () => {
  render(<ExtractedResults cv={reviewedCv()} onBack={vi.fn()} />);
  const section = screen.getByRole('region', { name: 'Experiences found in your CV' });
  expect(within(section).getByText('Jun 2026 to Aug 2026')).toBeInTheDocument();
  expect(within(section).getByText('2025 to now')).toBeInTheDocument();
  expect(within(section).getByText('Python, Excel')).toBeInTheDocument();
  expect(within(within(section).getByText('Side project').closest('details')!).getByText('Skipped')).toBeInTheDocument();
 });

 it('returns to the Skills Profile and offers no editing', () => {
  const back = vi.fn();
  render(<ExtractedResults cv={reviewedCv()} onBack={back} />);
  fireEvent.click(screen.getByRole('button', { name: 'Skills Profile' }));
  expect(back).toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: /Edit|Save/ })).toBeNull();
 });
});
