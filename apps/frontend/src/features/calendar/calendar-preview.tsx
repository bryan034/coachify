"use client";
import { useEffect, useState } from 'react';
import { EmptyState, PageTitle, FeatureNotice, PendingAction, SectionTitle } from '@/components/ui/workspace-ui';
const dayNames=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
export function CalendarPreview() {
 const [view,setView]=useState('Week');
 const [today,setToday]=useState<Date|null>(null);
 useEffect(()=>{setToday(new Date());},[]);
 let days:Date[]=[];
 if(today){
  const start=new Date(today.getFullYear(),today.getMonth(),view==='Month'?1:today.getDate());
  start.setDate(start.getDate()-(start.getDay()+6)%7);
  const count=view==='Week'?7:Math.ceil(((new Date(today.getFullYear(),today.getMonth(),1).getDay()+6)%7+new Date(today.getFullYear(),today.getMonth()+1,0).getDate())/7)*7;
  days=Array.from({length:count},(_,i)=>new Date(start.getFullYear(),start.getMonth(),start.getDate()+i));
 }
 return <section className="page on"><PageTitle title="Calendar & Events"><PendingAction primary>+ Add</PendingAction></PageTitle><FeatureNotice>Events, deadlines and task tracking are not available yet.</FeatureNotice>
 <div className="card pad row calendar-toolbar"><div className="grow"><p className="k">{today?today.toLocaleDateString('en-SG',{month:'long',year:'numeric'}):'Your calendar'}</p><p className="calendar-date">{today?today.toLocaleDateString('en-SG',{weekday:'long',day:'numeric',month:'long'}):'Loading calendar…'}</p></div><div className="seg" aria-label="Calendar view"><button type="button" className="chip" disabled title="Coming soon">Day</button>{['Week','Month'].map(v=><button key={v} type="button" className={`chip ${view===v?'on':''}`} aria-pressed={view===v} onClick={()=>setView(v)}>{v}</button>)}</div></div>
 <div className="card calendar-grid-wrap" aria-label={`${view} calendar`}><div className={view==='Week'?'week':'month'}>{view==='Month'&&dayNames.map(d=><div className="dh" key={d}>{d}</div>)}{days.map((d,i)=>{const isToday=d.toDateString()===today?.toDateString();return <div key={d.toISOString()} aria-current={isToday?'date':undefined} className={view==='Week'?`day ${isToday?'today':''}`:`${isToday?'today':''} ${d.getMonth()!==today?.getMonth()?'out':''}`}><div className={view==='Week'?'dn':''}>{view==='Week'&&dayNames[i]}<b>{d.getDate()}</b></div></div>})}</div></div>
 <div className="grid c2"><div><SectionTitle title="Deadlines"><span className="small">Next 14 days</span></SectionTitle><div className="card"><EmptyState compact icon="brief" title="Deadlines will live here">Application and project dates will appear when scheduling is ready.</EmptyState></div><SectionTitle title="Events for you"/><div className="card"><EmptyState compact icon="bolt" title="Find your next opportunity">Relevant events will appear here when discovery is available.</EmptyState></div></div><div><SectionTitle title="To-do"><span className="small">Coming soon</span></SectionTitle><div className="card"><EmptyState icon="book" title="Make space for your next steps">Roadmap tasks and completion tracking will appear here.</EmptyState></div></div></div>
 <SectionTitle title="Events & development"><span className="small">Built around your skill gaps</span></SectionTitle><div className="grid c2">{['Short term','Long term'].map(t=><div className="card pad" key={t}><span className="pill n">{t}</span><EmptyState compact icon="cal" title="Opportunities on the horizon">Events and development programmes will appear when recommendations are available.</EmptyState><PendingAction>View event</PendingAction></div>)}</div>
 </section>;
}
