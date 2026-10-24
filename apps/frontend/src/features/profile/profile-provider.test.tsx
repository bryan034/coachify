import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { ProfileProvider, useProfile } from './profile-provider';
function Probe() {
 const s=useProfile();
 return <><p data-testid="account">{s.account?.name || 'signed out'}</p><p data-testid="profile">{s.profile?.education.course || 'empty'}</p><p data-testid="complete">{String(s.profile?.onboarding_complete)}</p><button onClick={()=>s.setProfile({version:2,onboarding_complete:true,occupational_status:'employed',school_category:null,education_context:'last',education_review_required:false,education:{course:'Newer confirmed course'}})}>Confirm completion</button><button onClick={s.reload}>Reload</button><p data-testid="loading">{String(s.loading)}</p>
 <button onClick={()=>void s.beginAccess('register').then(()=>s.completeAccess({name:'Synthetic'}))}>Create</button><button onClick={s.signOut}>Logout</button><button onClick={s.retryLogout}>Retry logout</button><p>{s.logoutError}</p></>;
}
let failedLogout=false;
let privateRead: (()=>Promise<Response>) | undefined;
let requests: string[]=[];
beforeEach(()=>{
 sessionStorage.clear(); localStorage.clear(); failedLogout=false; privateRead=undefined; requests=[];
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{
  requests.push(url);
  const value=url.endsWith('/auth-config')?{mode:'local_test'}:url.endsWith('/school-categories')?[]:url.endsWith('/auth/attempts')?{nonce:'nonce'}:url.endsWith('/auth/complete')||url.endsWith('/auth/session')?{id:'synthetic-id',name:'Synthetic',provider:'local_test',onboarding_complete:false}:url.endsWith('/auth/logout')?{ok:true}:{version:1,education:{course:'Private course'}};
  if(url.endsWith('/auth/logout')&&failedLogout)return new Response(JSON.stringify({detail:'Unavailable'}),{status:503});
  if(url.endsWith('/profile')&&privateRead)return privateRead();
  return new Response(JSON.stringify(value));
 }));
});
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
