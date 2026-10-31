"use client";
import {useState,type FormEvent} from 'react';
import Link from 'next/link';
import {PageTitle} from '@/components/ui/workspace-ui';
import {Icon} from '@/components/ui/icon';

type Search={keywords:string;location:string};
function searches({keywords,location}:Search){
 const linkedin=new URL('https://www.linkedin.com/jobs/search/');
 linkedin.searchParams.set('keywords',keywords);linkedin.searchParams.set('location',location);
 const indeed=new URL('https://sg.indeed.com/jobs');
 indeed.searchParams.set('q',keywords);indeed.searchParams.set('l',location);
 return [{name:'LinkedIn',url:linkedin.href},{name:'Indeed',url:indeed.href}];
}

export function SearchJobs(){
 const [keywords,setKeywords]=useState(''),[location,setLocation]=useState('Singapore');
 const [submitted,setSubmitted]=useState<Search|null>(null);
 function submit(event:FormEvent<HTMLFormElement>){
  event.preventDefault();
  if(keywords.trim()&&location.trim())setSubmitted({keywords:keywords.trim(),location:location.trim()});
 }
 return <section className="page on job-search-page">
  <PageTitle title="Search Jobs"/>
  <p className="job-search-intro">Search by job title or skill, then choose a job site to view openings.</p>
  <div className="job-search-panel">
   <form className="job-search-form" onSubmit={submit}>
    <label htmlFor="job-keywords">Job title or keywords<input id="job-keywords" name="keywords" value={keywords} required maxLength={120} placeholder="e.g. Software engineer or Python" onChange={event=>{setKeywords(event.target.value);setSubmitted(null);}}/></label>
    <label htmlFor="job-location">Location<input id="job-location" name="location" value={location} required maxLength={120} onChange={event=>{setLocation(event.target.value);setSubmitted(null);}}/></label>
    <button className="btn pri" disabled={!keywords.trim()||!location.trim()}><Icon name="search"/>Find jobs</button>
   </form>
   <p className="small">Searches open on external job sites. Only the search terms you enter are sent when you open a site; your CV stays in elo.</p>
   <div aria-live="polite">
    {submitted&&<section className="job-search-links" aria-labelledby="job-search-links-title">
     <h2 id="job-search-links-title">View matching jobs</h2>
     <p><strong>{submitted.keywords}</strong> in {submitted.location}</p>
     <div className="job-search-destinations">{searches(submitted).map(site=><a key={site.name} className="btn ghost" href={site.url} target="_blank" rel="noopener noreferrer">{site.name}<span className="small">Opens in a new tab</span></a>)}</div>
     <p className="small">Listings, availability and applications are handled by each job site. A site may ask you to sign in.</p>
    </section>}
   </div>
  </div>
  <p className="job-search-handoff">Found a role you like? <Link className="text-link" href="/career-goal?new=1">Use its job description to set your Career Goal.</Link></p>
 </section>;
}
