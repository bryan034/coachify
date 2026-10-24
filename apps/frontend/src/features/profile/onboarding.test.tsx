import React from 'react';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {beforeEach,expect,test,vi} from 'vitest';
import {ProfileProvider} from './profile-provider';
import {ProfileForm} from './profile-form';
import {WorkspaceGuard} from '@/features/auth/workspace-guard';
const replace=vi.hoisted(()=>vi.fn());
vi.mock('next/navigation',()=>({useRouter:()=>({replace}),usePathname:()=>'/onboarding'}));
vi.mock('./school-browser',()=>({SchoolBrowser:()=>null}));
let saved:Record<string,unknown>;
let failure:'none'|'uncommitted'|'lost'='none';
beforeEach(()=>{
 replace.mockReset();saved={version:0,onboarding_complete:false,occupational_status:null,school_category:null,education_review_required:false,education:{}};failure='none';
 vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
  if(url.endsWith('/auth-config'))return new Response(JSON.stringify({mode:'local_test'}));
  if(url.endsWith('/school-categories'))return new Response(JSON.stringify([{id:'university',label:'University'}]));
  if(url.endsWith('/auth/session'))return new Response(JSON.stringify({id:'synthetic',name:'Synthetic',provider:'local_test',email_verified:true}));
  if(init?.method==='PATCH'||url.endsWith('/onboarding/complete')){
   if(failure==='uncommitted')return new Response(JSON.stringify({detail:'Synthetic storage outage'}),{status:503});
   const input=JSON.parse(String(init?.body));saved={...saved,...input,version:Number(saved.version)+1,onboarding_complete:url.endsWith('/onboarding/complete')};
   if(failure==='lost')throw new TypeError('Synthetic connection lost after commit');
  }
  return new Response(JSON.stringify(saved));
 }));
});
async function form(){
 render(<ProfileProvider><WorkspaceGuard><ProfileForm initialSetup/></WorkspaceGuard></ProfileProvider>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'Finish setup'})).toBeEnabled());
 fireEvent.click(screen.getByRole('radio',{name:'Employed'}));
 fireEvent.click(screen.getByRole('radio',{name:'No applicable previous education'}));
}
test('Save progress does not complete onboarding; explicit Finish setup does',async()=>{
 await form();fireEvent.click(screen.getByRole('button',{name:'Save progress'}));
 await screen.findByText('Profile saved.');expect(saved.onboarding_complete).toBe(false);expect(replace).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Finish setup'}));
 await waitFor(()=>expect(replace).toHaveBeenCalledWith('/dashboard'));
 expect(saved.no_previous_education).toBe(true);expect(saved.onboarding_complete).toBe(true);
});
test('uncommitted finish failure preserves the draft and never redirects',async()=>{
 await form();failure='uncommitted';fireEvent.click(screen.getByRole('button',{name:'Finish setup'}));
 await screen.findByText('Synthetic storage outage');expect(screen.getByRole('radio',{name:'Employed'})).toBeChecked();
 expect(saved.onboarding_complete).toBe(false);expect(replace).not.toHaveBeenCalled();
});
test('lost committed completion is confirmed by canonical readback',async()=>{
 await form();failure='lost';fireEvent.click(screen.getByRole('button',{name:'Finish setup'}));
 await waitFor(()=>expect(replace).toHaveBeenCalledWith('/dashboard'));
 expect(saved.version).toBe(1);expect(saved.onboarding_complete).toBe(true);
 expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).endsWith('/onboarding/complete'))).toHaveLength(1);
});
