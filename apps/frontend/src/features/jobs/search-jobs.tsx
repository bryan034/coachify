"use client";
import {useCallback,useEffect,useMemo,useRef,useState,type FormEvent} from 'react';
import Link from 'next/link';
import {PageTitle} from '@/components/ui/workspace-ui';
import {Icon} from '@/components/ui/icon';
import {useProfile} from '@/features/profile/profile-provider';
import {JobsError,listApplications,readJobFilters,removeApplication,saveApplication,searchJobs,updateApplication,
 type Application,type ApplicationStatus,type FilterOption,type FilterOptions,type JobFilters,type Posting} from '@/lib/api/jobs';
import {APPLICATION_RECORDED,noteApplyVisit} from './application-check';

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

function boardSearches(keywords:string){
 const linkedin=new URL('https://www.linkedin.com/jobs/search/');
 linkedin.searchParams.set('keywords',keywords);linkedin.searchParams.set('location','Singapore');
 const indeed=new URL('https://sg.indeed.com/jobs');
 indeed.searchParams.set('q',keywords);indeed.searchParams.set('l','Singapore');
 return [{name:'LinkedIn',url:linkedin.href},{name:'Indeed',url:indeed.href}];
}

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
 function clear(){setDraft('');setKeywords('');setChoices(NO_CHOICES);}
 const filtered=Boolean(keywords)||JSON.stringify(choices)!==JSON.stringify(NO_CHOICES);

 return <section className="page on job-search-page">
  <PageTitle title="Search Jobs"/>
  <p className="job-search-intro">Find jobs and internships in Singapore, then apply on the employer&rsquo;s own site. Elo tracks your progress and sends nothing to employers.</p>
  <div className="job-tabs" role="group" aria-label="Job views">
   <button type="button" className="btn ghost" aria-pressed={tab==='search'} onClick={()=>setTab('search')}>Find jobs</button>
   <button type="button" className="btn ghost" aria-pressed={tab==='tracker'} onClick={()=>setTab('tracker')}>My applications ({applications.length})</button>
  </div>
  {trackerError&&<p className="small" role="alert">{trackerError}</p>}
  {tab==='tracker'?<Tracker items={applications} onStatus={changeStatus} onRemove={remove}/>:<>
   <div className="job-search-panel">
    <form className="job-search-form" onSubmit={submit}>
     <label htmlFor="job-keywords">Job title or keywords<input id="job-keywords" name="keywords" value={draft} maxLength={120} placeholder="e.g. Software engineer or Python" onChange={event=>setDraft(event.target.value)}/></label>
     <button className="btn pri"><Icon name="search"/>Search</button>
    </form>
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
     <span>{loading?'Searching…':error?'':`${total} ${total===1?'job':'jobs'} in Singapore`}</span>
     {filtered&&<button type="button" className="btn ghost" onClick={clear}>Clear filters</button>}
    </div>
    {error&&<div role="alert"><p>{error}</p><button type="button" className="btn ghost" onClick={()=>setRetry(value=>value+1)}>Retry</button></div>}
    {!loading&&unavailable.length>0&&<p role="status">Some employer boards could not be read. Results may be incomplete. Search again to retry.</p>}
    {!loading&&!error&&!items.length&&<p>{filtered?'No jobs match these filters. Try removing one.':'No jobs are listed right now.'}</p>}
    <ul className="job-list">
     {items.map(posting=><JobCard key={posting.id} posting={posting} item={tracked.get(posting.id)} onSave={()=>save(posting)} onApply={()=>visitEmployer(posting)}/>)}
    </ul>
    {cursor&&!loading&&<button type="button" className="btn ghost" disabled={more} onClick={loadMore}>{more?'Loading…':'Show more jobs'}</button>}
    {keywords&&<section className="job-search-links" aria-labelledby="job-search-links-title">
     <h2 id="job-search-links-title">Search other job sites</h2>
     <div className="job-search-destinations">{boardSearches(keywords).map(site=><a key={site.name} className="btn ghost" href={site.url} target="_blank" rel="noopener noreferrer">{site.name}<span className="small">Opens in a new tab</span></a>)}</div>
     <p className="small">Only your search terms are sent when you open a site. A site may ask you to sign in.</p>
    </section>}
   </div>
   <p className="job-search-handoff">Found a role you like? <Link className="text-link" href="/career-goal?new=1">Use its job description to set your Career Goal.</Link></p>
  </>}
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

function Tracker({items,onStatus,onRemove}:{items:Application[];onStatus:(item:Application,status:ApplicationStatus)=>void;onRemove:(item:Application)=>void}){
 if(!items.length)return <p>You haven&rsquo;t saved any jobs yet. Jobs you save or confirm you applied to will appear here.</p>;
 return <ul className="job-list job-results">
  {items.map(item=>{
   const link=httpsOnly(item.snapshot.listing_url);
   return <li className="job-card" key={item.id}>
    <h3>{item.snapshot.title}</h3>
    <div>{item.snapshot.company}</div>
    <div className="job-card-meta">
     <span>{label(JOB_TYPES,item.snapshot.job_type)}</span><span>{item.snapshot.location}</span>
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
  })}
 </ul>;
}
