import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {SearchJobs} from './search-jobs';

vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({account:{id:'synthetic-account'},token:'synthetic-token'})}));
vi.mock('next/link',()=>({default:({href,children,...props}:{href:string;children:React.ReactNode})=><a href={href} {...props}>{children}</a>}));

const posting=(id:string,title:string,extra={})=>({id:id.repeat(32),title,company:'Synthetic Pay',industry:'fintech',location:'Singapore',department:'Data',job_type:'internship',workplace:'hybrid',posted_at:'2026-11-01T00:00:00Z',posted_at_estimated:false,application_deadline:null,excerpt:'Support synthetic payments analysis.',listing_url:`https://jobs.example.test/${id}`,apply_url:`https://jobs.example.test/${id}/apply`,provider:'lever',status:'open',...extra});
const options={job_types:[{value:'internship',count:2},{value:'full_time',count:1}],industries:[{value:'fintech',count:3}],workplaces:[{value:'hybrid',count:3}],companies:[{value:'Synthetic Pay',count:3}],last_synced_at:'2026-11-05T04:00:00Z'};
const application=(status:string,version:number,id='a')=>({id:'f'.repeat(32),posting_id:id.repeat(32),version,status,posting_status:'open',snapshot:{title:'Data Intern',company:'Synthetic Pay',location:'Singapore',job_type:'internship',listing_url:`https://jobs.example.test/${id}`,apply_url:`https://jobs.example.test/${id}/apply`},history:[],created_at:'2026-11-05T04:00:00Z',updated_at:'2026-11-05T04:00:00Z'});
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});

let search:(url:URL)=>Response;let saved:ReturnType<typeof application>[];let calls:{method:string;url:URL;body?:string}[];
beforeEach(()=>{
 calls=[];saved=[];
 search=()=>json({items:[posting('a','Data Intern'),posting('b','Backend Engineer',{job_type:'full_time',posted_at_estimated:true,application_deadline:'2026-12-01T00:00:00Z'})],total:2,next_cursor:null});
 vi.stubGlobal('fetch',vi.fn(async(input:string,init:RequestInit={})=>{
  const url=new URL(input,'http://elo.test');const method=init.method||'GET';calls.push({method,url,body:init.body as string});
  if(url.pathname.endsWith('/filters'))return json(options);
  if(url.pathname.endsWith('/search'))return search(url);
  if(url.pathname.endsWith('/applications')&&method==='GET')return json({items:saved});
  if(url.pathname.endsWith('/applications')&&method==='POST'){saved=[application('saved',1)];return json(saved[0]);}
  if(method==='PATCH'){const body=JSON.parse(init.body as string);saved=[application(body.status,body.expected_version+1)];return json(saved[0]);}
  if(method==='DELETE'){saved=[];return new Response(null,{status:204});}
  return json({detail:'Unexpected'},500);
 }));
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

const searches=()=>calls.filter(call=>call.url.pathname.endsWith('/search'));
const lastSearch=()=>searches().at(-1)!.url.searchParams;

describe('Search Jobs',()=>{
 it('shows current listings with their facts and the bearer token',async()=>{
  render(<SearchJobs/>);
  expect(screen.getByRole('heading',{level:1,name:'Search Jobs'})).toBeVisible();
  const card=(await screen.findByRole('heading',{name:'Data Intern'})).closest('li')!;
  expect(within(card).getByText('Internship')).toBeVisible();
  expect(within(card).getByText('Fintech')).toBeVisible();
  expect(within(card).getByText('Posted 1 Nov 2026')).toBeVisible();
  expect(screen.getByText('Posting date not supplied')).toBeVisible();
  expect(screen.getByText('Closes 1 Dec 2026')).toBeVisible();
  expect(screen.getByText('2 jobs in Singapore')).toBeVisible();
  const headers=(vi.mocked(fetch).mock.calls[0][1] as RequestInit).headers as Record<string,string>;
  expect(headers.Authorization).toBe('Bearer synthetic-token');
 });
 it('sends each chosen filter to the service',async()=>{
  render(<SearchJobs/>);
  await screen.findByRole('checkbox',{name:'Internship (2)'});
  fireEvent.click(screen.getByRole('checkbox',{name:'Internship (2)'}));
  await waitFor(()=>expect(lastSearch().getAll('job_type')).toEqual(['internship']));
  fireEvent.click(screen.getByRole('checkbox',{name:'Full-time (1)'}));
  await waitFor(()=>expect(lastSearch().getAll('job_type')).toEqual(['internship','full_time']));
  fireEvent.click(screen.getByRole('checkbox',{name:'Fintech (3)'}));
  await waitFor(()=>expect(lastSearch().getAll('industry')).toEqual(['fintech']));
  fireEvent.change(screen.getByRole('combobox',{name:'Work arrangement'}),{target:{value:'hybrid'}});
  await waitFor(()=>expect(lastSearch().getAll('workplace')).toEqual(['hybrid']));
  fireEvent.change(screen.getByRole('combobox',{name:'Employer'}),{target:{value:'Synthetic Pay'}});
  await waitFor(()=>expect(lastSearch().getAll('company')).toEqual(['Synthetic Pay']));
  fireEvent.change(screen.getByRole('combobox',{name:'Date posted'}),{target:{value:'7'}});
  await waitFor(()=>expect(lastSearch().get('posted_within_days')).toBe('7'));
  fireEvent.click(screen.getByRole('button',{name:'Clear filters'}));
  await waitFor(()=>expect([...lastSearch().keys()]).toEqual([]));
 });
 it('supports a custom posted date range',async()=>{
  render(<SearchJobs/>);
  await screen.findByRole('heading',{name:'Data Intern'});
  expect(screen.queryByLabelText('Posted from')).toBeNull();
  fireEvent.change(screen.getByRole('combobox',{name:'Date posted'}),{target:{value:'custom'}});
  fireEvent.change(screen.getByLabelText('Posted from'),{target:{value:'2026-10-01'}});
  fireEvent.change(screen.getByLabelText('Posted to'),{target:{value:'2026-10-31'}});
  await waitFor(()=>{expect(lastSearch().get('posted_from')).toBe('2026-10-01');expect(lastSearch().get('posted_to')).toBe('2026-10-31');});
  expect(lastSearch().get('posted_within_days')).toBeNull();
 });
 it('searches keywords on submit and builds encoded external links without browser storage',async()=>{
  const storage=vi.spyOn(Storage.prototype,'setItem');
  render(<SearchJobs/>);
  await screen.findByRole('heading',{name:'Data Intern'});
  expect(screen.queryByRole('link',{name:/LinkedIn/})).toBeNull();
  const before=searches().length;
  fireEvent.change(screen.getByRole('textbox',{name:'Job title or keywords'}),{target:{value:'  C++ & SQL #1  '}});
  expect(searches()).toHaveLength(before);
  fireEvent.click(screen.getByRole('button',{name:'Search'}));
  await waitFor(()=>expect(lastSearch().get('q')).toBe('C++ & SQL #1'));
  const linkedin=await screen.findByRole('link',{name:/LinkedIn/}),indeed=screen.getByRole('link',{name:/Indeed/});
  const first=new URL(linkedin.getAttribute('href')!),second=new URL(indeed.getAttribute('href')!);
  expect(first.origin+first.pathname).toBe('https://www.linkedin.com/jobs/search/');
  expect(first.searchParams.get('keywords')).toBe('C++ & SQL #1');
  expect(first.searchParams.get('location')).toBe('Singapore');
  expect(second.origin+second.pathname).toBe('https://sg.indeed.com/jobs');
  expect(second.searchParams.get('q')).toBe('C++ & SQL #1');
  for(const link of [linkedin,indeed]){expect(link).toHaveAttribute('target','_blank');expect(link).toHaveAttribute('rel','noopener noreferrer');}
  expect(storage).not.toHaveBeenCalled();
  expect(screen.getByRole('link',{name:/Use its job description/})).toHaveAttribute('href','/career-goal?new=1');
 });
 it('opens the employer form, saves the job and marks it applied only after the user confirms',async()=>{
  render(<SearchJobs/>);
  const card=(await screen.findByRole('heading',{name:'Data Intern'})).closest('li')!;
  const apply=within(card).getByRole('link',{name:/Apply on employer site/});
  expect(apply).toHaveAttribute('href','https://jobs.example.test/a/apply');
  expect(apply).toHaveAttribute('target','_blank');expect(apply).toHaveAttribute('rel','noopener noreferrer');
  apply.addEventListener('click',event=>event.preventDefault());
  fireEvent.click(apply);
  await within(card).findByText('Saved in My applications');
  expect(calls.some(call=>call.method==='PATCH')).toBe(false);
  fireEvent.click(within(card).getByRole('button',{name:'Yes, mark as applied'}));
  await within(card).findByText('Applied in My applications');
  expect(JSON.parse(calls.find(call=>call.method==='PATCH')!.body!)).toEqual({expected_version:1,status:'applied'});
  expect(within(card).queryByText('Did you submit your application?')).toBeNull();
 });
 it('leaves the job as saved when the user has not submitted',async()=>{
  render(<SearchJobs/>);
  const card=(await screen.findByRole('heading',{name:'Data Intern'})).closest('li')!;
  const apply=within(card).getByRole('link',{name:/Apply on employer site/});
  apply.addEventListener('click',event=>event.preventDefault());
  fireEvent.click(apply);
  fireEvent.click(await within(card).findByRole('button',{name:'Not yet'}));
  await within(card).findByText('Saved in My applications');
  expect(calls.some(call=>call.method==='PATCH')).toBe(false);
 });
 it('tracks, updates and removes saved jobs',async()=>{
  saved=[application('saved',1)];
  render(<SearchJobs/>);
  fireEvent.click(await screen.findByRole('button',{name:'My applications (1)'}));
  const status=screen.getByRole('combobox',{name:'Status'});
  fireEvent.change(status,{target:{value:'interviewing'}});
  await waitFor(()=>expect(screen.getByRole('combobox',{name:'Status'})).toHaveValue('interviewing'));
  expect(JSON.parse(calls.find(call=>call.method==='PATCH')!.body!)).toEqual({expected_version:1,status:'interviewing'});
  fireEvent.click(screen.getByRole('button',{name:'Remove Data Intern'}));
  await screen.findByText(/haven.t saved any jobs/);
  expect(calls.find(call=>call.method==='DELETE')!.url.search).toBe('?expected_version=2');
 });
 it('shows a stale update and reloads the saved state',async()=>{
  saved=[application('saved',1)];
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>(init as RequestInit|undefined)?.method==='PATCH'?(saved=[application('offer',5)],json({detail:'This saved job changed in another session. Reload and retry.',code:'conflict'},409)):original(input,init));
  render(<SearchJobs/>);
  fireEvent.click(await screen.findByRole('button',{name:'My applications (1)'}));
  fireEvent.change(screen.getByRole('combobox',{name:'Status'}),{target:{value:'rejected'}});
  expect(await screen.findByRole('alert')).toHaveTextContent('changed in another session');
  await waitFor(()=>expect(screen.getByRole('combobox',{name:'Status'})).toHaveValue('offer'));
 });
 it('loads further pages with the cursor and keeps the current filters',async()=>{
  search=url=>url.searchParams.get('cursor')?json({items:[posting('c','Third Role')],total:2,next_cursor:null}):json({items:[posting('a','Data Intern')],total:2,next_cursor:'next-page'});
  render(<SearchJobs/>);
  fireEvent.click(await screen.findByRole('button',{name:'Show more jobs'}));
  await screen.findByRole('heading',{name:'Third Role'});
  expect(screen.getByRole('heading',{name:'Data Intern'})).toBeVisible();
  expect(lastSearch().get('cursor')).toBe('next-page');
  expect(screen.queryByRole('button',{name:'Show more jobs'})).toBeNull();
 });
 it('never renders a non-HTTPS link from a listing',async()=>{
  search=()=>json({items:[posting('a','Unsafe Role',{apply_url:'javascript:alert(1)',listing_url:'http://jobs.example.test/a'})],total:1,next_cursor:null});
  render(<SearchJobs/>);
  const card=(await screen.findByRole('heading',{name:'Unsafe Role'})).closest('li')!;
  expect(within(card).queryByRole('link')).toBeNull();
 });
 it('recovers from a failed search with retry',async()=>{
  let attempts=0;
  search=()=>++attempts===1?json({detail:'Storage is unavailable.',code:'storage'},503):json({items:[posting('a','Data Intern')],total:1,next_cursor:null});
  render(<SearchJobs/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Storage is unavailable.');
  fireEvent.click(screen.getByRole('button',{name:'Retry'}));
  await screen.findByRole('heading',{name:'Data Intern'});
  expect(screen.queryByRole('alert')).toBeNull();
 });
 it('treats a malformed response as a recoverable error',async()=>{
  search=()=>json({items:'not-a-list'});
  render(<SearchJobs/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('unexpected response');
 });
 it('shows partial provider failures alongside usable listings',async()=>{
  search=()=>json({items:[posting('a','Live Intern')],total:1,next_cursor:null,unavailable_sources:['lever:synthetic']});
  render(<SearchJobs/>);
  await screen.findByRole('heading',{name:'Live Intern'});
  expect(screen.getByRole('status')).toHaveTextContent('Results may be incomplete');
 });
 it('fetches again when the same search is submitted',async()=>{
  render(<SearchJobs/>);
  await screen.findByRole('heading',{name:'Data Intern'});
  const before=searches().length;
  search=()=>json({items:[posting('c','New live job')],total:1,next_cursor:null});
  fireEvent.click(screen.getByRole('button',{name:'Search'}));
  await screen.findByRole('heading',{name:'New live job'});
  expect(searches().length).toBeGreaterThan(before);
 });
 it('keeps saved applications readable without claiming current availability',async()=>{
  saved=[{...application('saved',1),posting_status:'unknown'}];
  render(<SearchJobs/>);
  await screen.findByRole('heading',{name:'Data Intern'});
  fireEvent.click(screen.getByRole('button',{name:'My applications (1)'}));
  expect(screen.getByText('Check employer site for availability')).toBeVisible();
  expect(screen.queryByText('No longer listed')).not.toBeInTheDocument();
 });
 it('explains empty live results and an empty filter result differently',async()=>{
  search=()=>json({items:[],total:0,next_cursor:null});
  render(<SearchJobs/>);
  await screen.findByText('No jobs are listed right now.');
  fireEvent.change(screen.getByRole('combobox',{name:'Date posted'}),{target:{value:'1'}});
  await screen.findByText(/No jobs match these filters/);
 });
});
