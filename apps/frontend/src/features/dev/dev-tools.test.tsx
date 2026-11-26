import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {DevTools} from './dev-tools';
let accountType:'free'|'premium'|undefined;let enabled=true;
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({developmentToolsEnabled:enabled,token:'synthetic-marker',account:{id:'synthetic-id',name:'Synthetic user',provider:'email',account_type:accountType}})}));
const reload=vi.fn(),assign=vi.fn();
beforeEach(()=>{
 accountType=undefined;enabled=true;reload.mockReset();assign.mockReset();
 vi.stubGlobal('location',{...window.location,reload,assign});
});
afterEach(()=>{vi.unstubAllGlobals();localStorage.clear();sessionStorage.clear();});

it('shows the current plan and switches to the other one',async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response('{"account_type":"premium"}',{status:200}));vi.stubGlobal('fetch',fetch);
 render(<DevTools/>);
 expect(screen.getByRole('region',{name:'Development tools'})).toHaveTextContent('Account: Free');
 fireEvent.click(screen.getByRole('button',{name:'Switch to Premium'}));
 await waitFor(()=>expect(reload).toHaveBeenCalled());
 const [url,init]=fetch.mock.calls[0];
 expect(url).toBe('/api/v1/profile/dev/account-type');
 expect(init.method).toBe('PUT');expect(JSON.parse(init.body)).toEqual({account_type:'premium'});
});

it('offers Free to a Premium account and reports a disabled route without reloading',async()=>{
 accountType='premium';
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('',{status:404})));
 render(<DevTools/>);
 expect(screen.getByRole('region',{name:'Development tools'})).toHaveTextContent('Account: Premium');
 fireEvent.click(screen.getByRole('button',{name:'Switch to Free'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Plan switching is not enabled');
 expect(reload).not.toHaveBeenCalled();
});

it('starts afresh by resetting every service and forgetting this browser’s pending career and job memory',async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response('{"deleted":{}}',{status:200}));vi.stubGlobal('fetch',fetch);
 localStorage.setItem('elo.job-apply-visits.synthetic-id','[{"id":"job","title":"Analyst","company":"Synthetic"}]');
 sessionStorage.setItem('elo-career-extraction','{"owner":"synthetic-id"}');
 render(<DevTools/>);
 fireEvent.click(screen.getByRole('button',{name:'Start afresh'}));
 fireEvent.click(screen.getByRole('button',{name:'Yes, delete everything'}));
 await waitFor(()=>expect(assign).toHaveBeenCalledWith('/dashboard'));
 expect(fetch.mock.calls.map(([url])=>url).sort()).toEqual(['assessments','career','cv','jobs','profile','roadmaps'].map(prefix=>`/api/v1/${prefix}/dev/reset`));
 expect(localStorage.getItem('elo.job-apply-visits.synthetic-id')).toBeNull();
 expect(sessionStorage.getItem('elo-career-extraction')).toBeNull();
});

it('renders nothing outside development',()=>{
 enabled=false;
 const {container}=render(<DevTools/>);
 expect(container).toBeEmptyDOMElement();
});
