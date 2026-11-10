import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { newTask } from './add-task';
import { planCountdown } from './roadmap-planner';
import { TaskPlanner } from './task-planner';
import { review, roadmap } from '../../../tests/fixtures/roadmap-workspace';

describe('add a task', () => {
 it('links the chosen skill to its requirement and milestone, and schedules one slot', () => {
  expect(newTask(roadmap(), { title: '  Practise one timed problem ', date: '2030-01-09', start: '19:00', minutes: 30, gapId: 'python' })).toEqual({
   title: 'Practise one timed problem', instructions: 'Practise one timed problem', completion_outcome: 'You finished “Practise one timed problem”.',
   estimated_minutes: 30, requirement_refs: ['job:python'], prerequisites: [], milestone_key: 'm1',
   schedule: [{ date: '2030-01-09', start_time: '19:00', duration_minutes: 30 }],
  });
  expect(newTask(roadmap(), { title: 'Read', date: '2030-01-09', start: '08:00', minutes: 15, gapId: '' })).toMatchObject({ requirement_refs: [], milestone_key: null });
 });

 it('adds a task on the active roadmap from the preferred block for that day', async () => {
  const plan = roadmap(); const add = vi.fn(async () => true);
  render(<TaskPlanner plan={plan} review={review(plan)} frozen={false} complete={vi.fn()} reopen={vi.fn()} addTask={add} />);
  fireEvent.click(screen.getByRole('button', { name: /Add a task/ }));
  const form = screen.getByRole('form', { name: /New task for/ });
  expect(within(form).getByRole('button', { name: 'Add to roadmap' })).toBeDisabled();
  fireEvent.change(within(form).getByRole('textbox', { name: 'What would you like to do?' }), { target: { value: 'Mock coding problem' } });
  expect(within(form).getByRole('button', { name: 'Preferred · 7:00 pm' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(within(form).getByRole('button', { name: '30 minutes' }));
  fireEvent.click(within(form).getByRole('button', { name: 'Add to roadmap' }));
  await waitFor(() => expect(add).toHaveBeenCalledWith(expect.objectContaining({ title: 'Mock coding problem', schedule: [{ date: '2030-01-09', start_time: '19:00', duration_minutes: 30 }] })));
  await waitFor(() => expect(screen.queryByRole('form', { name: /New task for/ })).not.toBeInTheDocument());
 });

 it('keeps the draft when the save fails and never offers adding on a preview', async () => {
  const plan = roadmap(); const add = vi.fn(async () => false);
  const { rerender } = render(<TaskPlanner plan={plan} review={review(plan)} frozen={false} complete={vi.fn()} reopen={vi.fn()} addTask={add} />);
  fireEvent.click(screen.getByRole('button', { name: /Add a task/ }));
  fireEvent.change(screen.getByRole('textbox', { name: 'What would you like to do?' }), { target: { value: 'Mock coding problem' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add to roadmap' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('This task wasn’t added.');
  expect(screen.getByRole('textbox', { name: 'What would you like to do?' })).toHaveValue('Mock coding problem');
  rerender(<TaskPlanner plan={plan} review={review(plan)} frozen={false} complete={null} reopen={null} addTask={null} />);
  expect(screen.queryByRole('button', { name: /Add a task/ })).not.toBeInTheDocument();
 });
});

describe('roadmap countdown', () => {
 it('counts days to the target and the current planning week', () => {
  expect(planCountdown('2026-11-10', '2026-11-10', '2027-05-04')).toEqual({ days: '175 days', target: '2027-05-04', week: 1, weeks: 25 });
  expect(planCountdown('2026-11-16', '2026-11-16', '2027-05-04')).toMatchObject({ week: 1, weeks: 24 });
  expect(planCountdown('2026-11-24', '2026-11-10', '2027-05-04')).toMatchObject({ week: 3 });
  expect(planCountdown('2026-11-10', '2026-12-01', '2027-05-04')).toMatchObject({ week: null });
  expect(planCountdown('2027-05-05', '2026-11-10', '2027-05-04')).toBeNull();
  expect(planCountdown('2026-11-10', null, null)).toBeNull();
 });
});
