import {expect, test} from '@playwright/test';
import path from 'node:path';
import {createLocalAccount} from './account-helpers';
import {chatAnswer, readChat, sendChat} from './chat-workflow';

test('uploaded CV review saves and resumes the same question after leaving and reloading', async ({page}) => {
  test.setTimeout(120_000);
  const account = await createLocalAccount(page, 'Synthetic CV review resume');
  const profile = await (await account.get('/api/v1/profile')).json();
  expect((await account.finish({
    expected_version: profile.version, occupational_status: 'employed', no_previous_education: true,
  })).ok()).toBeTruthy();

  const sent: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/v1\/cv\/conversations\/[^/]+\/messages$/.test(new URL(request.url()).pathname)) {
      sent.push(request.postDataJSON().text);
    }
  });
  await page.goto('/cv');
  await page.getByLabel('CV document', {exact: true}).setInputFiles(
    path.resolve(__dirname, '../fixtures/synthetic-clarification-cv.docx'),
  );
  await page.getByRole('button', {name: 'Upload CV', exact: true}).click();
  await expect(page).toHaveURL(/\/cv\?review=/);
  const cvId = new URL(page.url()).searchParams.get('review')!;
  const chat = page.getByRole('region', {name: 'CV conversation', exact: true});
  await expect(chat.getByRole('button', {name: 'Why this question?'})).toBeVisible({timeout: 40_000});
  const firstQuestion = (await readChat(account, cvId)).active_question;
  expect(firstQuestion).toBeTruthy();
  expect(sent).toHaveLength(1);
  await chat.getByRole('button', {name: 'Why this question?'}).click();
  await sendChat(page, chatAnswer);
  expect(sent).toEqual([expect.stringMatching(/review my cv/i), chatAnswer]);

  const before = await readChat(account, cvId);
  expect(before.active_question).toBeTruthy();
  expect(before.active_question!.id).not.toBe(firstQuestion!.id);
  expect(before.messages.filter(message => message.role === 'user' && message.text === chatAnswer)).toHaveLength(1);
  await chat.getByRole('button', {name: 'Save and review later'}).click();
  await expect(page).toHaveURL(/\/cv$/);
  await page.reload();
  await page.getByRole('button', {name: /Review.*synthetic-clarification-cv\.docx/i}).click();
  await expect(page).toHaveURL(new RegExp(`/cv\\?review=${cvId}$`));
  await expect(chat.getByText(chatAnswer, {exact: true})).toBeVisible();
  await expect(chat.locator('.cv-chat-message-assistant').last()).toContainText(before.active_question!.question);

  const after = await readChat(account, cvId);
  expect(after.id).toBe(before.id);
  expect(after.active_question).toEqual(before.active_question);
  expect(after.messages).toEqual(before.messages);
  expect(sent).toHaveLength(2);
  expect((await (await account.get('/api/v1/cv')).json()).selection.cv_id).toBeNull();
});
