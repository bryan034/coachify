import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TaskPlanner, skillsFor } from './task-planner';
import { review, roadmap } from '../../../tests/fixtures/roadmap-workspace';

describe('session skill labels', () => {
 it('honours one projected link and never falls back for unlinked or ambiguous sessions', () => {
  const plan = roadmap();
  const session = plan.assignments[0];
  expect(skillsFor({ ...session, skill_gap_ids: ['docker'] }, plan)).toEqual(['Docker']);
  expect(skillsFor({ ...session, skill_gap_ids: [] }, plan)).toEqual([]);
  expect(skillsFor({ ...session, skill_gap_ids: ['python', 'docker'] }, plan)).toEqual([]);
  expect(skillsFor({ ...session, skill_gap_ids: ['missing'] }, plan)).toEqual([]);
 });

 it('retains only an unambiguous legacy gap or milestone fallback', () => {
  const plan = roadmap();
  const session = plan.assignments[0];
  expect(skillsFor(session, plan)).toEqual(['Python']);
  expect(skillsFor({ ...session, gap_id: 'docker', skill_gap_ids: null }, plan)).toEqual(['Docker']);
  const ambiguous = roadmap({ milestones: [{ ...plan.milestones[0], gap_ids: ['python', 'docker'] }] });
  expect(skillsFor(session, ambiguous)).toEqual([]);
 });

 it('does not show a misleading skill tag when the task was explicitly unlinked', () => {
  const base = roadmap();
  const plan = roadmap({ assignments: [{ ...base.assignments[0], gap_id: null, skill_gap_ids: [] }] });
  render(<TaskPlanner plan={plan} review={review(plan)} frozen={false} complete={null} reopen={null} />);
  const list = screen.getByRole('region', { name: 'To-do list' });
  expect(within(list).getByText('Write one tested Python endpoint.')).toBeVisible();
  expect(within(list).queryByText('Python')).not.toBeInTheDocument();
  expect(within(list).getByText('Build a Python API')).toBeVisible();
 });
});

describe('session notes', () => {
 it('opens saved notes on the active roadmap and never offers them on a preview', () => {
  const base = roadmap();
  const notes = { blocks: [{ type: 'paragraph' as const, runs: [{ text: 'Followed the testing guide.' }] }] };
  const plan = roadmap({ assignments: [{ ...base.assignments[0], task_id: 'task-1' }], editable_tasks: [{ id: 'task-1', notes }] });
  const { unmount } = render(<TaskPlanner plan={plan} review={review(plan)} frozen={false} complete={null} reopen={null} saveNotes={async () => true} />);
  expect(screen.getByText('Notes')).toBeVisible();
  expect(screen.getByRole('textbox', { name: `Notes for ${plan.assignments[0].task}` })).toHaveTextContent('Followed the testing guide.');
  unmount();
  render(<TaskPlanner plan={plan} review={review(plan)} frozen={false} complete={null} reopen={null} saveNotes={null} />);
  expect(screen.queryByText('Notes')).not.toBeInTheDocument();
 });
});
