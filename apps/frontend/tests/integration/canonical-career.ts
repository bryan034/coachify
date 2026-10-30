import {execFileSync} from 'node:child_process';
import {expect,type Page} from '@playwright/test';
import type {createLocalAccount} from './account-helpers';

type Account=Awaited<ReturnType<typeof createLocalAccount>>;
export type SyntheticGoal={role:string;field:string;target_type?:'specific_job'|'career_exploration';company?:string;skills:{name:string;evidence?:string}[];conditions?:{description:string;evidence?:string;category?:string}[];goal_id?:string};
export type SeededGoal={id:string;version:number;selection_version:number};

/** Only the disposable Compose override mounts this script and enables its guard. */
export async function seedCanonicalGoal(account:Account,input:SyntheticGoal):Promise<SeededGoal>{
 if(!input.role.startsWith('Synthetic '))throw new Error('Canonical goal fixtures must be clearly synthetic.');
 const who=await (await account.get('/api/v1/profile/auth/session')).json();
 const project=process.env.ELO_TEST_COMPOSE_PROJECT||'ci-profile';
 const containers=execFileSync('docker',['ps','--filter',`label=com.docker.compose.project=${project}`,'--filter','label=com.docker.compose.service=career-service','--format','{{.ID}}'],{encoding:'utf8'}).trim().split(/\s+/).filter(Boolean);
 if(containers.length!==1)throw new Error('Choose exactly one disposable Career test service using ELO_TEST_COMPOSE_PROJECT.');
 const result=JSON.parse(execFileSync('docker',['exec','-i',containers[0],'python','/fixture/seed-career.py'],{input:JSON.stringify({owner:who.id,...input}),encoding:'utf8'}));
 const value={id:result.id??result.goal?._id,version:result.version??result.goal?.version,selection_version:result.selection_version};
 if(typeof value.id!=='string'||!Number.isSafeInteger(value.version)||!Number.isSafeInteger(value.selection_version))throw new Error('The synthetic Career goal seed returned incomplete version metadata.');
 return value;
}

export async function confirmCanonicalGoal(page:Page,account:Account,goal:SeededGoal,throughUI=true){
 const before=await (await account.get('/api/v1/career/goals/current/cv-confirmation')).json();
 expect(before).toMatchObject({goal_id:goal.id,goal_version:goal.version,selection_version:goal.selection_version,confirmed:false,context:null});
 if(throughUI){
  await page.goto('/career-goal');const panel=page.getByRole('region',{name:'Goal confirmation for CV review'});
  await panel.getByRole('button',{name:'Confirm this goal for CV review',exact:true}).click();
  await expect(panel.getByRole('link',{name:'Review CV clarifications',exact:true})).toBeVisible();
 }else{
  const response=await page.request.post('/api/v1/career/goals/current/cv-confirmation',{headers:account.headers,data:{expected_goal_id:goal.id,expected_goal_version:goal.version,expected_selection_version:goal.selection_version,mutation_id:crypto.randomUUID()}});
  expect(response.ok()).toBeTruthy();
 }
 const result=await (await account.get('/api/v1/career/goals/current/confirmed-context')).json();
 expect(result).toMatchObject({id:goal.id,version:goal.version,selection_version:goal.selection_version,confirmed:true});
 return result;
}
