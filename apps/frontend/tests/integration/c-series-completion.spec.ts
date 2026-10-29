import { test, expect } from '@playwright/test';
import { createLocalAccount } from './account-helpers';
import { completionWorkflow } from './completion-workflow';

test('interpreted claims, dates, source links, reconciliation and target-bound handoff use real services', async ({page}) => {
 test.setTimeout(180_000);
 page.setDefaultTimeout(15_000);
 const account = await createLocalAccount(page, 'Synthetic C-series completion');
 const profile = await (await account.get('/api/v1/profile')).json();
 expect((await account.finish({expected_version: profile.version, occupational_status: 'employed', no_previous_education: true})).ok()).toBeTruthy();
 await completionWorkflow(page, account);
 await page.screenshot({path: test.info().outputPath('c-series-completion.png'), fullPage: true});
});
