import {execFileSync} from 'node:child_process';
import {expect} from '@playwright/test';
import type {createLocalAccount} from './account-helpers';

type Account=Awaited<ReturnType<typeof createLocalAccount>>;

export async function grantPremium(account:Account){
 const who=await (await account.get('/api/v1/profile/auth/session')).json();
 const project=process.env.ELO_TEST_COMPOSE_PROJECT||'ci-profile';
 const containers=execFileSync('docker',['ps','--filter',`label=com.docker.compose.project=${project}`,'--filter','label=com.docker.compose.service=profile-service','--format','{{.ID}}'],{encoding:'utf8'}).trim().split(/\s+/).filter(Boolean);
 if(containers.length!==1)throw new Error('Choose exactly one disposable Profile test service using ELO_TEST_COMPOSE_PROJECT.');
 execFileSync('docker',['exec','-i',containers[0],'python','/fixture/grant-premium.py'],{input:JSON.stringify({owner:who.id}),encoding:'utf8'});
 expect((await (await account.get('/api/v1/profile/auth/session')).json()).account_type).toBe('premium');
}
