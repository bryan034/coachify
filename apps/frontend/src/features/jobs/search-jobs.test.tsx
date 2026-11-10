import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {SearchJobs} from './search-jobs';
import {JobApplicationCheck} from './application-check';

vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({account:{id:'synthetic-account'},token:'synthetic-token'})}));
vi.mock('next/link',()=>({default:({href,children,...props}:{href:string;children:React.ReactNode})=><a href={href} {...props}>{children}</a>}));

const posting=(id:string,title:string,extra={})=>({id:id.repeat(32),title,company:'Synthetic Pay',industry:'fintech',location:'Singapore',department:'Data',job_type:'internship',workplace:'hybrid',posted_at:'2026-11-01T00:00:00Z',posted_at_estimated:false,application_deadline:null,excerpt:'Support synthetic payments analysis.',listing_url:`https://jobs.example.test/${id}`,apply_url:`https://jobs.example.test/${id}/apply`,provider:'lever',status:'open',...extra});
const options={job_types:[{value:'internship',count:2},{value:'full_time',count:1}],industries:[{value:'fintech',count:3}],workplaces:[{value:'hybrid',count:3}],companies:[{value:'Synthetic Pay',count:3}],last_synced_at:'2026-11-05T04:00:00Z'};
const application=(status:string,version:number,id='a')=>({id:'f'.repeat(32),posting_id:id.repeat(32),source:'listing',version,status,posting_status:'open',snapshot:{title:'Data Intern',company:'Synthetic Pay',location:'Singapore',job_type:'internship',listing_url:`https://jobs.example.test/${id}`,apply_url:`https://jobs.example.test/${id}/apply`},history:[],created_at:'2026-11-05T04:00:00Z',updated_at:'2026-11-05T04:00:00Z'});
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});

let search:(url:URL)=>Response;let saved:ReturnType<typeof application>[];let calls:{method:string;url:URL;body?:string}[];
beforeEach(()=>{
 calls=[];saved=[];localStorage.clear();
 search=()=>json({items:[posting('a','Data Intern'),posting('b','Backend Engineer',{job_type:'full_time',posted_at_estimated:true,application_deadline:'2026-12-01T00:00:00Z'})],total:2,next_cursor:null});
 vi.stubGlobal('fetch',vi.fn(async(input:string,init:RequestInit={})=>{
  const url=new URL(input,'http://elo.test');const method=init.method||'GET';calls.push({method,url,body:init.body as string});
  if(url.pathname.endsWith('/filters'))return json(options);
  if(url.pathname.endsWith('/external-searches')){const q=encodeURIComponent(url.searchParams.get('q')!);return json({items:[{name:'Prosple',url:`https://sg.prosple.com/search-jobs?keywords=${q}`},{name:'Huzzle',url:`https://www.huzzle.com/search/results?search=${q}&type=jobs`},{name:'LinkedIn',url:`https://www.linkedin.com/jobs/search/?keywords=${q}&location=Singapore`},{name:'Indeed',url:`https://sg.indeed.com/jobs?q=${q}&l=Singapore`},{name:'Unsafe',url:'javascript:alert(1)'}]});}
  if(url.pathname.endsWith('/applications/link')){const body=JSON.parse(init.body as string);if(body.url.includes('refused'))return json({detail:'Paste the full https:// link to the job.'},422);saved=[{...application('saved',1),id:'c'.repeat(32),source:'link',snapshot:{title:body.title,company:body.company,location:body.location,job_type:body.job_type,listing_url:body.url,apply_url:body.url}}];return json(saved[0]);}
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
const writes=()=>calls.filter(call=>call.method!=='GET');
const prompt=()=>screen.queryByRole('region',{name:'Application check'});
const VISITS='elo.job-apply-visits.synthetic-account';
const renderWithCheck=()=>render(<><SearchJobs/><JobApplicationCheck/></>);
async function visitEmployer(title:string){
 await runSearch();
 const card=(await screen.findByRole('heading',{name:title})).closest('li')!;
 const apply=within(card).getByRole('link',{name:/Apply on employer site/});
 apply.addEventListener('click',event=>event.preventDefault());
 fireEvent.click(apply);
 return card;
}
const returnToElo=()=>fireEvent.focus(window);
// Nothing is searched until the user presses Search.
const runSearch=async()=>fireEvent.click(await screen.findByRole('button',{name:'Search'}));

describe('Search Jobs',()=>{
 async function openLinkForm(){
  fireEvent.click(await screen.findByRole('button',{name:/My applications/}));
  fireEvent.click(screen.getByRole('button',{name:'+ Save a job'}));
  return within(screen.getByRole('form',{name:'Save a job from a link'}));
 }
 function fillLink(form:ReturnType<typeof within>,link:string){
  fireEvent.change(form.getByRole('textbox',{name:'Job link'}),{target:{value:link}});
  fireEvent.change(form.getByRole('textbox',{name:'Job title'}),{target:{value:'Markets Intern'}});
  fireEvent.change(form.getByRole('textbox',{name:'Employer'}),{target:{value:'Example Bank'}});
  fireEvent.change(form.getByRole('combobox',{name:'Job type'}),{target:{value:'internship'}});
 }
 it('saves a job from a pasted link onto the board',async()=>{
  render(<SearchJobs/>);
  const form=await openLinkForm();
  fillLink(form,'https://careers.example.com/roles/42');
  fireEvent.click(form.getByRole('button',{name:'Save job'}));
  expect(await screen.findByRole('heading',{name:'Markets Intern'})).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent('Saved Markets Intern.');
  expect(screen.getByText('Added from a link')).toBeVisible();
  expect(within(screen.getByRole('region',{name:'Saved'})).getByText('Example Bank')).toBeVisible();
  expect(screen.queryByRole('form',{name:'Save a job from a link'})).toBeNull();
  expect(JSON.parse(writes().at(-1)!.body!)).toEqual({url:'https://careers.example.com/roles/42',title:'Markets Intern',company:'Example Bank',location:'',job_type:'internship'});
  expect(screen.getByRole('button',{name:'My applications (1)'})).toBeVisible();
 });
 it('keeps the pasted details and shows why a link was refused',async()=>{
  render(<SearchJobs/>);
  const form=await openLinkForm();
  fillLink(form,'https://refused.example.com/a');
  fireEvent.click(form.getByRole('button',{name:'Save job'}));
  expect(await form.findByRole('alert')).toHaveTextContent('Paste the full https:// link to the job.');
  expect(form.getByRole('textbox',{name:'Job title'})).toHaveValue('Markets Intern');
  expect(form.getByRole('button',{name:'Save job'})).toBeEnabled();
 });
 it('offers to paste a link from the empty Saved column',async()=>{
  render(<SearchJobs/>);
  fireEvent.click(await screen.findByRole('button',{name:/My applications/}));
  fireEvent.click(screen.getByRole('button',{name:'Paste a job link'}));
  expect(screen.getByRole('form',{name:'Save a job from a link'})).toBeVisible();
 });
 it('shows current listings with their facts and the bearer token',async()=>{
  render(<SearchJobs/>);
  expect(screen.getByRole('heading',{level:1,name:'Search Jobs'})).toBeVisible();
  await runSearch();
  const card=(await screen.findByRole('heading',{name:'Data Intern'})).closest('li')!;
  expect(within(card).getByText('Internship')).toBeVisible();
  expect(within(card).getByText('Fintech')).toBeVisible();
  expect(within(card).getByText('Posted Sun, 1 Nov 2026')).toBeVisible();
  expect(screen.getByText('Posting date not supplied')).toBeVisible();
  expect(screen.getByText('Closes Tue, 1 Dec 2026')).toBeVisible();
  expect(screen.getByText('2 jobs in Singapore')).toBeVisible();
  const headers=(vi.mocked(fetch).mock.calls[0][1] as RequestInit).headers as Record<string,string>;
  expect(headers.Authorization).toBe('Bearer synthetic-token');
 });
 it('searches nothing on load, and sends each chosen filter only when Search is pressed',async()=>{
  render(<SearchJobs/>);
  await screen.findByRole('checkbox',{name:'Internship (2)'});
  expect(searches()).toHaveLength(0);
  expect(screen.getByText('Choose your filters, then press Search')).toBeVisible();
  expect(screen.queryByText(/No jobs are listed/)).toBeNull();
  fireEvent.click(screen.getByRole('checkbox',{name:'Internship (2)'}));
  fireEvent.click(screen.getByRole('checkbox',{name:'Full-time (1)'}));
  fireEvent.click(screen.getByRole('checkbox',{name:'Fintech (3)'}));
  fireEvent.change(screen.getByRole('combobox',{name:'Work arrangement'}),{target:{value:'hybrid'}});
  fireEvent.change(screen.getByRole('combobox',{name:'Employer'}),{target:{value:'Synthetic Pay'}});
  fireEvent.change(screen.getByRole('combobox',{name:'Date posted'}),{target:{value:'7'}});
  fireEvent.change(screen.getByRole('combobox',{name:'Sort results'}),{target:{value:'newest'}});
  expect(searches()).toHaveLength(0);
  await runSearch();
  await waitFor(()=>expect(searches()).toHaveLength(1));
  const sent=lastSearch();
  expect(sent.getAll('job_type')).toEqual(['internship','full_time']);
  expect(sent.getAll('industry')).toEqual(['fintech']);
  expect(sent.getAll('workplace')).toEqual(['hybrid']);
  expect(sent.getAll('company')).toEqual(['Synthetic Pay']);
  expect(sent.get('posted_within_days')).toBe('7');
  expect(sent.get('sort')).toBe('newest');
  // Editing a filter after a search does not search again until Search is pressed.
  fireEvent.click(screen.getByRole('checkbox',{name:'Fintech (3)'}));
  expect(searches()).toHaveLength(1);
  // Clearing filters returns to the waiting state instead of searching.
  fireEvent.click(screen.getByRole('button',{name:'Clear filters'}));
  expect(searches()).toHaveLength(1);
  expect(await screen.findByText('Choose your filters, then press Search')).toBeVisible();
  await runSearch();
  // Sort is a display order, not a filter: clearing filters keeps the chosen order.
  await waitFor(()=>expect([...lastSearch().entries()]).toEqual([['sort','newest']]));
 });
 it('supports a custom posted date range',async()=>{
  render(<SearchJobs/>);
  await runSearch();
  await screen.findByRole('heading',{name:'Data Intern'});
  expect(screen.queryByLabelText('Posted from')).toBeNull();
  fireEvent.change(screen.getByRole('combobox',{name:'Date posted'}),{target:{value:'custom'}});
  fireEvent.change(screen.getByLabelText('Posted from'),{target:{value:'2026-10-01'}});
  fireEvent.change(screen.getByLabelText('Posted to'),{target:{value:'2026-10-31'}});
  await runSearch();
  await waitFor(()=>{expect(lastSearch().get('posted_from')).toBe('2026-10-01');expect(lastSearch().get('posted_to')).toBe('2026-10-31');});
  expect(lastSearch().get('posted_within_days')).toBeNull();
 });
 it('searches keywords on submit and shows the service\'s external links without browser storage',async()=>{
  const storage=vi.spyOn(Storage.prototype,'setItem');
  render(<SearchJobs/>);
  await runSearch();
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
  expect(screen.getByRole('link',{name:/Prosple/})).toHaveAttribute('href','https://sg.prosple.com/search-jobs?keywords=C%2B%2B%20%26%20SQL%20%231');
  expect(screen.getByRole('link',{name:/Huzzle/})).toBeVisible();
  expect(screen.queryByRole('link',{name:/Unsafe/})).toBeNull();
  expect(storage).not.toHaveBeenCalled();
 });
 it('records nothing for an employer visit and asks only once the user returns',async()=>{
  renderWithCheck();
  const card=await visitEmployer('Data Intern');
  const apply=within(card).getByRole('link',{name:/Apply on employer site/});
  expect(apply).toHaveAttribute('href','https://jobs.example.test/a/apply');
  expect(apply).toHaveAttribute('target','_blank');expect(apply).toHaveAttribute('rel','noopener noreferrer');
  expect(prompt()).toBeNull();
  expect(writes()).toEqual([]);
  expect(within(card).queryByText(/in My applications/)).toBeNull();
  returnToElo();
  expect(await screen.findByText(/Did you apply to/)).toHaveTextContent('Did you apply to Data Intern at Synthetic Pay?');
  expect(writes()).toEqual([]);
 });
 it('marks the job applied when the user says yes',async()=>{
  renderWithCheck();
  const card=await visitEmployer('Data Intern');
  returnToElo();
  fireEvent.click(await screen.findByRole('button',{name:'Yes, I applied'}));
  await within(card).findByText('Applied in My applications');
  expect(JSON.parse(calls.find(call=>call.method==='PATCH')!.body!)).toEqual({expected_version:1,status:'applied'});
  expect(screen.getByRole('button',{name:'My applications (1)'})).toBeVisible();
  expect(prompt()).toBeNull();
  expect(localStorage.getItem(VISITS)).toBeNull();
 });
 it('records nothing and stops asking when the user says no',async()=>{
  renderWithCheck();
  const card=await visitEmployer('Data Intern');
  returnToElo();
  fireEvent.click(await screen.findByRole('button',{name:'No'}));
  expect(prompt()).toBeNull();
  returnToElo();
  expect(prompt()).toBeNull();
  expect(writes()).toEqual([]);
  expect(within(card).getByRole('button',{name:'Save job'})).toBeVisible();
  expect(screen.getByRole('button',{name:'My applications (0)'})).toBeVisible();
  expect(localStorage.getItem(VISITS)).toBeNull();
 });
 it('asks about each visited job in turn',async()=>{
  renderWithCheck();
  await visitEmployer('Data Intern');
  await visitEmployer('Backend Engineer');
  returnToElo();
  expect(await screen.findByText(/Did you apply to/)).toHaveTextContent('Data Intern');
  fireEvent.click(screen.getByRole('button',{name:'No'}));
  expect(await screen.findByText(/Did you apply to/)).toHaveTextContent('Backend Engineer');
  fireEvent.click(screen.getByRole('button',{name:'No'}));
  expect(prompt()).toBeNull();
 });
 it('still asks after a reload and on any workspace page, for the same account only',async()=>{
  const view=renderWithCheck();
  await visitEmployer('Data Intern');
  view.unmount();
  localStorage.setItem('elo.job-apply-visits.another-account',JSON.stringify([{id:'b'.repeat(32),title:'Other Account Role',company:'Synthetic Pay'}]));
  render(<JobApplicationCheck/>);
  expect(await screen.findByText(/Did you apply to/)).toHaveTextContent('Data Intern');
  expect(screen.queryByText('Other Account Role')).toBeNull();
 });
 it('ignores unreadable stored visits',async()=>{
  localStorage.setItem(VISITS,'not-json');
  render(<JobApplicationCheck/>);
  await waitFor(()=>expect(prompt()).toBeNull());
 });
 it('keeps asking when recording the application fails, then succeeds on retry',async()=>{
  renderWithCheck();
  await visitEmployer('Data Intern');
  returnToElo();
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementationOnce(async()=>json({detail:'Storage is unavailable.',code:'storage'},503));
  fireEvent.click(await screen.findByRole('button',{name:'Yes, I applied'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Storage is unavailable.');
  expect(localStorage.getItem(VISITS)).toContain('a'.repeat(32));
  vi.mocked(fetch).mockImplementation(original);
  fireEvent.click(screen.getByRole('button',{name:'Yes, I applied'}));
  await waitFor(()=>expect(prompt()).toBeNull());
  expect(screen.getByRole('button',{name:'My applications (1)'})).toBeVisible();
 });
 it('promotes an already saved job on yes and leaves a further status alone',async()=>{
  saved=[application('saved',1)];
  const view=renderWithCheck();
  await runSearch();
  await screen.findByText('Saved in My applications');
  await visitEmployer('Data Intern');
  returnToElo();
  fireEvent.click(await screen.findByRole('button',{name:'Yes, I applied'}));
  await screen.findByText('Applied in My applications');
  view.unmount();
  saved=[application('interviewing',3)];
  renderWithCheck();
  await runSearch();
  await screen.findByText('Interviewing in My applications');
  await visitEmployer('Data Intern');
  returnToElo();
  expect(prompt()).toBeNull();
  expect(localStorage.getItem(VISITS)).toBeNull();
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
  await runSearch();
  fireEvent.click(await screen.findByRole('button',{name:'Show more jobs'}));
  await screen.findByRole('heading',{name:'Third Role'});
  expect(screen.getByRole('heading',{name:'Data Intern'})).toBeVisible();
  expect(lastSearch().get('cursor')).toBe('next-page');
  expect(screen.queryByRole('button',{name:'Show more jobs'})).toBeNull();
 });
 it('offers each HTTPS listing as a career goal through the review intake',async()=>{
  search=()=>json({items:[posting('a','Data Intern')],total:1,next_cursor:null});
  render(<SearchJobs/>);
  await runSearch();
  const card=(await screen.findByRole('heading',{name:'Data Intern'})).closest('li')!;
  const use=within(card).getByRole('link',{name:'Use as career goal'});
  expect(new URLSearchParams(use.getAttribute('href')!.split('?')[1]).get('job_url')).toMatch(/^https:\/\//);
  expect(use.getAttribute('href')).toMatch(/^\/career-goal\?new=1&/);
 });
 it('never renders a non-HTTPS link from a listing',async()=>{
  search=()=>json({items:[posting('a','Unsafe Role',{apply_url:'javascript:alert(1)',listing_url:'http://jobs.example.test/a'})],total:1,next_cursor:null});
  render(<SearchJobs/>);
  await runSearch();
  const card=(await screen.findByRole('heading',{name:'Unsafe Role'})).closest('li')!;
  expect(within(card).queryByRole('link')).toBeNull();
 });
 it('recovers from a failed search with retry',async()=>{
  let attempts=0;
  search=()=>++attempts===1?json({detail:'Storage is unavailable.',code:'storage'},503):json({items:[posting('a','Data Intern')],total:1,next_cursor:null});
  render(<SearchJobs/>);
  await runSearch();
  expect(await screen.findByRole('alert')).toHaveTextContent('Storage is unavailable.');
  fireEvent.click(screen.getByRole('button',{name:'Retry'}));
  await screen.findByRole('heading',{name:'Data Intern'});
  expect(screen.queryByRole('alert')).toBeNull();
 });
 it('treats a malformed response as a recoverable error',async()=>{
  search=()=>json({items:'not-a-list'});
  render(<SearchJobs/>);
  await runSearch();
  expect(await screen.findByRole('alert')).toHaveTextContent('unexpected response');
 });
 it('shows partial provider failures alongside usable listings',async()=>{
  search=()=>json({items:[posting('a','Live Intern')],total:1,next_cursor:null,unavailable_sources:['lever:synthetic']});
  render(<SearchJobs/>);
  await runSearch();
  await screen.findByRole('heading',{name:'Live Intern'});
  expect(screen.getByRole('status')).toHaveTextContent('Results may be incomplete');
 });
 it('fetches again when the same search is submitted',async()=>{
  render(<SearchJobs/>);
  await runSearch();
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
  await runSearch();
  await screen.findByRole('heading',{name:'Data Intern'});
  fireEvent.click(screen.getByRole('button',{name:'My applications (1)'}));
  expect(screen.getByText('Check employer site for availability')).toBeVisible();
  expect(screen.queryByText('No longer listed')).not.toBeInTheDocument();
 });
 it('explains empty live results and an empty filter result differently',async()=>{
  search=()=>json({items:[],total:0,next_cursor:null});
  render(<SearchJobs/>);
  await runSearch();
  await screen.findByText('No jobs are listed right now.');
  fireEvent.change(screen.getByRole('combobox',{name:'Date posted'}),{target:{value:'1'}});
  await runSearch();
  await screen.findByText(/No jobs match these filters/);
 });
});
