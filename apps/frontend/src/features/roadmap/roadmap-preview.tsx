"use client";
import { useState } from 'react';
import Link from 'next/link';
import { useProfile } from '@/features/profile/profile-provider';
import { EmptyState, PageTitle, FeatureNotice, SectionTitle } from '@/components/ui/workspace-ui';
export function RoadmapPreview() {
 const [filter, setFilter] = useState('All');
 const { profile } = useProfile();
 return <section className="page on"><PageTitle title="Roadmap"><span className="chip">Your path to job-ready</span></PageTitle>
 <FeatureNotice>Roadmap planning and progress tracking are not available yet.</FeatureNotice>
 <div className="card tf row timeframe"><div className="grow"><p className="k">Your saved planning preferences</p><h2>A deadline and pace that work for you</h2><p className="small">Inputs come from your saved profile. Roadmap generation is not available yet.</p></div><Link className="btn ghost" href="/profile#planning-preferences">Edit planning preferences →</Link></div>
 <div className="card split roadmap-stats">{[['Application date',profile?.application_date || 'Not set'],['Normal weekly hours',profile?.weekly_hours == null ? 'Not set' : `${profile.weekly_hours} hours/week`],['Reduced periods',profile?.availability_periods?.length ? `${profile.availability_periods.length} saved` : 'None saved']].map(([title,value]) => <div key={title}><p className="k">{title}</p><p className="stat-value">{value}</p></div>)}</div>
 <div className="chips filter-row" aria-label="Roadmap filters">{['All','Courses','Skills','People','Jobs'].map(f => <button key={f} type="button" className={`chip ${filter===f?'on':''}`} aria-pressed={filter===f} onClick={()=>setFilter(f)}>{f}</button>)}</div>
 <SectionTitle title={filter==='All'?'Your milestones':filter}/><div className="card"><EmptyState icon="road" title={filter==='All'?'Your roadmap starts here':`No ${filter.toLowerCase()} to show yet`}>Your personalised steps will appear here when roadmap planning is ready.</EmptyState></div>
 <div className="grid c3 roadmap-outline">{[['book','Build your capabilities','Courses and practical skills for your target role.'],['chat','Find your people','Conversations to help you understand the path ahead.'],['brief','Make your next move','Projects, internships and applications along the way.']].map(([icon,title,body])=><div className="card" key={title}><EmptyState compact icon={icon} title={title}>{body}</EmptyState></div>)}</div>
 </section>;
}
