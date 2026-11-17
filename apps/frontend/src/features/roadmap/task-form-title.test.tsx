import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { TaskForm, blankDraft, draftOf } from './task-form';
import type { Session } from './types';
import { config } from '../../../tests/fixtures/roadmap-workspace';

const base = { date: '2030-01-09', where: 'today', others: [], config: config(), nowMinute: null, catalog: [], disabled: false, onChange: vi.fn(), onSubmit: vi.fn(), onCancel: vi.fn(), onEscape: vi.fn() };

it('shows and enforces the word limit in the redesigned new-task form', () => {
 const empty = blankDraft(null);
 const view = render(<TaskForm {...base} mode="new" draft={{ ...empty, title: Array(20).fill('word').join(' ') }} base={empty} />);
 const form = screen.getByRole('group', { name: 'New task' });
 expect(within(form).getByText('20 of 11 words')).toBeVisible();
 expect(within(form).getByRole('button', { name: 'Add task' })).toBeDisabled();
 expect(within(form).getByText('Use at most 11 words and 160 characters')).toBeVisible();
 view.rerender(<TaskForm {...base} mode="new" draft={{ ...empty, title: 'Solve an array problem' }} base={empty} />);
 fireEvent.click(within(form).getByRole('button', { name: 'Add task' }));
 expect(base.onSubmit).toHaveBeenCalledWith(false);
});

it('allows another field to be edited while a legacy long title stays unchanged', () => {
 const session: Session = { id: 'one', task_id: 'one', title: Array(20).fill('word').join(' '), instructions: 'Read.', completion_criterion: 'Finish.', date: '2030-01-09', start_time: null, duration_minutes: 30, status: 'scheduled', missed: false, origin: 'generated', milestone_key: null, skills: [] };
 const original = draftOf(session);
 render(<TaskForm {...base} mode="edit" session={session} base={original} draft={{ ...original, doneWhen: 'Save the result.' }} />);
 expect(screen.getByText(/saved title; shorten it only if you change it/)).toBeVisible();
 expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
});
