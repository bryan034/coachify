import React, { useState } from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ProfileProvider, useProfile } from './profile-provider';
import { WorkspaceGuard } from '@/features/auth/workspace-guard';
const replace=vi.hoisted(()=>vi.fn());
vi.mock('next/navigation',()=>({usePathname:()=>'/cv',useRouter:()=>({replace})}));
function Probe() {
 const s=useProfile();
 return <><p data-testid="account">{s.account?.name || 'signed out'}</p><p data-testid="profile">{s.profile?.education.course || 'empty'}</p><p data-testid="complete">{String(s.profile?.onboarding_complete)}</p><button onClick={()=>s.setProfile({version:2,onboarding_complete:true,occupational_status:'employed',school_category:null,education_context:'last',education_review_required:false,education:{course:'Newer confirmed course'}})}>Confirm completion</button><button onClick={s.reload}>Reload</button><p data-testid="loading">{String(s.loading)}</p>
 <button onClick={()=>void s.beginAccess('register').then(()=>s.completeAccess({name:'Synthetic'}))}>Create</button><button onClick={s.signOut}>Logout</button><button onClick={s.retryLogout}>Retry logout</button><p>{s.logoutError}</p><p data-testid="session-checking">{String(s.sessionChecking)}</p><p data-testid="session-error">{s.sessionError}</p><button onClick={()=>void s.retrySession()}>Validate session</button></>;
}
function Draft(){const [value,setValue]=useState('');return <label>Unsaved clarification<textarea value={value} onChange={event=>setValue(event.target.value)}/></label>;}
async function openDraft(){
 render(<ProfileProvider><Probe/><WorkspaceGuard><Draft/></WorkspaceGuard></ProfileProvider>);
 await waitFor(()=>expect(screen.getByTestId('loading')).toHaveTextContent('false'));
 fireEvent.click(screen.getByText('Create',{exact:true}));
 await waitFor(()=>expect(screen.getByTestId('profile')).toHaveTextContent('Private course'));
 fireEvent.click(screen.getByText('Confirm completion',{exact:true}));
 const field=screen.getByRole('textbox',{name:'Unsaved clarification'});
 fireEvent.change(field,{target:{value:'My unfinished explanation'}});field.focus();return field;
}
async function startPollingClock(){
 vi.useFakeTimers();
 // Refresh once under the clock so subsequent polling and expiry timers are controlled too.
 await act(async()=>{fireEvent.click(screen.getByText('Validate session'));});
}
let failedLogout=false;
let privateRead: (()=>Promise<Response>) | undefined;
let sessionRead: (()=>Promise<Response>) | undefined;
let requests: string[]=[];
beforeEach(()=>{
 sessionStorage.clear(); localStorage.clear(); failedLogout=false; privateRead=undefined; sessionRead=undefined; requests=[];replace.mockReset();
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
  requests.push(url);
  const value=url.endsWith('/auth-config')?{mode:'local_test'}:url.endsWith('/school-categories')?[]:url.endsWith('/auth/attempts')?{nonce:'nonce'}:url.endsWith('/auth/complete')||url.endsWith('/auth/session')?{id:'synthetic-id',name:'Synthetic',provider:'local_test',onboarding_complete:false}:url.endsWith('/auth/logout')?{ok:true}:{version:1,education:{course:'Private course'}};
  if(url.endsWith('/auth/logout')&&failedLogout)return new Response(JSON.stringify({detail:'Unavailable'}),{status:503});
  if(url.endsWith('/profile')&&privateRead)return privateRead();
  if(url.endsWith('/auth/session')&&sessionRead)return sessionRead();
  return new Response(JSON.stringify(value));
 }));
});
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();});
test('signed-out entry never loads a private profile; registration and logout clear state',async()=>{
 render(<ProfileProvider><Probe/></ProfileProvider>);
 await waitFor(()=>expect(screen.getByTestId('loading')).toHaveTextContent('false'));
 expect(requests.some(url=>url.endsWith('/profile'))).toBe(false);
 fireEvent.click(screen.getByText('Create',{exact:true}));
 await waitFor(()=>expect(screen.getByTestId('profile')).toHaveTextContent('Private course'));
 fireEvent.click(screen.getByText('Logout',{exact:true}));
 expect(screen.getByTestId('account')).toHaveTextContent('signed out');
 expect(screen.getByTestId('profile')).toHaveTextContent('empty');
 await waitFor(()=>expect(sessionStorage.getItem('coachify.pending-logout')).toBeNull());
});
test('late profile response after logout cannot restore private state',async()=>{
 let release:(response:Response)=>void=()=>{};
 privateRead=()=>new Promise(resolve=>{release=resolve;});
 render(<ProfileProvider><Probe/></ProfileProvider>);
 await waitFor(()=>expect(screen.getByTestId('loading')).toHaveTextContent('false'));
 fireEvent.click(screen.getByText('Create',{exact:true}));
 await waitFor(()=>expect(requests.some(url=>url.endsWith('/profile'))).toBe(true));
 fireEvent.click(screen.getByText('Logout',{exact:true}));
 await act(async()=>{release(new Response(JSON.stringify({version:1,education:{course:'Stale private course'}})));});
 expect(screen.getByTestId('profile')).toHaveTextContent('empty');
 expect(screen.getByTestId('account')).toHaveTextContent('signed out');
});
test('failed logout stays locked across remount and offers termination retry',async()=>{
 const first=render(<ProfileProvider><Probe/></ProfileProvider>);
 await waitFor(()=>expect(screen.getByTestId('loading')).toHaveTextContent('false'));
 fireEvent.click(screen.getByText('Create',{exact:true}));
 await waitFor(()=>expect(screen.getByTestId('profile')).toHaveTextContent('Private course'));
 failedLogout=true;fireEvent.click(screen.getByText('Logout',{exact:true}));
 await screen.findByText(/Server sign-out could not be confirmed/);
 first.unmount();requests=[];
 render(<ProfileProvider><Probe/></ProfileProvider>);
 await screen.findByText(/Sign-out is pending/);
 expect(requests.some(url=>url.endsWith('/auth/session')||url.endsWith('/profile'))).toBe(false);
 failedLogout=false;fireEvent.click(screen.getByText('Retry logout'));
 await waitFor(()=>expect(sessionStorage.getItem('coachify.pending-logout')).toBeNull());
 expect(screen.getByTestId('profile')).toHaveTextContent('empty');
});
test('cross-tab access change clears the account and ignores earlier session errors',async()=>{
 render(<ProfileProvider><Probe/></ProfileProvider>);
 await waitFor(()=>expect(screen.getByTestId('loading')).toHaveTextContent('false'));
 fireEvent.click(screen.getByText('Create',{exact:true}));
 await waitFor(()=>expect(screen.getByTestId('profile')).toHaveTextContent('Private course'));
 const previous = JSON.parse(sessionStorage.getItem('coachify.session')!).token;
 fireEvent.click(screen.getByText('Logout',{exact:true}));
 fireEvent.click(screen.getByText('Create',{exact:true}));
 await waitFor(()=>expect(screen.getByTestId('profile')).toHaveTextContent('Private course'));
 act(()=>window.dispatchEvent(new CustomEvent('coachify:expired',{detail:previous})));
 expect(screen.getByTestId('account')).toHaveTextContent('Synthetic');
 act(()=>window.dispatchEvent(new StorageEvent('storage',{key:'coachify.access-epoch',newValue:'newer'})));
 expect(screen.getByTestId('account')).toHaveTextContent('signed out');
 expect(screen.getByTestId('profile')).toHaveTextContent('empty');
});

test('older incomplete readback cannot replace newer confirmed setup',async()=>{
 render(<ProfileProvider><Probe/></ProfileProvider>);
 await waitFor(()=>expect(screen.getByTestId('loading')).toHaveTextContent('false'));
 fireEvent.click(screen.getByText('Create',{exact:true}));
 await waitFor(()=>expect(screen.getByTestId('profile')).toHaveTextContent('Private course'));
 fireEvent.click(screen.getByText('Confirm completion',{exact:true}));
 expect(screen.getByTestId('complete')).toHaveTextContent('true');
 fireEvent.click(screen.getByText('Reload',{exact:true}));
 await waitFor(()=>expect(screen.getByTestId('loading')).toHaveTextContent('false'));
 expect(screen.getByTestId('profile')).toHaveTextContent('Newer confirmed course');
 expect(screen.getByTestId('complete')).toHaveTextContent('true');
});


test('back-forward cached pages mask the mounted draft until session and profile are revalidated',async()=>{
 const field=await openDraft();
 let release:((response:Response)=>void)|undefined;
 privateRead=()=>new Promise(resolve=>{release=resolve;});
 const validations=requests.filter(url=>url.endsWith('/auth/session')).length;
 act(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
 expect(field).not.toBeVisible();expect(field).toBeInTheDocument();
 expect(screen.getByRole('dialog',{name:'Checking your session'})).toHaveFocus();
 expect(screen.getByTestId('session-checking')).toHaveTextContent('true');
 await waitFor(()=>expect(release).toBeTypeOf('function'));
 expect(requests.filter(url=>url.endsWith('/auth/session'))).toHaveLength(validations+1);
 await act(async()=>{release!(new Response(JSON.stringify({version:3,onboarding_complete:true,education:{course:'Revalidated private course'}})));});
 await waitFor(()=>expect(screen.getByTestId('session-checking')).toHaveTextContent('false'));
 expect(screen.getByTestId('profile')).toHaveTextContent('Revalidated private course');
 expect(screen.getByRole('textbox',{name:'Unsaved clarification'})).toBe(field);
 expect(field).toHaveValue('My unfinished explanation');expect(field).toHaveFocus();
});

test('tab changes preserve a draft; unavailable validation locks actions and retry restores it',async()=>{
 const field=await openDraft();
 const visibility=vi.spyOn(document,'visibilityState','get');
 visibility.mockReturnValue('hidden');
 const privateReads=requests.filter(url=>url.endsWith('/profile')).length;
 act(()=>document.dispatchEvent(new Event('visibilitychange')));
 expect(field).toBeVisible();expect(field).toHaveValue('My unfinished explanation');
 sessionRead=async()=>new Response(JSON.stringify({detail:'Unavailable'}),{status:503});
 visibility.mockReturnValue('visible');act(()=>document.dispatchEvent(new Event('visibilitychange')));
 await screen.findByRole('dialog',{name:'Connection interrupted'});
 expect(field).not.toBeVisible();expect(field.closest('[inert]')).not.toBeNull();
 expect(screen.getByTestId('account')).toHaveTextContent('Synthetic');
 sessionRead=undefined;fireEvent.click(screen.getByRole('button',{name:'Retry session'}));
 await waitFor(()=>expect(field).toBeVisible());
 expect(field).toHaveValue('My unfinished explanation');expect(field).toHaveFocus();
 expect(requests.filter(url=>url.endsWith('/profile'))).toHaveLength(privateReads);
});

test('failed BFCache profile validation stays masked and retry checks the profile again',async()=>{
 const field=await openDraft();
 privateRead=async()=>new Response(JSON.stringify(null));
 act(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
 await screen.findByRole('dialog',{name:'Connection interrupted'});
 expect(field).not.toBeVisible();expect(field).toHaveValue('My unfinished explanation');
 const reads=requests.filter(url=>url.endsWith('/profile')).length;
 privateRead=async()=>new Response(JSON.stringify({version:3,onboarding_complete:true,education:{course:'Revalidated course'}}));
 fireEvent.click(screen.getByRole('button',{name:'Retry session'}));
 await waitFor(()=>expect(field).toBeVisible());
 expect(requests.filter(url=>url.endsWith('/profile'))).toHaveLength(reads+1);
 expect(screen.getByTestId('profile')).toHaveTextContent('Revalidated course');expect(field).toHaveValue('My unfinished explanation');
});

test('a hanging validation is bounded, coalesces triggers and ignores a late failure after retry',async()=>{
 const field=await openDraft();
 vi.useFakeTimers();let release:((response:Response)=>void)|undefined;
 sessionRead=()=>new Promise(resolve=>{release=resolve;});
 const validations=requests.filter(url=>url.endsWith('/auth/session')).length;
 fireEvent.click(screen.getByText('Validate session'));
 fireEvent.click(screen.getByText('Validate session'));
 act(()=>document.dispatchEvent(new Event('visibilitychange')));
 expect(requests.filter(url=>url.endsWith('/auth/session'))).toHaveLength(validations+1);
 await act(async()=>{await vi.advanceTimersByTimeAsync(10_000);});
 expect(screen.getByRole('dialog',{name:'Connection interrupted'})).toBeVisible();
 sessionRead=undefined;
 await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'Retry session'}));});
 expect(field).toBeVisible();
 await act(async()=>{release!(new Response(JSON.stringify({detail:'Expired'}),{status:401}));});
 expect(field).toBeVisible();expect(field).toHaveValue('My unfinished explanation');
 expect(screen.getByTestId('account')).toHaveTextContent('Synthetic');
});

test.each([
 ['revoked session',()=>new Response(JSON.stringify({detail:'Expired'}),{status:401})],
 ['different account',()=>new Response(JSON.stringify({id:'other-owner',name:'Other',provider:'local_test'}))],
 ['expired session',()=>new Response(JSON.stringify({id:'synthetic-id',name:'Synthetic',provider:'local_test',expires_at:'2000-01-01T00:00:00Z'}))],
] as const)('%s clears private drafts instead of unmasking them',async(_,response)=>{
 const field=await openDraft();sessionRead=async()=>response();
 fireEvent.click(screen.getByText('Validate session'));
 await waitFor(()=>expect(screen.getByTestId('account')).toHaveTextContent('signed out'));
 expect(field).not.toBeInTheDocument();expect(sessionStorage.getItem('coachify.session')).toBeNull();
});

test.each([
 ['missing account identity',{name:'Synthetic',provider:'local_test'}],
 ['malformed account expiry',{id:'synthetic-id',name:'Synthetic',provider:'local_test',expires_at:'not-a-date'}],
] as const)('%s masks the draft without signing out and allows recovery',async(_,payload)=>{
 const field=await openDraft();const epoch=localStorage.getItem('coachify.access-epoch');const session=sessionStorage.getItem('coachify.session');
 sessionRead=async()=>new Response(JSON.stringify(payload));
 fireEvent.click(screen.getByText('Validate session'));
 await screen.findByRole('dialog',{name:'Connection interrupted'});
 expect(field).toBeInTheDocument();expect(field).not.toBeVisible();expect(field).toHaveValue('My unfinished explanation');
 expect(localStorage.getItem('coachify.access-epoch')).toBe(epoch);expect(sessionStorage.getItem('coachify.session')).toBe(session);
 expect(requests.some(url=>url.endsWith('/auth/logout'))).toBe(false);
 sessionRead=undefined;fireEvent.click(screen.getByRole('button',{name:'Retry session'}));
 await waitFor(()=>expect(field).toBeVisible());expect(field).toHaveValue('My unfinished explanation');expect(field).toHaveFocus();
});

test('malformed initial session readback retains credentials for an explicit connection retry',async()=>{
 localStorage.setItem('coachify.access-epoch','1');
 const session=JSON.stringify({token:'synthetic-session-token',epoch:'1'});sessionStorage.setItem('coachify.session',session);
 sessionRead=async()=>new Response(JSON.stringify({name:'Incomplete identity'}));
 render(<ProfileProvider><Probe/><WorkspaceGuard><Draft/></WorkspaceGuard></ProfileProvider>);
 await screen.findByRole('alert');
 expect(sessionStorage.getItem('coachify.session')).toBe(session);expect(localStorage.getItem('coachify.access-epoch')).toBe('1');
 expect(requests.some(url=>url.endsWith('/auth/logout')||url.endsWith('/profile'))).toBe(false);
 sessionRead=undefined;fireEvent.click(screen.getByRole('button',{name:'Retry connection'}));
 await waitFor(()=>expect(screen.getByTestId('profile')).toHaveTextContent('Private course'));
 expect(screen.getByTestId('account')).toHaveTextContent('Synthetic');
});

test('a slow healthy foreground poll keeps the draft visible and editable without moving focus',async()=>{
 const field=await openDraft();await startPollingClock();let release:((response:Response)=>void)|undefined;
 sessionRead=()=>new Promise(resolve=>{release=resolve;});
 await act(async()=>{await vi.advanceTimersByTimeAsync(30_000);});
 expect(release).toBeTypeOf('function');expect(field).toBeVisible();expect(field).toHaveFocus();
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
 fireEvent.change(field,{target:{value:'Still editing while access is checked'}});
 await act(async()=>{release!(new Response(JSON.stringify({id:'synthetic-id',name:'Synthetic',provider:'local_test'})));});
 expect(field).toBeVisible();expect(field).toHaveFocus();expect(field).toHaveValue('Still editing while access is checked');
});

test('returning to a tab promotes a silent poll to a masked check without another request',async()=>{
 const field=await openDraft();await startPollingClock();let release:((response:Response)=>void)|undefined;
 sessionRead=()=>new Promise(resolve=>{release=resolve;});
 const validations=requests.filter(url=>url.endsWith('/auth/session')).length;
 await act(async()=>{await vi.advanceTimersByTimeAsync(30_000);});
 expect(release).toBeTypeOf('function');expect(field).toBeVisible();
 act(()=>document.dispatchEvent(new Event('visibilitychange')));
 expect(field).not.toBeVisible();expect(screen.getByRole('dialog',{name:'Checking your session'})).toBeVisible();
 expect(requests.filter(url=>url.endsWith('/auth/session'))).toHaveLength(validations+1);
 await act(async()=>{release!(new Response(JSON.stringify({id:'synthetic-id',name:'Synthetic',provider:'local_test'})));});
 expect(field).toBeVisible();expect(field).toHaveFocus();expect(field).toHaveValue('My unfinished explanation');
});

test('a failed silent foreground poll masks the retained draft for recovery',async()=>{
 const field=await openDraft();await startPollingClock();
 sessionRead=async()=>new Response(JSON.stringify({detail:'Unavailable'}),{status:503});
 await act(async()=>{await vi.advanceTimersByTimeAsync(30_000);});
 expect(screen.getByRole('dialog',{name:'Connection interrupted'})).toBeVisible();
 expect(field).not.toBeVisible();expect(field).toHaveValue('My unfinished explanation');
 sessionRead=undefined;
 await act(async()=>{fireEvent.click(screen.getByRole('button',{name:'Retry session'}));});
 expect(field).toBeVisible();expect(field).toHaveFocus();
});

test('an old validation cannot restore a draft after logout and a new sign-in',async()=>{
 const field=await openDraft();let release:((response:Response)=>void)|undefined;
 sessionRead=()=>new Promise(resolve=>{release=resolve;});
 fireEvent.click(screen.getByText('Validate session'));fireEvent.click(screen.getByText('Logout',{exact:true}));
 sessionRead=undefined;fireEvent.click(screen.getByText('Create',{exact:true}));
 await waitFor(()=>expect(screen.getByTestId('profile')).toHaveTextContent('Private course'));
 fireEvent.click(screen.getByText('Confirm completion',{exact:true}));
 const newField=screen.getByRole('textbox',{name:'Unsaved clarification'});expect(newField).not.toBe(field);expect(newField).toHaveValue('');
 await act(async()=>{release!(new Response(JSON.stringify({id:'old-owner',name:'Old account',provider:'local_test'})));});
 expect(screen.getByTestId('account')).toHaveTextContent('Synthetic');expect(newField).toBeVisible();expect(newField).toHaveValue('');
});

test('cross-tab epoch changes discard drafts even when an earlier validation succeeds later',async()=>{
 const field=await openDraft();let release:((response:Response)=>void)|undefined;
 sessionRead=()=>new Promise(resolve=>{release=resolve;});
 fireEvent.click(screen.getByText('Validate session'));
 act(()=>{localStorage.setItem('coachify.access-epoch','newer');window.dispatchEvent(new StorageEvent('storage',{key:'coachify.access-epoch',newValue:'newer'}));});
 await act(async()=>{release!(new Response(JSON.stringify({id:'synthetic-id',name:'Synthetic',provider:'local_test'})));});
 expect(screen.getByTestId('account')).toHaveTextContent('signed out');expect(field).not.toBeInTheDocument();
});

test('an epoch change is checked before a delayed storage notification can arrive',async()=>{
 const field=await openDraft();let release:((response:Response)=>void)|undefined;
 sessionRead=()=>new Promise(resolve=>{release=resolve;});
 fireEvent.click(screen.getByText('Validate session'));
 localStorage.setItem('coachify.access-epoch','newer');
 await act(async()=>{release!(new Response(JSON.stringify({id:'synthetic-id',name:'Synthetic',provider:'local_test'})));});
 expect(screen.getByTestId('account')).toHaveTextContent('signed out');expect(field).not.toBeInTheDocument();
});

test('background tabs do not poll sessions and there is no inactivity logout',async()=>{
 const field=await openDraft();await startPollingClock();vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');
 const validations=requests.filter(url=>url.endsWith('/auth/session')).length;
 await act(async()=>{await vi.advanceTimersByTimeAsync(6*60_000);});
 expect(requests.filter(url=>url.endsWith('/auth/session'))).toHaveLength(validations);
 expect(screen.getByTestId('account')).toHaveTextContent('Synthetic');expect(field).toBeVisible();expect(field).toHaveValue('My unfinished explanation');
});
