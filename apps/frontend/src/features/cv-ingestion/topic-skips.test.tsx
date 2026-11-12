import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {CvConversationPanel} from './cv-conversation';
import {cvApi} from '@/lib/api/cv';
import {confirmedTarget, savedCv} from '../../../tests/fixtures/cv';
import type {CvConversation, InterviewTopic} from './types';

vi.mock('@/lib/api/cv', async importOriginal => {const actual = await importOriginal<typeof import('@/lib/api/cv')>(); return {...actual, cvApi: Object.fromEntries(Object.keys(actual.cvApi).map(key => [key, vi.fn()]))};});
const question = 'As co-founder of SportsFinder, what did you personally build or decide?';
const topics: InterviewTopic[] = [
 {id: 'done', title: 'Business Analyst — Synapxe', status: 'reviewed'},
 {id: 'one', title: 'Co-founder — SportsFinder', status: 'current'},
 {id: 'two', title: 'Analyst — SEA Bridge', status: 'pending'},
 {id: 'three', title: 'Coachify', status: 'deferred'},
];
const chat = (): CvConversation => ({id: 'chat-one', cv_id: 'cv-one', revision: 4, read_only: false, previous_conversation_id: null, purpose: 'skills_profile',
 active_question: {id: 'q2', item_id: 'one', title: 'Co-founder — SportsFinder', question, number: 2, limit: 3,
  hints: ['What you built or decided', 'Tools or methods you used'], reason: 'It shows which parts of the project you handled yourself.'},
 context: confirmedTarget, next_before: null, limits: {max_message_chars: 4000, max_messages: 500},
 interview: {status: 'reviewing', reviewed_items: 2, total_items: 4, estimates: [], topics},
 messages: [{id: 'm1', role: 'assistant', sequence: 1, created_at: '2026-11-12T02:55:00Z', actions: [], text: question}]});
const panel = () => <CvConversationPanel cvId="cv-one" detail={savedCv('cv-one')} token="synthetic-session" onChanged={vi.fn().mockResolvedValue(undefined)} onOpenSummary={vi.fn()} purpose="skills_profile" autoReview/>;
beforeEach(() => {
 vi.clearAllMocks();
 vi.mocked(cvApi.openConversation).mockResolvedValue(chat());
 vi.mocked(cvApi.conversation).mockResolvedValue(chat());
 vi.mocked(cvApi.sendMessage).mockResolvedValue(chat());
});
const sent = () => vi.mocked(cvApi.sendMessage).mock.calls.map(call => call[1]);

describe('skipping review topics', () => {
 it('shows each topic’s state and skips one topic after confirming in the sidebar', async () => {
  render(panel());
  const rail = await screen.findByRole('group', {name: 'Review topics'});
  const current = within(rail).getByText('Co-founder — SportsFinder').closest('li')!;
  expect(within(current).getByText('Now · question 2 of 3')).toBeVisible();
  expect(within(within(rail).getByText('Coachify').closest('li')!).getByText('Skipped · CV used as written')).toBeVisible();
  expect(within(rail).getByText(/% of your experience reviewed/)).toBeVisible();
  // Covered topics cannot be skipped; a skipped topic offers review instead.
  expect(within(rail).queryByRole('button', {name: 'Skip Business Analyst — Synapxe'})).not.toBeInTheDocument();
  expect(within(rail).queryByRole('button', {name: 'Skip Coachify'})).not.toBeInTheDocument();
  fireEvent.click(within(rail).getByRole('button', {name: 'Skip Analyst — SEA Bridge'}));
  const confirm = within(rail).getByRole('group', {name: 'Skip this topic?'});
  expect(cvApi.sendMessage).not.toHaveBeenCalled();
  fireEvent.click(within(confirm).getByRole('button', {name: 'Skip topic'}));
  await waitFor(() => expect(sent()).toEqual([expect.objectContaining({text: 'Skip Analyst — SEA Bridge.', command: 'skip_topic', item_id: 'two', expected_revision: 4})]));
 });

 it('keeps reviewing when the sidebar confirmation is dismissed', async () => {
  render(panel());
  const rail = await screen.findByRole('group', {name: 'Review topics'});
  fireEvent.click(within(rail).getByRole('button', {name: 'Skip Co-founder — SportsFinder'}));
  fireEvent.click(within(rail).getByRole('button', {name: 'Keep reviewing'}));
  expect(within(rail).queryByRole('group', {name: 'Skip this topic?'})).not.toBeInTheDocument();
  expect(cvApi.sendMessage).not.toHaveBeenCalled();
 });

 it('skips every remaining topic from the button beside the Topics heading', async () => {
  render(panel());
  const rail = await screen.findByRole('group', {name: 'Review topics'});
  fireEvent.click(within(rail).getByRole('button', {name: 'Skip all remaining'}));
  const confirm = within(rail).getByRole('group', {name: 'Skip all 2 remaining topics?'});
  fireEvent.click(within(confirm).getByRole('button', {name: 'Skip all'}));
  await waitFor(() => expect(sent()).toEqual([expect.objectContaining({command: 'skip_remaining', text: 'Skip all remaining topics.'})]));
  expect(sent()[0]).not.toHaveProperty('item_id');
 });

 it('reopens a skipped topic', async () => {
  render(panel());
  const rail = await screen.findByRole('group', {name: 'Review topics'});
  fireEvent.click(within(rail).getByRole('button', {name: 'Review Coachify instead'}));
  await waitFor(() => expect(sent()).toEqual([expect.objectContaining({command: 'review_topic', item_id: 'three'})]));
 });

 it('removes the review-complete card the moment a skipped topic is reopened', async () => {
  const finished = {...chat(), active_question: null, interview: {status: 'reviewed_with_gaps' as const, reviewed_items: 3, total_items: 4, estimates: [], topics: topics.map(topic => topic.status === 'deferred' ? topic : {...topic, status: 'reviewed' as const})}};
  vi.mocked(cvApi.openConversation).mockResolvedValue(finished); vi.mocked(cvApi.conversation).mockResolvedValue(finished);
  let reply!: (value: CvConversation) => void;
  vi.mocked(cvApi.sendMessage).mockReturnValue(new Promise<CvConversation>(resolve => { reply = resolve; }));
  render(panel());
  expect(await screen.findByRole('heading', {name: 'Your CV review is complete'})).toBeVisible();
  fireEvent.click(within(screen.getByRole('group', {name: 'Review topics'})).getByRole('button', {name: 'Review Coachify instead'}));
  await waitFor(() => expect(screen.queryByRole('heading', {name: 'Your CV review is complete'})).not.toBeInTheDocument());
  reply({...chat(), revision: 5});
  expect(await screen.findByText(question, {selector: 'p'})).toBeVisible();
 });

 it('confirms the composer shortcut in the chat before skipping the current topic', async () => {
  render(panel());
  fireEvent.click(await screen.findByRole('button', {name: 'Skip this topic'}));
  const confirm = screen.getByRole('group', {name: 'Skip Co-founder — SportsFinder?'});
  expect(within(confirm).getByText(/use what your CV says about it, as written/)).toBeVisible();
  fireEvent.click(within(confirm).getByRole('button', {name: 'Skip topic'}));
  await waitFor(() => expect(sent()).toEqual([expect.objectContaining({command: 'skip_topic', item_id: 'one', text: 'Skip Co-founder — SportsFinder.'})]));
 });
});

describe('the current question', () => {
 it('names its topic and position, lists what an answer can cover and explains why it is asked', async () => {
  render(panel());
  const transcript = await screen.findByRole('list', {name: 'Saved conversation messages'});
  const bubble = within(transcript).getByText(question).closest('li')!;
  expect(within(bubble).getByText('Co-founder — SportsFinder')).toBeVisible();
  expect(within(bubble).getByText('Question 2 of 3')).toBeVisible();
  expect(within(bubble).getByText('Your answer can cover')).toBeVisible();
  expect(within(bubble).getAllByRole('listitem').map(item => item.textContent)).toEqual(['What you built or decided', 'Tools or methods you used']);
  expect(screen.queryByRole('button', {name: 'Why this question?'})).not.toBeInTheDocument();
 });
});
