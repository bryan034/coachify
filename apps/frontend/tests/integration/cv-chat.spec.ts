import {test, expect} from '@playwright/test';
import {chatWorkflow, setupChatScenario, sendChat, readChat, manualMessage, chatAnswer} from './chat-workflow';
import {createLocalAccount} from './account-helpers';

test('saved chat interprets context, separates questions and corrections, resumes and retains sources', async ({page}, testInfo) => {
  test.setTimeout(180_000);
  const scenario = await setupChatScenario(page);
  await chatWorkflow(page, scenario, async (title) => {
    if (title.startsWith('3.')) await page.screenshot({path: testInfo.outputPath('cv-chat-desktop.png'), fullPage: true});
    if (title.startsWith('12.')) await page.screenshot({path: testInfo.outputPath('cv-chat-mobile.png'), fullPage: true});
  });
});

test('manual-only chat persists without a fake CV and recovers saved failed messages', async ({page}) => {
  test.setTimeout(90_000);
  const account = await createLocalAccount(page, 'Synthetic manual-only chat');
  const profile = await (await account.get('/api/v1/profile')).json();
  expect((await account.finish({expected_version: profile.version, occupational_status: 'employed', no_previous_education: true})).ok()).toBeTruthy();
  await page.goto('/cv'); await sendChat(page, manualMessage);
  await page.getByRole('button', {name: 'Save capability', exact: true}).click();
  await expect.poll(async () => (await (await account.get('/api/v1/profile/capabilities')).json()).declarations.length).toBe(1);
  expect((await (await account.get('/api/v1/cv')).json()).cvs).toHaveLength(0);
  const before = await readChat(account, null); await page.reload();
  await expect(page.getByRole('textbox', {name: 'Message elo', exact: true})).toBeEnabled();
  expect((await readChat(account, null)).messages).toEqual(before.messages);
  await sendChat(page, 'SYNTHETIC_CHAT_PROVIDER_FAILURE');
  const failed = await readChat(account, null), action = failed.messages.flatMap(message => message.actions).find(action => action.status === 'failed')!;
  expect(action).toBeTruthy();
  await Promise.all([
    page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`/actions/${action.id}`)),
    page.getByRole('button', {name: 'Retry this action', exact: true}).click(),
  ]);
  await expect.poll(async () => (await readChat(account, null)).messages.flatMap(message => message.actions).find(current => current.id === action.id)?.status).toBe('failed');
  const retry = await readChat(account, null);
  expect(retry.messages.filter(message => message.role === 'user' && message.text === 'SYNTHETIC_CHAT_PROVIDER_FAILURE')).toHaveLength(1);
  expect(retry.messages.flatMap(message => message.actions).find(current => current.id === action.id)?.status).toBe('failed');
  expect((await (await account.get('/api/v1/profile/capabilities')).json()).declarations).toHaveLength(1);
});

test('ambiguous and stale proposals cannot edit the wrong source; duplicate sends retain one turn', async ({page}) => {
  test.setTimeout(120_000);
  const {account, cvId} = await setupChatScenario(page);
  const cv = async () => (await account.get(`/api/v1/cv/${cvId}`)).json();
  await page.goto('/cv');
  await page.getByRole('button', {name: /^(Review with me|Continue review)$/}).click();
  await expect(page.locator('.cv-chat-current-topic')).toContainText('Team dashboard');
  const before = await cv();
  await sendChat(page, 'I helped with that project.');
  const choose = page.getByRole('article', {name: 'Save your explanation', exact: true}).filter({has: page.getByRole('button', {name: 'Use this source', exact: true})});
  await expect(choose.getByRole('button', {name: 'Use this source', exact: true})).toBeDisabled();
  await expect(choose.getByRole('radio')).toHaveCount(2);
  expect(await cv()).toEqual(before);
  await choose.getByRole('button', {name: 'Cancel change', exact: true}).click();
  expect(await cv()).toEqual(before);

  const conversation = await readChat(account, cvId);
  const body = {mutation_id: crypto.randomUUID(), expected_revision: conversation.revision, text: 'Why are you asking?'};
  const endpoint = `/api/v1/cv/conversations/${conversation.id}/messages`;
  const first = await page.request.post(endpoint, {headers: account.headers, data: body});
  expect(first.ok()).toBeTruthy();
  const repeated = await page.request.post(endpoint, {headers: account.headers, data: body});
  expect(repeated.ok()).toBeTruthy();
  await expect.poll(async () => (await readChat(account, cvId)).messages.flatMap(message => message.actions).some(action => action.status === 'pending')).toBe(false);
  expect((await readChat(account, cvId)).messages.filter(message => message.role === 'user' && message.text === body.text)).toHaveLength(1);
  expect(await cv()).toEqual(before);
  await page.reload(); await expect(page.getByRole('textbox', {name: 'Message elo', exact: true})).toBeEnabled();

  await sendChat(page, 'SYNTHETIC_CHAT_INVALID_SOURCE');
  expect(await cv()).toEqual(before);
  expect((await readChat(account, cvId)).messages.flatMap(message => message.actions).some(action => action.status === 'failed')).toBe(true);

  await sendChat(page, 'The Team dashboard project started in February 2023 and ended in 2024.');
  const correction = page.getByRole('article', {name: 'Review this correction', exact: true});
  await expect(correction.getByRole('button', {name: 'Save change', exact: true})).toBeEnabled();
  const project = before.items.find((item: {kind: string}) => item.kind === 'project');
  // A separate writer changes the record after the proposal, before its confirmation.
  const edited = await page.request.patch(`/api/v1/cv/${cvId}/items/${project.id}`, {headers: account.headers,
    data: {mutation_id: crypto.randomUUID(), expected_version: before.version, action: 'update', title: 'Newer project title'}});
  expect(edited.ok()).toBeTruthy(); const newer = await cv();
  await correction.getByRole('button', {name: 'Save change', exact: true}).click();
  await expect(correction).toContainText('Source changed');
  expect(await cv()).toEqual(newer);
});

test('a multi-source message reports partial failure and retries only the unfinished action', async ({page}) => {
  test.setTimeout(120_000);
  const {account, cvId} = await setupChatScenario(page);
  await page.goto('/cv');
  await page.getByRole('button', {name: /^(Review with me|Continue review)$/}).click();
  await expect(page.locator('.cv-chat-current-topic')).toContainText('Team dashboard');
  const text = chatAnswer + ' I cannot clarify my internship yet. SYNTHETIC_SECOND_ACTION_FAILURE';
  await sendChat(page, text);
  const conversation = await readChat(account, cvId);
  const actions = conversation.messages.flatMap(message => message.actions).filter(action => action.kind === 'clarify');
  expect(actions.filter(action => action.status === 'saved')).toHaveLength(1);
  expect(actions.filter(action => action.status === 'failed')).toHaveLength(1);
  const failed = actions.find(action => action.status === 'failed')!;
  const before = await (await account.get(`/api/v1/cv/${cvId}`)).json();
  const projectAnswer = before.clarifications.find((question: {item_id: string}) => question.item_id === actions.find(action => action.status === 'saved')!.item_id);
  expect(before.skills.find((skill: {skill_id: string}) => skill.skill_id === 'skill:python')?.experience_months).toBe(6);
  await Promise.all([
    page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`/actions/${failed.id}`)),
    page.getByRole('button', {name: 'Retry this action', exact: true}).click(),
  ]);
  await expect.poll(async () => (await readChat(account, cvId)).messages.flatMap(message => message.actions).find(action => action.id === failed.id)?.status, {timeout: 35_000}).toBe('failed');
  const after = await (await account.get(`/api/v1/cv/${cvId}`)).json();
  expect(after.clarifications.find((question: {id: string}) => question.id === projectAnswer.id)).toEqual(projectAnswer);
  const retried = await readChat(account, cvId);
  expect(retried.messages.filter(message => message.role === 'user' && message.text === text)).toHaveLength(1);
  expect(retried.messages.flatMap(message => message.actions).find(action => action.id === failed.id)?.status).toBe('failed');
});
