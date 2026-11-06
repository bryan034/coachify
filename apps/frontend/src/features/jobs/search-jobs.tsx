"use client";
import {useCallback,useEffect,useMemo,useRef,useState,type FormEvent} from 'react';
import Link from 'next/link';
import {Icon} from '@/components/ui/icon';
import {useProfile} from '@/features/profile/profile-provider';
import {JobsError,externalSearches,listApplications,readJobFilters,removeApplication,saveApplication,saveJobLink,searchJobs,updateApplication,
 type Application,type ApplicationStatus,type ExternalSearch,type FilterOption,type FilterOptions,type JobFilters,type JobLink,type JobType,type Posting} from '@/lib/api/jobs';
import {loadGoal,useSection} from '@/lib/api/workspace-summary';
import {APPLICATION_RECORDED,noteApplyVisit} from './application-check';
import '@/styles/jobs.css';

const JOB_TYPES:Record<string,string>={internship:'Internship',graduate:'Graduate programme',full_time:'Full-time',part_time:'Part-time',contract:'Contract',temporary:'Temporary',unknown:'Not stated'};
const WORKPLACES:Record<string,string>={onsite:'On-site',hybrid:'Hybrid',remote:'Remote',unknown:'Not stated'};
const INDUSTRIES:Record<string,string>={artificial_intelligence:'Artificial intelligence',consumer_internet:'Consumer internet',crypto:'Crypto',financial_services:'Financial services',fintech:'Fintech',gaming:'Gaming',logistics:'Logistics',technology:'Technology'};
const STATUSES:Record<ApplicationStatus,string>={saved:'Saved',applied:'Applied',interviewing:'Interviewing',offer:'Offer',rejected:'Rejected',withdrawn:'Withdrawn'};
const PROVIDERS:Record<string,string>={greenhouse:'Greenhouse',lever:'Lever',ashby:'Ashby'};
const POSTED:[string,string][]=[['any','Any time'],['1','Past 24 hours'],['7','Past 7 days'],['30','Past 30 days'],['custom','Choose dates']];

type Choices={jobTypes:string[];industries:string[];workplace:string;company:string;posted:string;from:string;to:string};
const NO_CHOICES:Choices={jobTypes:[],industries:[],workplace:'',company:'',posted:'any',from:'',to:''};

const label=(names:Record<string,string>,value:string)=>names[value]??value;
const explanation=(error:unknown)=>error instanceof JobsError?error.message:'The job service is temporarily unavailable. Retry shortly.';
const day=(value:string)=>new Intl.DateTimeFormat('en-SG',{day:'numeric',month:'short',year:'numeric',timeZone:'Asia/Singapore'}).format(new Date(value));
const httpsOnly=(url:string)=>url.startsWith('https://')?url:undefined;

function toFilters(q:string,choices:Choices):JobFilters{
 return {q:q||undefined,job_type:choices.jobTypes,industry:choices.industries,
  workplace:choices.workplace?[choices.workplace]:[],company:choices.company?[choices.company]:[],
  posted_within_days:/^\d+$/.test(choices.posted)?Number(choices.posted):undefined,
  posted_from:choices.posted==='custom'?choices.from:undefined,posted_to:choices.posted==='custom'?choices.to:undefined};
}

export function SearchJobs(){
 const {account,token}=useProfile();
 if(!account||!token)return null;
 return <JobSearch key={`${account.id}:${token}`} accountId={account.id} token={token}/>;
}

function JobSearch({accountId,token}:{accountId:string;token:string}){
 const [tab,setTab]=useState<'search'|'tracker'>('search');
 const [draft,setDraft]=useState('');const [keywords,setKeywords]=useState('');
 const [choices,setChoices]=useState(NO_CHOICES);
 const [options,setOptions]=useState<FilterOptions|null>(null);
 const [items,setItems]=useState<Posting[]>([]);const [total,setTotal]=useState(0);const [cursor,setCursor]=useState<string|null>(null);
 const [unavailable,setUnavailable]=useState<string[]>([]);
 const [loading,setLoading]=useState(true);const [more,setMore]=useState(false);const [error,setError]=useState('');
 const [applications,setApplications]=useState<Application[]>([]);const [trackerError,setTrackerError]=useState('');
 const [retry,setRetry]=useState(0);
 const filters=useMemo(()=>toFilters(keywords,choices),[keywords,choices]);
 const latest=useRef(0);
 const goal=useSection(loadGoal,token);
 const [sites,setSites]=useState<ExternalSearch[]>([]);

 useEffect(()=>{
  const controller=new AbortController();
  readJobFilters(token,controller.signal).then(setOptions).catch(()=>{});
  listApplications(token,controller.signal).then(setApplications).catch(problem=>{if(!controller.signal.aborted)setTrackerError(explanation(problem));});
  return ()=>controller.abort();
 },[token,retry]);

 useEffect(()=>{
  const controller=new AbortController();const request=++latest.current;
  setLoading(true);setError('');
  searchJobs(token,filters,controller.signal).then(result=>{
   if(request!==latest.current)return;
   setUnavailable(result.unavailable_sources??[]);setItems(result.items);setTotal(result.total);setCursor(result.next_cursor);setLoading(false);
  }).catch(problem=>{
   if(request!==latest.current||controller.signal.aborted)return;
   setItems([]);setTotal(0);setCursor(null);setError(explanation(problem));setLoading(false);
  });
  return ()=>controller.abort();
 },[token,filters,retry]);

 useEffect(()=>{
  if(!keywords){setSites([]);return;}
  const controller=new AbortController();
  // These links are optional, so a failure only hides them and never interrupts the search.
  externalSearches(token,keywords,controller.signal).then(setSites).catch(()=>{if(!controller.signal.aborted)setSites([]);});
  return ()=>controller.abort();
 },[token,keywords]);

 async function loadMore(){
  if(!cursor)return;
  const request=latest.current;setMore(true);setError('');
  try{
   const result=await searchJobs(token,{...filters,cursor});
   if(request!==latest.current)return;
   setUnavailable(result.unavailable_sources??[]);setItems(current=>Array.from(new Map([...current,...result.items].map(item=>[item.id,item])).values()));setCursor(result.next_cursor);setTotal(result.total);
  }catch(problem){if(request===latest.current)setError(explanation(problem));}
  finally{if(request===latest.current)setMore(false);}
 }

 const tracked=useMemo(()=>new Map(applications.map(item=>[item.posting_id,item])),[applications]);
 const remember=useCallback((item:Application)=>setApplications(current=>[item,...current.filter(other=>other.id!==item.id)]),[]);
 const recover=useCallback(async(problem:unknown)=>{
  setTrackerError(explanation(problem));
  if(problem instanceof JobsError&&(problem.status===409||problem.status===404))setApplications(await listApplications(token).catch(()=>applications));
 },[token,applications]);

 useEffect(()=>{
  const recorded=(event:Event)=>remember((event as CustomEvent<Application>).detail);
  window.addEventListener(APPLICATION_RECORDED,recorded);
  return ()=>window.removeEventListener(APPLICATION_RECORDED,recorded);
 },[remember]);

 async function save(posting:Posting){
  setTrackerError('');
  try{remember(await saveApplication(token,posting.id));}catch(problem){await recover(problem);}
 }
 function visitEmployer(posting:Posting){
  const status=tracked.get(posting.id)?.status;
  if(!status||status==='saved')noteApplyVisit(accountId,posting);
 }
 async function changeStatus(item:Application,status:ApplicationStatus){
  setTrackerError('');
  try{remember(await updateApplication(token,item,status));}catch(problem){await recover(problem);}
 }
 async function remove(item:Application){
  setTrackerError('');
  try{await removeApplication(token,item);setApplications(current=>current.filter(other=>other.id!==item.id));}catch(problem){await recover(problem);}
 }
 function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();setKeywords(draft.trim());setRetry(value=>value+1);}
 function change(next:Partial<Choices>){setChoices(current=>({...current,...next}));}
 function tryTerm(term:string){setDraft(term);setKeywords(term);setTab('search');setRetry(value=>value+1);}
 function clear(){setDraft('');setKeywords('');setChoices(NO_CHOICES);}
 const goalTerms=goal.state.status==='ready'&&goal.state.data.goal?[goal.state.data.goal.role,...goal.state.data.goal.skills.filter(skill=>skill.priority==='required').map(skill=>skill.name),...goal.state.data.goal.skills.filter(skill=>skill.priority!=='required').map(skill=>skill.name)].slice(0,4):[];
 const filtered=Boolean(keywords)||JSON.stringify(choices)!==JSON.stringify(NO_CHOICES);

 return <section className="page on job-search-page">
  <div className="job-hero">
   <h1>Search Jobs</h1>
   <p className="job-search-intro">Find jobs and internships in Singapore, then apply on the employer&rsquo;s own site. Elo tracks your progress and sends nothing to employers.</p>
   <form className="job-search-form" onSubmit={submit}>
    <label htmlFor="job-keywords"><Icon name="search"/><span className="cv-visually-hidden">Job title or keywords</span><input id="job-keywords" name="keywords" value={draft} maxLength={120} placeholder="Job title or keywords" onChange={event=>setDraft(event.target.value)}/></label>
    <span className="job-search-place"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 21s7-6.1 7-11.5a7 7 0 1 0-14 0C5 14.9 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>Singapore</span>
    <button className="btn job-find">Search</button>
   </form>
   {goalTerms.length>0&&<div className="job-try"><span>From your goal</span>{goalTerms.map(term=><button type="button" key={term} onClick={()=>tryTerm(term)}>{term}</button>)}</div>}
   {sites.length>0&&<div className="job-open-on" aria-label="Search other job sites" role="group"><span>Open on</span>{sites.filter(site=>httpsOnly(site.url)).map(site=><a key={site.name} href={site.url} target="_blank" rel="noopener noreferrer">{site.name}<span aria-hidden="true"> ↗</span><span className="cv-visually-hidden">Opens in a new tab</span></a>)}</div>}
   {sites.length>0&&<p className="job-hero-note">Only your search terms leave elo when you open a site, and your CV stays here. A site may ask you to sign in.</p>}
  </div>
  <div className="job-tabs" role="group" aria-label="Job views">
   <button type="button" className="btn ghost" aria-pressed={tab==='search'} onClick={()=>setTab('search')}>Find jobs</button>
   <button type="button" className="btn ghost" aria-pressed={tab==='tracker'} onClick={()=>setTab('tracker')}>My applications ({applications.length})</button>
  </div>
  {trackerError&&<p className="small" role="alert">{trackerError}</p>}
  {tab==='tracker'?<Tracker items={applications} onStatus={changeStatus} onRemove={remove} onSaveLink={link=>saveJobLink(token,link)} onSaved={remember}/>:<div className="job-find-layout">
   <div className="job-search-panel" aria-label="Filters" role="group">
    <h2>Filters</h2>
    <div className="job-filters">
     <CheckGroup legend="Job type" options={options?.job_types} names={JOB_TYPES} selected={choices.jobTypes} onChange={jobTypes=>change({jobTypes})}/>
     <CheckGroup legend="Industry" options={options?.industries} names={INDUSTRIES} selected={choices.industries} onChange={industries=>change({industries})}/>
     <div className="job-filter-column">
      <label className="job-select" htmlFor="job-posted">Date posted
       <select id="job-posted" value={choices.posted} onChange={event=>change({posted:event.target.value})}>{POSTED.map(([value,name])=><option key={value} value={value}>{name}</option>)}</select>
      </label>
      {choices.posted==='custom'&&<>
       <label className="job-select" htmlFor="job-posted-from">Posted from<input id="job-posted-from" type="date" value={choices.from} max={choices.to||undefined} onChange={event=>change({from:event.target.value})}/></label>
       <label className="job-select" htmlFor="job-posted-to">Posted to<input id="job-posted-to" type="date" value={choices.to} min={choices.from||undefined} onChange={event=>change({to:event.target.value})}/></label>
      </>}
      <label className="job-select" htmlFor="job-workplace">Work arrangement
       <select id="job-workplace" value={choices.workplace} onChange={event=>change({workplace:event.target.value})}>
        <option value="">Any</option>{options?.workplaces.map(o=><option key={o.value} value={o.value}>{label(WORKPLACES,o.value)} ({o.count})</option>)}
       </select>
      </label>
      <label className="job-select" htmlFor="job-company">Employer
       <select id="job-company" value={choices.company} onChange={event=>change({company:event.target.value})}>
        <option value="">Any</option>{options?.companies.map(o=><option key={o.value} value={o.value}>{o.value} ({o.count})</option>)}
       </select>
      </label>
     </div>
    </div>
   </div>
   <div className="job-results">
    <div className="job-results-summary" aria-live="polite">
     <span><strong>{loading?'Searching…':error?'':`${total} ${total===1?'job':'jobs'} in Singapore`}</strong>{!loading&&!error&&options?.last_synced_at&&<small> Employer boards last read {day(options.last_synced_at)}</small>}</span>
     {filtered&&<button type="button" className="btn ghost" onClick={clear}>Clear filters</button>}
    </div>
    {error&&<div role="alert"><p>{error}</p><button type="button" className="btn ghost" onClick={()=>setRetry(value=>value+1)}>Retry</button></div>}
    {!loading&&unavailable.length>0&&<p role="status">Some employer boards could not be read. Results may be incomplete. Search again to retry.</p>}
    {!loading&&!error&&!items.length&&<p>{filtered?'No jobs match these filters. Try removing one.':'No jobs are listed right now.'}</p>}
    <ul className="job-list">
     {items.map(posting=><JobCard key={posting.id} posting={posting} item={tracked.get(posting.id)} onSave={()=>save(posting)} onApply={()=>visitEmployer(posting)}/>)}
    </ul>
    {cursor&&!loading&&<button type="button" className="btn ghost" disabled={more} onClick={loadMore}>{more?'Loading…':'Show more jobs'}</button>}
   </div>
  </div>}
  <div className="job-handoff"><p><strong>Found a role you like?</strong> <Link href="/career-goal?new=1">Use its job description to set your Career Goal.</Link></p><Link className="btn pri" href="/career-goal?new=1" aria-hidden="true" tabIndex={-1}>Set as Career Goal</Link></div>
 </section>;
}

function CheckGroup({legend,options,names,selected,onChange}:{legend:string;options?:FilterOption[];names:Record<string,string>;selected:string[];onChange:(values:string[])=>void}){
 return <fieldset>
  <legend>{legend}</legend>
  {options?.length?options.map(option=><label className="job-check" key={option.value}>
   <input type="checkbox" checked={selected.includes(option.value)} onChange={event=>onChange(event.target.checked?[...selected,option.value]:selected.filter(value=>value!==option.value))}/>
   {label(names,option.value)} ({option.count})
  </label>):<span className="small">Not available yet</span>}
 </fieldset>;
}

function JobCard({posting,item,onSave,onApply}:{posting:Posting;item?:Application;onSave:()=>void;onApply:()=>void}){
 const apply=httpsOnly(posting.apply_url),listing=httpsOnly(posting.listing_url);
 return <li className="job-card">
  <h3>{posting.title}</h3>
  <div>{posting.company}{posting.department?` · ${posting.department}`:''}</div>
  <div className="job-card-meta">
   <span>{label(JOB_TYPES,posting.job_type)}</span><span>{label(WORKPLACES,posting.workplace)}</span>
   <span>{label(INDUSTRIES,posting.industry)}</span><span>{posting.location}</span>
   <span>{posting.posted_at_estimated?'Posting date not supplied':`Posted ${day(posting.posted_at)}`}</span>
   {posting.application_deadline&&<span>Closes {day(posting.application_deadline)}</span>}
  </div>
  {posting.excerpt&&<p>{posting.excerpt}</p>}
  <div className="job-card-actions">
   {apply&&<a className="btn pri" href={apply} target="_blank" rel="noopener noreferrer" onClick={onApply}>Apply on employer site<span className="small">Opens in a new tab</span></a>}
   {listing&&<a className="btn ghost" href={listing} target="_blank" rel="noopener noreferrer">View full job</a>}
   {item?<span className="small">{STATUSES[item.status]} in My applications</span>:<button type="button" className="btn ghost" onClick={onSave}>Save job</button>}
  </div>
  <p className="small">Listed through {label(PROVIDERS,posting.provider)}. Details and applications are handled by {posting.company}.</p>
 </li>;
}

const COLUMNS:{name:string;statuses:ApplicationStatus[]}[]=[{name:'Saved',statuses:['saved']},{name:'Applied',statuses:['applied']},{name:'Interviewing',statuses:['interviewing']},{name:'Offer',statuses:['offer']},{name:'Closed',statuses:['rejected','withdrawn']}];

function SaveLinkForm({onSubmit,onCancel}:{onSubmit:(link:JobLink)=>Promise<void>;onCancel:()=>void}){
 const [link,setLink]=useState<JobLink>({url:'',title:'',company:'',location:'',job_type:'unknown'});
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const change=(next:Partial<JobLink>)=>setLink(current=>({...current,...next}));
 async function submit(event:FormEvent<HTMLFormElement>){
  event.preventDefault();setBusy(true);setError('');
  try{await onSubmit(link);}catch(problem){setError(explanation(problem));setBusy(false);}
 }
 return <form className="job-link-form" aria-label="Save a job from a link" onSubmit={event=>void submit(event)}>
  <label className="job-link-url">Job link<input type="url" required autoFocus maxLength={2000} placeholder="https://" value={link.url} onChange={event=>change({url:event.target.value})}/></label>
  <label>Job title<input required maxLength={200} value={link.title} onChange={event=>change({title:event.target.value})}/></label>
  <label>Employer<input required maxLength={120} value={link.company} onChange={event=>change({company:event.target.value})}/></label>
  <label>Location (optional)<input maxLength={120} value={link.location} onChange={event=>change({location:event.target.value})}/></label>
  <label>Job type<select value={link.job_type} onChange={event=>change({job_type:event.target.value as JobType})}>{Object.entries(JOB_TYPES).map(([value,name])=><option key={value} value={value}>{name}</option>)}</select></label>
  <p className="small">Elo saves these details and doesn&rsquo;t open the link, so add the title and employer yourself.</p>
  {error&&<p className="small" role="alert">{error}</p>}
  <div className="job-link-actions"><button className="btn pri" disabled={busy}>{busy?'Saving…':'Save job'}</button><button type="button" className="btn ghost" disabled={busy} onClick={onCancel}>Cancel</button></div>
 </form>;
}

function Tracker({items,onStatus,onRemove,onSaveLink,onSaved}:{items:Application[];onStatus:(item:Application,status:ApplicationStatus)=>void;onRemove:(item:Application)=>void;onSaveLink:(link:JobLink)=>Promise<Application>;onSaved:(item:Application)=>void}){
 const [adding,setAdding]=useState(false);const [message,setMessage]=useState('');
 const opener=useRef<HTMLButtonElement>(null);
 function close(){setAdding(false);requestAnimationFrame(()=>opener.current?.focus());}
 async function saveLink(link:JobLink){
  const item=await onSaveLink(link);
  setMessage(items.some(other=>other.id===item.id)?`${item.snapshot.title} is already in your saved jobs.`:`Saved ${item.snapshot.title}.`);
  onSaved(item);close();
 }
 const columns=COLUMNS.filter(column=>column.name!=='Closed'||items.some(item=>column.statuses.includes(item.status)));
 return <section className="job-board" aria-labelledby="job-board-title">
  <header><h2 id="job-board-title">Saved jobs</h2><span>{items.length} tracked</span><button ref={opener} type="button" className="btn pri" aria-expanded={adding} onClick={()=>{setMessage('');setAdding(value=>!value);}}>+ Save a job</button></header>
  {message&&<p className="small job-link-message" role="status">{message}</p>}
  {adding&&<SaveLinkForm onSubmit={saveLink} onCancel={close}/>}
  <div className="job-board-columns" style={{gridTemplateColumns:`repeat(${columns.length},minmax(210px,1fr))`}}>{columns.map((column,index)=>{
   const members=items.filter(item=>column.statuses.includes(item.status));
   return <section className={`job-column job-column-${index+1}`} key={column.name} aria-label={column.name}>
    <h3>{column.name}<span>{members.length}</span></h3>
    {members.length?<ul className="job-list">{members.map(item=>{
     const link=httpsOnly(item.snapshot.listing_url);
     return <li className="job-card" key={item.id}>
      <h3>{item.snapshot.title}</h3>
      <div>{item.snapshot.company}</div>
      <div className="job-card-meta">
       <span>{label(JOB_TYPES,item.snapshot.job_type)}</span>{item.snapshot.location&&<span>{item.snapshot.location}</span>}
       {item.source==='link'&&<span>Added from a link</span>}
       <span>Updated {day(item.updated_at)}</span>
       {item.posting_status==='unknown'?<span>Check employer site for availability</span>:item.posting_status!=='open'&&<span>No longer listed</span>}
      </div>
      <div className="job-card-actions">
       <label className="job-status-control">Status
        <select value={item.status} onChange={event=>onStatus(item,event.target.value as ApplicationStatus)}>
         {Object.entries(STATUSES).map(([value,name])=><option key={value} value={value}>{name}</option>)}
        </select>
       </label>
       {link&&<a className="btn ghost" href={link} target="_blank" rel="noopener noreferrer">View job</a>}
       <button type="button" className="btn ghost" aria-label={`Remove ${item.snapshot.title}`} onClick={()=>onRemove(item)}>Remove</button>
      </div>
     </li>;
    })}</ul>:<div className="job-column-empty">{index===0&&<div>{!items.length&&<p>You haven&rsquo;t saved any jobs yet. Jobs you save or confirm you applied to will appear here.</p>}{!adding&&<button type="button" className="job-paste" onClick={()=>{setMessage('');setAdding(true);}}>Paste a job link</button>}</div>}</div>}
   </section>;
  })}</div>
 </section>;
}
