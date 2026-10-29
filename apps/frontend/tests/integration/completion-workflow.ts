import { openCvReviewTools } from '../fixtures/cv-ui';
import { expect, type Locator, type Page } from '@playwright/test';
import path from 'node:path';
import { createLocalAccount } from './account-helpers';
import {seedCanonicalGoal,confirmCanonicalGoal} from './canonical-career';
import type { CvDetail, Reconciliation } from '../../src/features/cv-ingestion/types';

export const mixedAnswer = "I wrote the Python loader for six months with my tutor's help. I also used Pandas to clean the data. My teammate wrote SQL.";
const qualificationAnswer = 'I completed the Computer Science diploma in 2024.';
const qualification = 'A Computer Science diploma is required.';
const repo = path.resolve(__dirname, '../../../..');
export type Chapter = (title: string, text: string, focus?: Locator) => Promise<void>;
export type Account = Awaited<ReturnType<typeof createLocalAccount>>;

export async function completionWorkflow(page: Page, account: Account, chapter: Chapter = async () => {}) {
 page.on('dialog', dialog => dialog.accept());
 const readCv = async (id: string): Promise<CvDetail> => {
  const response = await account.get(`/api/v1/cv/${id}`); expect(response.ok()).toBeTruthy(); return response.json();
 };
 async function upload() {
  const before = (await (await account.get('/api/v1/cv')).json()).cvs.map((cv: {id: string}) => cv.id);
  await page.getByLabel('CV document', { exact: true }).setInputFiles(path.join(repo, 'apps/frontend/tests/fixtures/synthetic-completion-cv.docx'));
  await page.getByRole('button', { name: 'Upload CV', exact: true }).click();
  let id = '';
  await expect.poll(async () => { const data = await (await account.get('/api/v1/cv')).json(); const cv = data.cvs.find((cv: {id: string}) => !before.includes(cv.id)); id = cv?.id ?? ''; return cv?.status; }, { timeout: 40_000 }).toBe('ready');
  await page.getByRole('button', { name: 'Refresh saved status', exact: true }).click();
  return id;
 }
 const question = (heading: string) => page.locator('.cv-question').filter({ has: page.getByRole('heading', { name: heading, exact: true }) });
 const projectQuestion = () => question('What did you personally contribute, and what did teammates or guidance cover?');

 const target=await seedCanonicalGoal(account,{role:'Synthetic data analyst internship',field:'Data analytics',skills:[{name:'Python',evidence:'Build reports using Python.'},{name:'SQL',evidence:'Query data using SQL.'}],conditions:[{description:qualification,evidence:qualification,category:'Qualifications'}]});
 const targetId=target.id;
 await page.goto('/career-goal');
 await chapter('1. Review the target requirements', 'The test account uses a pre-seeded synthetic canonical goal. The displayed skills and diploma requirement are saved by Career; this walkthrough does not evaluate live extraction.', page.getByRole('heading',{name:'Synthetic data analyst internship',exact:true}));
 await expect(page.getByText(qualification,{exact:true}).first()).toBeVisible();
 await chapter('2. Confirm this goal for CV review', 'Automatic saving is separate from explicit confirmation. Review the displayed requirements, then acknowledge this exact goal version before CV questions use it.',page.getByRole('region',{name:'Goal confirmation for CV review'}));
 const context=await confirmCanonicalGoal(page,account,target);
 expect(context.conditions).toEqual(expect.arrayContaining([expect.objectContaining({description:qualification,evidence:qualification})]));

 await page.goto('/cv');await openCvReviewTools(page);
 await chapter('3. Upload a CV, then select it', 'Upload, parsing, saved records and service calls are real. The document and model are synthetic test fixtures. Uploading alone does not change the selected CV.', page.getByLabel('CV document', { exact: true }));
 const cvId = await upload();
 expect((await (await account.get('/api/v1/cv')).json()).selection.cv_id).toBeNull();
 await page.getByRole('article', { name: `CV ${cvId}`, exact: true }).getByRole('button', { name: 'Select for analysis', exact: true }).click();
 await expect(page.getByLabel('Confirmed clarification target', { exact: true })).toContainText('Synthetic data analyst internship');
 await page.getByRole('button', { name: 'Prepare relevant questions', exact: true }).click();
 await expect(projectQuestion().getByRole('textbox', {name: 'Your explanation', exact: true})).toBeVisible();
 const initial = await readCv(cvId);
 const projectId = initial.items.find(item => item.kind === 'project')!.id;
 expect(initial.clarifications.some(q => q.question.startsWith('What can you clarify about this qualification?'))).toBe(true);
 await chapter('4. Explain contribution, guidance and a new skill', 'One answer separates personal Python work, tutor supervision, six months of reported use, a new Pandas claim and the teammate’s SQL work.', projectQuestion());
 await projectQuestion().getByRole('textbox', {name: 'Your explanation', exact: true}).fill(mixedAnswer);
 await projectQuestion().getByRole('button', { name: 'Save explanation', exact: true }).click();
 await expect(projectQuestion().getByRole('heading', { name: 'What your explanation changes', exact: true })).toBeVisible();
 await expect(projectQuestion()).toContainText('Performed under supervision');
 await expect(projectQuestion()).toContainText('Experience: 6 months reported');
 await expect(projectQuestion()).toContainText('team work only; not personal support from this source');
 const clarified = await readCv(cvId);
 const python = clarified.skills.find(skill => skill.skill_id === 'skill:python')!;
 expect(python).toMatchObject({experience_months: 6, proficiency: null});
 expect(python.sources).toEqual(expect.arrayContaining([expect.objectContaining({item_id: projectId, attribution: 'personal', assistance: 'supervised', experience_months: 6})]));
 expect(clarified.skills.find(skill => skill.skill_id === 'skill:sql')).toBeUndefined();
 expect(clarified.skills.find(skill => skill.skill_id === 'skill:pandas')?.sources).toEqual(expect.arrayContaining([expect.objectContaining({item_id: projectId, attribution: 'personal'})]));
 expect(clarified.items.find(item => item.id === projectId)?.description).toBe(initial.items.find(item => item.id === projectId)?.description);
 await chapter('5. Review what changed immediately', 'Python now shows the reported six months and supervision. Pandas is source-linked. SQL remains in the original evidence and answer, but teammate-only SQL does not become personal capability. No second confirmation is required.', page.getByRole('region', { name: 'Potential skills', exact: true }));

 const educationQuestion = question('What can you clarify about this qualification? Partial knowledge or “I do not know” is fine.');
 await educationQuestion.getByRole('textbox', {name: 'Your explanation', exact: true}).fill(qualificationAnswer);
 await educationQuestion.getByRole('button', { name: 'Save explanation', exact: true }).click();
 await expect(educationQuestion.getByRole('button', { name: 'Edit explanation', exact: true })).toBeVisible();
 expect((await readCv(cvId)).items.find(item => item.kind === 'education')).toMatchObject({end_date: '2024'});
 await page.getByRole('button', { name: 'Edit or remove Team dashboard', exact: true }).click();
 const editor = page.getByRole('form', { name: 'Edit Team dashboard', exact: true });
 await editor.getByLabel('Start date', { exact: true }).fill('2023-02');
 await editor.getByLabel('End date', { exact: true }).fill('2024');
 await chapter('6. Dates retain the precision you know', 'The diploma answer supplies only a year. The project editor accepts a month and a year. These calendar dates do not recalculate the six months of Python use.', editor);
 await editor.getByRole('button', { name: 'Save correction', exact: true }).click();
 await expect(editor).not.toBeVisible();
 const dated = await readCv(cvId);
 expect(dated.items.find(item => item.id === projectId)).toMatchObject({start_date: '2023-02', end_date: '2024'});
 expect(dated.skills.find(skill => skill.skill_id === 'skill:python')?.experience_months).toBe(6);
 expect(dated.clarifications.find(question => question.item_id === projectId)).toMatchObject({reconciliation_required: false, answer: mixedAnswer});
 await expect(projectQuestion()).toContainText(mixedAnswer);

 // Source changes require fresh preparation while retaining unrelated saved facts.
 await page.getByRole('button', {name: 'Prepare relevant questions', exact: true}).click();
 const pending = page.locator('.cv-question').filter({has: page.getByRole('button', {name: 'Save explanation', exact: true})});
 await expect(pending.getByRole('textbox', {name: 'Your explanation', exact: true})).toBeVisible();
 const reprepared = await readCv(cvId);
 expect(reprepared.items).toEqual(dated.items);
 expect(reprepared.skills).toEqual(dated.skills);
 expect(reprepared.clarifications.find(question => question.item_id === projectId)).toEqual(dated.clarifications.find(question => question.item_id === projectId));
 await expect(projectQuestion()).toContainText(mixedAnswer);

 // Deliberate model outage keeps the raw answer; retry never submits another answer revision.
 await pending.getByRole('textbox', {name: 'Your explanation', exact: true}).fill('SYNTHETIC_INTERPRETATION_FAILURE');
 await pending.getByRole('button', {name: 'Save explanation', exact: true}).click();
 const failed = question('How would you describe your current familiarity with this skill? Unknown is fine.');
 await expect(failed).toContainText('Your explanation is saved, but interpretation could not finish.');
 const failedCv = await readCv(cvId);
 const beforeRetry = failedCv.clarifications.find(q => q.interpretation_status === 'failed')!;
 const failedSelection = (await (await account.get('/api/v1/cv')).json()).selection;
 const failedTarget = await (await account.get('/api/v1/career/goals/current/confirmed-context')).json();
 const failedDeclarations = await (await account.get('/api/v1/profile/capabilities')).json();
 const failedParams = new URLSearchParams({expected_version: String(failedCv.version), expected_selection_version: String(failedSelection.version), expected_declarations_version: String(failedDeclarations.version), expected_target_id: failedTarget.id, expected_target_version: String(failedTarget.version), expected_target_selection_version: String(failedTarget.selection_version)});
 expect((await account.get(`/api/v1/cv/${cvId}/analysis-input?${failedParams}`)).status()).toBe(409);
 await chapter('7. A failed interpretation does not lose the answer', 'This is an intentional synthetic model outage. The explanation remains saved. Retry acts on that saved answer; it does not invent a result or resubmit the explanation.', failed);
 await failed.getByRole('button', {name: 'Retry interpretation', exact: true}).click();
 await expect(failed.getByRole('button', {name: 'Retry interpretation', exact: true})).toBeEnabled();
 expect((await readCv(cvId)).clarifications.find(q => q.id === beforeRetry.id)).toMatchObject({answer_revision: beforeRetry.answer_revision, answer: beforeRetry.answer, interpretation_status: 'failed'});
 await failed.getByRole('button', {name: 'Edit explanation', exact: true}).click();
 await failed.getByRole('textbox', {name: 'Your explanation', exact: true}).fill('I do not know my proficiency yet.');
 await failed.getByRole('button', {name: 'Save explanation', exact: true}).click();
 await expect(page.getByText('You could not clarify this further. You can continue with uncertainty; it does not establish a missing capability.', {exact: true})).toBeVisible();

 await page.getByLabel('Capability name', { exact: true }).fill('Python');
 await page.getByLabel('Capability description', { exact: true }).fill('I also practise Python in weekly synthetic exercises.');
 await page.getByRole('radio', { name: /Attach to CV evidence: Team dashboard/ }).check();
 await page.getByRole('button', { name: 'Add capability', exact: true }).click();
 await expect(page.getByText('Linked evidence is current.', {exact: true})).toBeVisible();
 let manual = await (await account.get('/api/v1/profile/capabilities')).json();
 const declarationId = manual.declarations[0].id;
 expect(manual.declarations[0].attached_to).toMatchObject({cv_id: cvId, item_id: projectId});
 await chapter('8. Attach a manual claim to its actual source', 'Python can link to the project that supports it, including skills found through projects. The manual declaration remains a separate user statement.', page.getByText('Linked evidence is current.', {exact: true}));
 await page.getByRole('button', { name: 'Edit or remove Team dashboard', exact: true }).click();
 await editor.getByLabel('Description', { exact: true }).fill('Project: The team dashboard included a Python data loader and SQL queries. I have corrected this source summary.');
 await editor.getByRole('button', { name: 'Save correction', exact: true }).click();
 await expect(editor).not.toBeVisible();
 await expect(page.getByText('Linked evidence changed. Review how this declaration relates to it.', {exact: true})).toBeVisible();
 const beforeDetach = await (await account.get('/api/v1/profile/capabilities')).json();
 await chapter('9. Changed evidence prompts an explicit link decision', 'The source summary changed. Coachify retains the manual declaration, flags the old link, and lets you choose how it should relate to the evidence.', page.getByText('Linked evidence changed. Review how this declaration relates to it.', {exact: true}));
 await page.getByRole('button', { name: 'Review CV link', exact: true }).click();
 await page.getByRole('combobox', { name: 'How should this declaration be linked?', exact: true }).selectOption('standalone');
 await page.getByRole('button', { name: 'Save link choice', exact: true }).click();
 await expect(page.getByText('Standalone declaration; no CV evidence link.', {exact: true})).toBeVisible();
 manual = await (await account.get('/api/v1/profile/capabilities')).json();
 expect(manual.declarations[0]).toMatchObject({id: declarationId, description: beforeDetach.declarations[0].description, attached_to: null});
 const originalBeforeReplacement = await readCv(cvId);

 await chapter('10. Upload a replacement without replacing history', 'A second CV is saved independently. Compare the previous evidence and explicitly choose which statements to carry forward. Similar names never transfer answers automatically.', page.getByLabel('CV document', {exact: true}));
 const replacementId = await upload();
 expect((await (await account.get('/api/v1/cv')).json()).selection.cv_id).toBe(cvId);
 await page.getByRole('combobox', {name: 'Previous saved CV', exact: true}).selectOption(cvId);
 await page.getByRole('button', {name: 'Compare saved evidence', exact: true}).click();
 await expect(page.getByRole('heading', {name: 'Review changed source evidence', exact: true})).toBeVisible();
 const comparisonResponse = await account.get(`/api/v1/cv/${replacementId}/reconciliation`);
 expect(comparisonResponse.ok()).toBeTruthy(); const comparison: Reconciliation = await comparisonResponse.json();
 const newProject = comparison.candidate_items.find(item => item.kind === 'project')!;
 await expect(page.getByRole('button', {name: 'Accept reviewed extraction', exact: true})).toBeDisabled();
 for (const id of comparison.affected_item_ids) {
  const previous = comparison.previous_items.find(item => item.id === id)!;
  await page.getByRole('combobox', {name: `Reconcile ${previous.title}`, exact: true}).selectOption(id === projectId ? newProject.id : 'archive');
 }
 await chapter('11. Reapply one explanation; retain other statements in history', 'The project explanation is deliberately assigned to the reviewed replacement project. The diploma explanation and other prepared items stay in history. Original CV records remain intact.', page.getByRole('combobox', {name: 'Reconcile Team dashboard', exact: true}));
 await page.getByRole('button', {name: 'Accept reviewed extraction', exact: true}).click();
 await expect(page.getByRole('heading', {name: 'Review changed source evidence', exact: true})).not.toBeVisible();
 let replacement = await readCv(replacementId);
 expect(replacement.clarifications).toHaveLength(1);
 expect(replacement.items.find(item => item.kind === 'education')?.end_date).toBeNull();
 expect(replacement.clarifications[0]).toMatchObject({answer: mixedAnswer, interpretation_status: 'failed', reconciled_from: {cv_id: cvId, item_id: projectId}});
 expect(await readCv(cvId)).toEqual(originalBeforeReplacement);
 await page.getByRole('article', {name: `CV ${replacementId}`, exact: true}).getByRole('button', {name: 'Select for analysis', exact: true}).click();
 await projectQuestion().getByRole('button', {name: 'Retry interpretation', exact: true}).click();
 await expect(projectQuestion().getByRole('heading', {name: 'What your explanation changes', exact: true})).toBeVisible();
 replacement = await readCv(replacementId);
 expect(replacement.skills.find(skill => skill.skill_id === 'skill:python')?.experience_months).toBe(6);
 expect(replacement.skills.some(skill => skill.skill_id === 'skill:pandas')).toBe(true);
 expect(replacement.skills.some(skill => skill.skill_id === 'skill:sql')).toBe(false);
 await page.reload();await openCvReviewTools(page);
 await expect(projectQuestion()).toContainText(mixedAnswer);
 await expect(page.getByText('Standalone declaration; no CV evidence link.', {exact: true})).toBeVisible();

 const selected = (await (await account.get('/api/v1/cv')).json()).selection;
 const selectedTarget = await (await account.get('/api/v1/career/goals/current/confirmed-context')).json();
 manual = await (await account.get('/api/v1/profile/capabilities')).json();
 const params = new URLSearchParams({expected_version: String(replacement.version), expected_selection_version: String(selected.version), expected_declarations_version: String(manual.version), expected_target_id: targetId, expected_target_version: String(selectedTarget.version), expected_target_selection_version: String(selectedTarget.selection_version)});
 const response = await account.get(`/api/v1/cv/${replacementId}/analysis-input?${params}`);
 expect(response.status()).toBe(200); const handoff = await response.json();
 expect(handoff).toMatchObject({schema_version: '2', requires_consumer_revalidation: true, target: selectedTarget, capabilities: {cv_id: replacementId, cv_version: replacement.version, selection_version: selected.version, declarations_version: manual.version, effective_version: replacement.effective_version}});
 expect(handoff.capabilities.skills.find((skill: {skill_id: string}) => skill.skill_id === 'skill:python')).toMatchObject({experience_months: 6});
 expect(handoff).not.toHaveProperty('analysis_id');
 expect(await readCv(replacementId)).toEqual(replacement);
 params.set('expected_target_version', String(selectedTarget.version + 1));
 expect((await account.get(`/api/v1/cv/${replacementId}/analysis-input?${params}`)).status()).toBe(409);
 await chapter('12. Ready to hand off exact saved versions', 'The API assembles a snapshot tied to the selected CV, manual declarations and confirmed target. A stale target is rejected. This read does not create a gap analysis, eligibility result or roadmap; a future consumer must revalidate the versions.', page.getByRole('region', {name: 'Potential skills', exact: true}));
 return {cvId, replacementId, targetId, declarationId, handoff};
}
