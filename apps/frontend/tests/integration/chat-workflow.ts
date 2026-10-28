import {expect, type Locator, type Page} from '@playwright/test';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {createLocalAccount} from './account-helpers';
import type {CvConversation, CvDetail} from '../../src/features/cv-ingestion/types';

export const chatAnswer = "I wrote the Python loader for six months with my tutor's help. I also used Pandas to clean the data. My teammate wrote SQL.";
export const chatExtra = 'I also used Power BI for two months.';
export const chatCorrection = 'Actually, I used Python for three months, not six.';
export const manualMessage = 'I use Figma to make posters for my student society.';
export type ChatAccount = Awaited<ReturnType<typeof createLocalAccount>>;
export type ChatChapter = (title: string, text: string, focus?: Locator) => Promise<void>;

export async function setupChatScenario(page: Page) {
  const account = await createLocalAccount(page, 'Synthetic conversational CV reviewer');
  const profile = await (await account.get('/api/v1/profile')).json();
  expect((await account.finish({expected_version: profile.version, occupational_status: 'employed', no_previous_education: true})).ok()).toBeTruthy();
  const source = 'SYNTHETIC VACANCY: Build reports using Python. Query data using SQL.';
  const created = await page.request.post('/api/v1/career/targets', {headers: account.headers, data: {
    mutation_id: crypto.randomUUID(), target_type: 'specific_job', role: 'Synthetic data analyst', field: 'Data analytics',
    reviewed_source_text: source, skills: [{name: 'Python', evidence: 'Build reports using Python.'}, {name: 'SQL', evidence: 'Query data using SQL.'}],
  }});
  expect(created.status()).toBe(201); const target = await created.json();
  const confirmed = await page.request.post(`/api/v1/career/targets/${target.id}/confirm`, {headers: account.headers,
    data: {mutation_id: crypto.randomUUID(), expected_version: target.version}});
  expect(confirmed.ok()).toBeTruthy(); const confirmedTarget = await confirmed.json();
  expect((await page.request.put('/api/v1/career/targets/selection', {headers: account.headers, data: {
    mutation_id: crypto.randomUUID(), expected_version: 0, career_target_id: target.id, career_target_version: confirmedTarget.version,
  }})).ok()).toBeTruthy();
  const upload = await page.request.post('/api/v1/cv/uploads', {headers: account.headers,
    multipart: {mutation_id: crypto.randomUUID(), file: {name: 'synthetic-chat-cv.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      buffer: readFileSync(path.resolve(__dirname, '../fixtures/synthetic-clarification-cv.docx'))}}});
  expect(upload.status()).toBe(202); const cvId = (await upload.json()).id as string;
  await expect.poll(async () => (await (await account.get(`/api/v1/cv/${cvId}`)).json()).status, {timeout: 40_000}).toBe('ready');
  expect((await page.request.put('/api/v1/cv/selection', {headers: account.headers,
    data: {mutation_id: crypto.randomUUID(), expected_version: 0, cv_id: cvId}})).ok()).toBeTruthy();
  return {account, cvId, targetId: target.id};
}

export async function sendChat(page: Page, text: string) {
  const composer = page.getByRole('textbox', {name: 'Message Coachify', exact: true});
  await expect(composer).toBeEnabled(); await composer.fill(text);
  await page.getByRole('button', {name: 'Send message', exact: true}).click();
  await expect(composer).toBeEnabled(); await expect(composer).toHaveValue('');
  await expect(page.locator('.cv-chat-action-pending')).toHaveCount(0, {timeout: 35_000});
}

export async function readChat(account: ChatAccount, cvId: string | null): Promise<CvConversation> {
  const listing = await (await account.get(`/api/v1/cv/conversations${cvId ? `?cv_id=${cvId}` : ''}`)).json();
  expect(listing.conversations.length).toBeGreaterThan(0);
  return (await account.get(`/api/v1/cv/conversations/${listing.conversations[0].id}?limit=100`)).json();
}

export async function chatWorkflow(page: Page, scenario: Awaited<ReturnType<typeof setupChatScenario>>, chapter: ChatChapter = async () => {}) {
  const {account, cvId} = scenario;
  const readCv = async (): Promise<CvDetail> => (await account.get(`/api/v1/cv/${cvId}`)).json();
  const chat = page.getByRole('region', {name: 'CV conversation', exact: true});
  await page.goto('/cv');
  await expect(page.getByRole('textbox', {name: 'Message Coachify', exact: true})).toBeEnabled();
  await chapter('1. Review your saved CV through a conversation', 'This is a synthetic account and model, using real local services and saves. The CV and Career target were explicitly selected before this walkthrough.', chat);
  await chat.getByRole('button', {name: /^(Review with me|Continue review)$/}).click();
  await expect(chat.locator('.cv-chat-current-topic')).toContainText('Team dashboard');
  await expect(chat).toContainText('Synthetic data analyst');
  await chapter('2. One focused question', 'Coachify asks about the project contribution that matters to the confirmed target. You can answer naturally, ask why, or skip.', chat.locator('.cv-chat-current-topic'));
  await sendChat(page, chatAnswer);
  await expect.poll(async () => (await readCv()).skills.find(skill => skill.skill_id === 'skill:python')?.experience_months).toBe(6);
  const first = await readCv(), projectId = first.items.find(item => item.kind === 'project')!.id;
  expect(first.skills.find(skill => skill.skill_id === 'skill:python')?.sources).toEqual(expect.arrayContaining([expect.objectContaining({item_id: projectId, attribution: 'personal', assistance: 'supervised'})]));
  expect(first.skills.some(skill => skill.skill_id === 'skill:pandas')).toBe(true);
  expect(first.skills.some(skill => skill.skill_id === 'skill:sql')).toBe(false);
  await chapter('3. A natural answer becomes source-linked facts', 'One explanation records personal Python work, tutor guidance, six months, Pandas and teammate-only SQL. Ordinary clarification does not require another confirmation.', chat);

  const beforeQuestion = await readCv();
  await sendChat(page, 'Why are you asking?');
  expect(await readCv()).toEqual(beforeQuestion);
  await expect(chat).toContainText('It does not establish whether you used the skill elsewhere.');
  await chapter('4. Ask a side question without changing your CV', 'The assistant explains why the question matters. The test verifies this message does not change any saved CV evidence.', chat);
  await sendChat(page, 'What if I had six months of SQL experience?');
  expect(await readCv()).toEqual(beforeQuestion);

  await sendChat(page, chatExtra);
  const extended = await readCv();
  expect(extended.skills.find(skill => skill.skill_id === 'skill:python')).toMatchObject({experience_months: 6});
  expect(extended.skills.find(skill => skill.skill_id === 'skill:power bi')).toMatchObject({experience_months: 2});
  expect(extended.clarifications.some(question => question.answer === chatAnswer)).toBe(true);
  await chapter('5. Add context without repeating yourself', 'The additional Power BI experience is saved alongside the earlier explanation. Python, Pandas and guidance are preserved.', chat);

  await sendChat(page, chatCorrection);
  const proposal = () => chat.getByRole('article', {name: 'Review this correction', exact: true}).filter({has: page.getByRole('button', {name: 'Save change', exact: true})});
  await expect(proposal()).toBeVisible(); expect((await readCv()).skills.find(skill => skill.skill_id === 'skill:python')?.experience_months).toBe(6);
  await chapter('6. Review or cancel a correction', 'A requested correction is shown before it changes saved facts. Cancel keeps the earlier six months.', proposal());
  await proposal().getByRole('button', {name: 'Cancel change', exact: true}).click();
  expect((await readCv()).skills.find(skill => skill.skill_id === 'skill:python')?.experience_months).toBe(6);
  await sendChat(page, chatCorrection);
  await proposal().getByRole('button', {name: 'Save change', exact: true}).click();
  await expect.poll(async () => (await readCv()).skills.find(skill => skill.skill_id === 'skill:python')?.experience_months).toBe(3);
  await expect.poll(async () => (await readChat(account, cvId)).messages.flatMap(message => message.actions).filter(action => action.kind === 'correct').at(-1)?.status).toBe('saved');
  const corrected = await readCv();
  expect(corrected.skills.find(skill => skill.skill_id === 'skill:python')?.sources).toEqual(expect.arrayContaining([expect.objectContaining({item_id: projectId, assistance: 'supervised'})]));
  expect(corrected.skills.find(skill => skill.skill_id === 'skill:power bi')?.experience_months).toBe(2);
  await chapter('7. Save only the intended change', 'Python changes from six months to three. Earlier statements remain in history, and the independent Power BI fact stays intact.', chat);

  const beforeReload = await readChat(account, cvId);
  await page.reload();
  await expect(page.getByRole('textbox', {name: 'Message Coachify', exact: true})).toBeEnabled();
  const resumed = await readChat(account, cvId);
  expect(resumed.id).toBe(beforeReload.id); expect(resumed.messages).toEqual(beforeReload.messages);
  await expect(chat.getByText(chatAnswer, {exact: true}).first()).toBeVisible();
  await chapter('8. Return to the same saved conversation', 'Reload restores the account-owned history. No duplicate answer or correction is submitted.', chat);

  await chat.getByRole('button', {name: /^(Review with me|Continue review)$/}).click();
  await expect(chat.getByRole('button', {name: 'Skip this question', exact: true})).toBeEnabled();
  const beforeSkip = await readCv();
  await chat.getByRole('button', {name: 'Skip this question', exact: true}).click();
  await expect(chat.getByText(/Skipped; that detail remains unknown\./)).toBeVisible();
  const skipped = await readCv();
  expect(skipped.effective_version).toBe(beforeSkip.effective_version);
  expect(skipped.clarifications.some(question => question.status === 'skipped')).toBe(true);
  await chapter('9. Leave uncertainty unresolved', 'Skipping a question does not erase earlier facts, imply zero experience or establish a missing skill.', chat);

  await sendChat(page, manualMessage);
  const manual = () => chat.getByRole('article', {name: 'Add a capability', exact: true}).filter({has: page.getByRole('button', {name: 'Save capability', exact: true})});
  await expect(manual()).toBeVisible();
  expect((await (await account.get('/api/v1/profile/capabilities')).json()).declarations).toHaveLength(0);
  await manual().getByRole('button', {name: 'Cancel change', exact: true}).click();
  expect((await (await account.get('/api/v1/profile/capabilities')).json()).declarations).toHaveLength(0);
  await sendChat(page, manualMessage);
  await manual().getByRole('button', {name: 'Save capability', exact: true}).click();
  await expect.poll(async () => (await (await account.get('/api/v1/profile/capabilities')).json()).declarations.length).toBe(1);
  await chapter('10. Add an omitted capability', 'A manual Figma statement is saved only after Save capability. Profile owns the declaration; it is not presented as text extracted from the CV.', chat);

  await chat.getByRole('button', {name: 'View CV summary', exact: true}).click();
  await expect(page.getByRole('region', {name: 'Potential skills', exact: true})).toContainText('3 months');
  await expect(page.getByRole('heading', {name: 'Figma', exact: true})).toBeVisible();
  await chapter('11. Inspect the evidence whenever you need it', 'The summary retains the saved contributions, sources, original evidence and detailed review tools. It does not calculate readiness or create an assessment.', page.getByRole('region', {name: 'Potential skills', exact: true}));
  const storage = await page.evaluate(() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)]));
  expect(storage).not.toContain(chatAnswer); expect(storage).not.toContain(manualMessage);
  await page.locator('summary').filter({hasText: 'Your CV summary'}).click();
  await page.setViewportSize({width: 390, height: 844});
  await expect(page.getByRole('textbox', {name: 'Message Coachify', exact: true})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await chapter('12. Continue on a smaller screen', 'The same conversation and composer remain available on mobile. This walkthrough uses a fixed synthetic model fixture; live language understanding has not been evaluated.', chat);
  return {cvId, targetId: scenario.targetId, conversationId: resumed.id, conversation: await readChat(account, cvId), savedCv: await readCv()};
}
