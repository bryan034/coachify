import {test,expect} from '@playwright/test';
import {createLocalAccount,fillCurrentEmployment} from './account-helpers';

const enabled=process.env.CAREER_FLOW_E2E==='1';
const live=process.env.CAREER_FLOW_LIVE==='1';
const source='Synthetic ExampleCo is hiring a Software Engineer Intern. The role is in Singapore. Build Python APIs. Python is required. Git is preferred. A computing diploma is required. Apply by 31 December 2026.';

test.describe('Career extraction through real services',()=>{
 test.skip(!enabled,'Run only through the isolated run-career-flow.py harness.');
 test.setTimeout(600_000);

 test('extracts, saves, researches, answers, edits and restores the canonical goal',async({page})=>{
  const account=await createLocalAccount(page,'Synthetic career extraction account');
  await page.getByRole('button',{name:'Employed',exact:true}).click();await fillCurrentEmployment(page);
  await page.getByRole('button',{name:'No applicable previous education'}).click();
  await page.getByRole('button',{name:'Enter elo',exact:true}).click();
  await page.goto('/career-goal?new=1');
  await page.getByRole('tab',{name:'Upload document'}).click();
  await page.getByLabel('Job description document',{exact:true}).setInputFiles({name:'synthetic-role.txt',mimeType:'text/plain',buffer:Buffer.from(source)});
  await expect(page.getByRole('textbox',{name:'Review and edit the preview'})).toHaveValue(source);
  await page.getByRole('button',{name:'Extract career goal'}).click();
  await expect(page).toHaveURL(/\/career-goal\/chat\?source=jd$/);
  await Promise.race([
   expect(page.getByRole('button',{name:'Role and research details'})).toBeEnabled({timeout:180_000}),
   page.getByRole('log').getByRole('alert').waitFor({state:'visible',timeout:180_000}).then(async()=>{
    throw new Error('Career extraction failed: '+await page.getByRole('log').getByRole('alert').innerText());
   }),
  ]);
  await page.getByRole('button',{name:'Role and research details'}).click();
  await expect(page.getByRole('heading',{name:/Software Engineer/})).toBeVisible();
  await expect(page.getByText('Python · required')).toBeVisible();
  await expect(page.getByText('Git · preferred')).toBeVisible();
  await expect(page.getByText('application deadline: 31 December 2026')).toBeVisible();
  await page.getByRole('button',{name:'Hide details'}).click();
  await expect(page.getByRole('log')).toContainText('Ask me anything about this goal set!',{timeout:180_000});
  const before=await (await account.get('/api/v1/career/goals/current')).json();
  expect(before.goal).toMatchObject({company:'Synthetic ExampleCo',location:'Singapore',employment_type:'internship',
   job_dates:[{kind:'application_deadline',text:'31 December 2026',date:'2026-12-31'}]});
  expect(before.goal.skills).toEqual(expect.arrayContaining([expect.objectContaining({name:'Python',priority:'required',origin:'employer'}),expect.objectContaining({name:'Git',priority:'preferred',origin:'employer'})]));
  expect(before.goal.non_skill_requirements).toEqual(expect.arrayContaining([expect.objectContaining({category:'qualification',priority:'required'})]));
  expect(before.goal).not.toHaveProperty('source_text');
  const box=page.getByRole('textbox',{name:'Message elo'});
  await box.fill('Which skills are required and preferred?');await page.getByRole('button',{name:'Send message'}).click();
  await expect(page.locator('.agent-exchange .assistant').last()).toContainText('Python',{timeout:180_000});
  await expect(page.locator('.agent-exchange .assistant').last()).toContainText('Git');
  await expect(page.getByRole('button',{name:'Send message'})).toBeDisabled();
  await box.fill('Change the location to London.');await page.getByRole('button',{name:'Send message'}).click();
  await expect.poll(async()=>((await (await account.get('/api/v1/career/goals/current')).json()).goal.location),{timeout:180_000}).toBe('London');
  const edited=await (await account.get('/api/v1/career/goals/current')).json();
  expect(edited.goal._id).toBe(before.goal._id);expect(edited.goal.version).toBeGreaterThan(before.goal.version);
  expect(edited.goal.skills).toEqual(before.goal.skills);expect(edited.goal.job_dates).toEqual(before.goal.job_dates);
  await page.reload();
  await expect(page.getByRole('button',{name:'Role and research details'})).toBeEnabled({timeout:180_000});
  await page.getByRole('button',{name:'Role and research details'}).click();
  await expect(page.getByText('application deadline: 31 December 2026')).toBeVisible();
  const restored=await (await account.get('/api/v1/career/goals/current')).json();expect(restored.goal).toEqual(edited.goal);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(live?'career-local-model.png':'career-fixture.png'),fullPage:true});
  const noOwner=await page.request.get('/api/v1/career/goals/current');expect(noOwner.status()).toBe(401);
  if(!live){
   await page.goto('/career-goal?new=1');
   await page.getByRole('textbox',{name:'Job description',exact:true}).fill(source+' Synthetic malformed output.');
   await page.getByRole('button',{name:'Extract career goal'}).click();
   await expect(page.getByRole('log').getByRole('alert')).toBeVisible({timeout:30_000});
   await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeEnabled();
   const unchanged=await (await account.get('/api/v1/career/goals/current')).json();expect(unchanged.goal).toEqual(edited.goal);
   await page.getByRole('button',{name:'← Career Goal',exact:true}).click();
   await expect(page.getByRole('heading',{name:/Software Engineer/})).toBeVisible();
  }
 });
});
