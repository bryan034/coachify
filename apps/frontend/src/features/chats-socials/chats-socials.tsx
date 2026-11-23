"use client";

import { useEffect, useState } from 'react';
import { Icon } from '@/components/ui/icon';
import { CardSkeleton, PageSkeleton } from '@/components/ui/workspace-ui';
import { useProfile } from '@/features/profile/profile-provider';
import { loadExpertInbox, loadSocials, type ChatBooking, type Expert } from '@/lib/api/socials';
import { useSection } from '@/lib/api/workspace-summary';
import { BookingDetails, ExpertBooking, ReportChat } from './chat-booking';
import { chatStatus } from './chat-controls';
import { ChatRequest } from './chat-request';
import '@/styles/chats-socials.css';

function ExpertCard({ expert, credits, onRequest }: { expert: Expert; credits: number; onRequest: () => void }) {
 const initials = expert.name.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
 return <article className="card socials-expert">
  <header><span className="socials-initials" aria-hidden="true">{initials}</span><div><h3>{expert.name}</h3><p>{expert.role}</p></div></header>
  <p className="small">{expert.organisation}</p>
  <p className="socials-availability">{expert.open_slots ? `${expert.open_slots} ${expert.open_slots === 1 ? 'time' : 'times'} available` : 'No upcoming times'}</p>
  <div className="socials-actions">
   <button type="button" className="btn pri sm" disabled={expert.open_slots === 0 || credits === 0} onClick={onRequest}>Request a chat</button>
   {expert.linkedin_url && <a className="btn ghost sm" href={expert.linkedin_url} target="_blank" rel="noreferrer">LinkedIn</a>}
  </div>
 </article>;
}

function ExpertInbox({ token, report }: { token: string; report: (booking: ChatBooking) => void }) {
 const inbox = useSection(loadExpertInbox, token);
 return <section aria-labelledby="expert-inbox">
  <div className="socials-section-head"><h2 id="expert-inbox">Expert inbox</h2><button type="button" className="btn ghost sm" onClick={inbox.retry}>Refresh requests</button></div>
  {inbox.state.status === 'loading' && <CardSkeleton label="Loading requests"/>}
  {inbox.state.status === 'error' && <p role="alert" className="socials-error">{inbox.state.message}</p>}
  {inbox.state.status === 'ready' && (inbox.state.data.length ? <div className="socials-list">
   {inbox.state.data.map(booking => <ExpertBooking key={`${booking.id}:${booking.version}`} booking={booking} token={token} saved={inbox.retry} report={() => report(booking)}/>)}
  </div> : <p className="small">Your chat requests will appear here.</p>)}
 </section>;
}

function SocialsPage({ token }: { token: string }) {
 const workspace = useSection(loadSocials, token);
 const [field, setField] = useState('');
 const [expert, setExpert] = useState<Expert | null>(null);
 const [report, setReport] = useState<ChatBooking | null>(null);
 const [notice, setNotice] = useState('');
 const data = workspace.state.status === 'ready' ? workspace.state.data : null;
 const recommendation = data?.recommendation;
 const recommended = data?.experts.find(item => item.id === recommendation?.expert_id);
 const fields = Array.from(new Set(data?.experts.map(item => item.field))).sort();
 const filtered = data?.experts.filter(item => field ? item.field === field : item.id !== recommended?.id) ?? [];

 useEffect(() => {
  const fragment = window.location.hash;
  if (data && fragment.startsWith('#booking-')) document.getElementById(fragment.slice(1))?.scrollIntoView();
 }, [data]);

 return <div className="page on socials-page">
  <header className="socials-header">
   <div><h1>Chats &amp; Socials</h1><p>Book a coffee chat with someone already doing the job you want.</p></div>
   {data?.access === 'enabled' && <div className="socials-credits"><Icon name="chat"/><div><strong>{data.credits}</strong><span>{data.credits === 1 ? 'Chat credit' : 'Chat credits'}</span></div></div>}
  </header>
  <div className="socials-list">
   {notice && <p className="socials-notice" role="status">{notice}</p>}
   {workspace.state.status === 'loading' && <PageSkeleton label="Loading Chats & Socials"/>}
   {workspace.state.status === 'error' && <div className="card socials-panel"><p role="alert">{workspace.state.message}</p><button type="button" className="btn ghost sm" onClick={workspace.retry}>Try again</button></div>}
   {data?.access === 'locked' && <section className="card socials-panel"><h2>Expert chats are invite-only</h2><p className="small">Bookings are available to members invited to the pilot.</p></section>}
   {data?.access === 'enabled' && <>
    {data.credits === 0 && <p className="socials-notice">You have no chat credits available.</p>}
    {recommended && recommendation && <section className="socials-recommended" aria-labelledby="socials-recommended">
     <div><h2 id="socials-recommended">Recommended for you</h2><p>Based on your {recommendation.role} career goal.</p></div>
     <ExpertCard expert={recommended} credits={data.credits} onRequest={() => setExpert(recommended)}/>
    </section>}
    {(!recommended || filtered.length > 0 || fields.length > 1) && <section aria-labelledby="socials-browse">
     <div className="socials-section-head"><h2 id="socials-browse">Browse experts</h2>
      {fields.length > 1 && <label>Field<select value={field} onChange={event => setField(event.target.value)}><option value="">All fields</option>{fields.map(item => <option key={item}>{item}</option>)}</select></label>}
     </div>
     {filtered.length > 0 ? <div className="socials-grid">{filtered.map(item => <ExpertCard key={item.id} expert={item} credits={data.credits} onRequest={() => setExpert(item)}/>)}</div>
      : <p className="small">No experts are listed here yet.</p>}
    </section>}
   </>}
   {data && (data.access === 'enabled' || data.bookings.length > 0) && <section aria-labelledby="socials-bookings">
    <div className="socials-section-head"><h2 id="socials-bookings">Your chats</h2><button type="button" className="btn ghost sm" onClick={workspace.retry}>Refresh chats</button></div>
    {data.bookings.length ? <div className="socials-list">{data.bookings.map(booking => <BookingDetails key={booking.id} booking={booking} token={token} refresh={workspace.retry} report={() => setReport(booking)}/>)}</div>
     : <p className="small">Your chat requests will appear here.</p>}
   </section>}
   {data?.expert_inbox && <ExpertInbox token={token} report={setReport}/>}
  </div>
  {expert && data && <ChatRequest expert={expert} token={token} credits={data.credits} onClose={() => setExpert(null)} onSaved={booking => {
   setExpert(null);
   setNotice(booking.status === 'requested' ? 'Request sent. You’ll see the expert’s decision in Your chats.' : chatStatus[booking.status]);
   workspace.retry();
  }}/>}
  {report && <ReportChat booking={report} token={token} close={() => setReport(null)} saved={() => { setReport(null); setNotice('Report sent.'); }}/>}
 </div>;
}

export function ChatsSocials() {
 const { account, token } = useProfile();
 return account && token ? <SocialsPage key={`${account.id}:${token}`} token={token}/> : null;
}
