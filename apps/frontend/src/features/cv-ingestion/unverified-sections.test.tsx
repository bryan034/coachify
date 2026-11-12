import {render, screen, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {CvConversationPanel} from './cv-conversation';
import {CvReview} from './cv-review';
import {cvApi} from '@/lib/api/cv';
import {clarificationState, confirmedTarget, policy, savedCv} from '../../../tests/fixtures/cv';
import type {CvConversation} from './types';

vi.mock('@/lib/api/cv', async importOriginal => {const actual = await importOriginal<typeof import('@/lib/api/cv')>(); return {...actual, cvApi: Object.fromEntries(Object.keys(actual.cvApi).map(key => [key, vi.fn()]))};});
const notice = 'Heads up: I couldn’t automatically verify “Team dashboard” against your CV, so I’ve kept what I extracted but treated it as unconfirmed. It would be better if you explain this section to me here in the chat.';
const issue = {status: 'unverified' as const, code: 'source_excerpt', message: 'This section could not be verified against your CV, so it is kept as unconfirmed. Explain it in the review chat to confirm it.'};
const chat = (topics: NonNullable<CvConversation['interview']>['topics']): CvConversation => ({id: 'chat-one', cv_id: 'cv-one', revision: 1, read_only: false, previous_conversation_id: null,
 active_question: {id: 'q1', item_id: 'one', title: 'Team dashboard', question: 'What did you personally build?'}, context: confirmedTarget, next_before: null, limits: {max_message_chars: 4000, max_messages: 500}, purpose: 'skills_profile',
 interview: {status: 'reviewing', reviewed_items: 0, total_items: topics!.length, estimates: [], topics},
 messages: [{id: 'm1', role: 'assistant', sequence: 1, created_at: '2026-10-28T09:00:00Z', actions: [], text: `${notice}\n\nWhat did you personally build?`}]});
const panel = () => <CvConversationPanel cvId="cv-one" detail={savedCv('cv-one')} token="synthetic-session" onChanged={vi.fn()} onOpenSummary={vi.fn()} purpose="skills_profile" autoReview/>;
beforeEach(() => vi.clearAllMocks());

describe('sections that could not be verified', () => {
 it('flags them in the topic sidebar with a warning label and says it again in the chat', async () => {
  const current = chat([{id: 'one', title: 'Team dashboard', status: 'current', validation: 'unverified'}, {id: 'two', title: 'Payments API', status: 'pending', validation: null}]);
  vi.mocked(cvApi.openConversation).mockResolvedValue(current);
  vi.mocked(cvApi.conversation).mockResolvedValue(current);
  render(panel());
  const topics = await screen.findByRole('group', {name: 'Review topics'});
  const flagged = within(topics).getByText('Team dashboard').closest('li')!;
  expect(flagged).toHaveClass('is-warning');
  expect(within(flagged).getByText(/Warning · could not be verified\. Best explained in the chat\./)).toBeVisible();
  expect(within(flagged).getByText(/warning, could not be verified/)).toBeInTheDocument();
  const ordinary = within(topics).getByText('Payments API').closest('li')!;
  expect(ordinary).not.toHaveClass('is-warning');
  expect(within(ordinary).queryByText(/Warning/)).not.toBeInTheDocument();
  // The summary sits outside the topic list, which is hidden on small screens.
  expect(screen.getByText(/1 section could not be verified against your CV/)).toBeVisible();
  expect(screen.getByText(/Heads up: I couldn’t automatically verify “Team dashboard”/)).toBeVisible();
 });
 it('shows no warning when every section verified', async () => {
  const current = chat([{id: 'one', title: 'Team dashboard', status: 'current'}]);
  vi.mocked(cvApi.openConversation).mockResolvedValue(current);
  vi.mocked(cvApi.conversation).mockResolvedValue(current);
  render(panel());
  const topics = await screen.findByRole('group', {name: 'Review topics'});
  expect(within(topics).queryByText(/Warning/)).not.toBeInTheDocument();
  expect(screen.queryByText(/could not be verified against your CV/)).not.toBeInTheDocument();
 });
 it('marks the extracted item as unverified while keeping its extracted context visible', () => {
  const detail = savedCv();
  detail.items[0] = {...detail.items[0], validation_issue: issue};
  render(<CvReview detail={detail} policy={policy} questions={clarificationState(detail, confirmedTarget, true)} token="token" signal={new AbortController().signal} onSaved={vi.fn()} refresh={vi.fn().mockResolvedValue(undefined)}/>);
  const card = screen.getByText('Team dashboard', {selector: 'h4'}).closest('article')!;
  expect(within(card).getByText('Warning · unverified')).toBeVisible();
  expect(within(card).getByRole('note')).toHaveTextContent(issue.message);
  expect(within(card).getByRole('note')).toHaveTextContent('not confirmed');
  // The extracted description and its cited excerpt both stay visible.
  expect(within(card).getAllByText('Built a Python dashboard with a team.').length).toBeGreaterThanOrEqual(2);
  expect(within(card).queryByText('Stated in CV')).not.toBeInTheDocument();
 });
});
