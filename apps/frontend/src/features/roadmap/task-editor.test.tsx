import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { TaskEditor, type EditableRoadmapTask } from './task-editor';
import { roadmap } from '../../../tests/fixtures/roadmap-workspace';

const base: EditableRoadmapTask = { id: 'task-1', title: 'Review arrays', instructions: 'Practice arrays.', completion_outcome: 'Save a solution.', estimated_minutes: 30, milestone_key: 'm1', status: 'not_started', schedule: [{ date: '2030-01-09', start_time: '18:00', duration_minutes: 30 }] };
const milestones = roadmap().milestones;

it('shows the title limit and creates an unscheduled task only when valid', async () => {
 const change = vi.fn().mockResolvedValue(true);
 render(<TaskEditor tasks={[]} milestones={milestones} frozen={false} change={change} />);
 fireEvent.click(screen.getByRole('button', { name: 'Add task' }));
 fireEvent.change(screen.getByLabelText('Title'), { target: { value: Array(20).fill('word').join(' ') } });
 fireEvent.change(screen.getByLabelText('Instructions'), { target: { value: 'Choose a problem.' } });
 fireEvent.change(screen.getByLabelText('Completion outcome'), { target: { value: 'Save a solution.' } });
 expect(screen.getByText(/20 of 19 words/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button', { name: 'Save task' }));
 expect(screen.getByRole('alert').textContent).toMatch(/1–19 words/);
 expect(change).not.toHaveBeenCalled();
 fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Solve one medium array problem' } });
 fireEvent.click(screen.getByRole('button', { name: 'Save task' }));
 await waitFor(() => expect(change).toHaveBeenCalledWith('/planner/tasks/add', { task: { title: 'Solve one medium array problem', instructions: 'Choose a problem.', completion_outcome: 'Save a solution.', estimated_minutes: 60, milestone_key: null, requirement_refs: [], prerequisites: [], schedule: [] } }));
});

it('preserves a legacy long title and only sends changed fields', async () => {
 const longTitle = Array(20).fill('word').join(' '); const task = { ...base, title: longTitle };
 const change = vi.fn().mockResolvedValue(true);
 render(<TaskEditor tasks={[task]} milestones={milestones} frozen={false} change={change} />);
 fireEvent.click(screen.getByRole('button', { name: `Edit ${longTitle}` }));
 expect(screen.getByText(/saved title; shorten it only if you change it/)).toBeTruthy();
 fireEvent.change(screen.getByLabelText('Instructions'), { target: { value: 'Updated instructions.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Save task' }));
 await waitFor(() => expect(change).toHaveBeenCalledWith('/planner/tasks/edit', { task_id: 'task-1', changes: { instructions: 'Updated instructions.' } }));
});

it('keeps a failed draft and prevents overwriting a concurrently changed field', async () => {
 const change = vi.fn().mockResolvedValue(false);
 const view = render(<TaskEditor tasks={[base]} milestones={milestones} frozen={false} change={change} />);
 fireEvent.click(screen.getByRole('button', { name: 'Edit Review arrays' }));
 fireEvent.change(screen.getByLabelText('Instructions'), { target: { value: 'My draft.' } });
 fireEvent.click(screen.getByRole('button', { name: 'Save task' }));
 await waitFor(() => expect(change).toHaveBeenCalledTimes(1));
 expect((screen.getByLabelText('Instructions') as HTMLTextAreaElement).value).toBe('My draft.');
 view.rerender(<TaskEditor tasks={[{ ...base, instructions: 'Edited elsewhere.' }]} milestones={milestones} frozen={false} change={change} />);
 expect(screen.getByRole('alert').textContent).toMatch(/changed while you were editing/);
 expect((screen.getByRole('button', { name: 'Save task' }) as HTMLButtonElement).disabled).toBe(true);
});
