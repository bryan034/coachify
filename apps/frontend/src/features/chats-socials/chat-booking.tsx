"use client";

import { useState } from 'react';
import { decideChat, reportChat, saveChatFollowUp, SocialsError, type ChatBooking, type ChatFollowUp, type DecideChat } from '@/lib/api/socials';
import { ChatDialog, chatStatus, chatTime, useChatCommand } from './chat-controls';

export function ReportChat({ booking, token, close, saved }: { booking: ChatBooking; token: string; close: () => void; saved: () => void }) {
 const [reason, setReason] = useState('');
 const command = useChatCommand<{ reason: string }, { id: string }>(body => reportChat(token, booking.id, body));
 return <ChatDialog title="Report a chat" close={close} busy={command.busy}>
  <form className="socials-form" onSubmit={event => {
   event.preventDefault();
   if (reason.trim()) void command.run({ reason: reason.trim() }, saved);
  }}>
   <label>What happened?<textarea required maxLength={2000} rows={4} value={reason} disabled={command.busy} onChange={event => setReason(event.target.value)}/></label>
   <p className="small">elo’s team will review your report.</p>
   {command.error && <p role="alert" className="socials-error">{command.error}</p>}
   <button className="btn pri" disabled={command.busy || !reason.trim()}>{command.busy ? 'Sending report…' : 'Send report'}</button>
  </form>
 </ChatDialog>;
}

function FollowUp({ booking, token, refresh }: { booking: ChatBooking; token: string; refresh: () => void }) {
 const [notes, setNotes] = useState(booking.notes);
 const [prep, setPrep] = useState(booking.prep_done);
 const [current, setCurrent] = useState(booking);
 const command = useChatCommand<ChatFollowUp, ChatBooking>(body => saveChatFollowUp(token, booking.id, body));
 const changed = prep !== current.prep_done || notes.trim() !== current.notes;
 const [conflict, setConflict] = useState(false);
 return <details className="socials-followup">
  <summary>Prep and notes{current.prep_done ? ' · prep done' : ''}</summary>
  <form className="socials-form" onSubmit={event => {
   event.preventDefault();
   setConflict(false);
   if (changed) void command.run({ expected_version: current.version, prep_done: prep, notes: notes.trim() }, saved => {
    setCurrent(saved);
    setNotes(saved.notes);
    setPrep(saved.prep_done);
   }, cause => setConflict(cause instanceof SocialsError && cause.status === 409));
  }}>
   <label className="socials-check"><input type="checkbox" checked={prep} disabled={command.busy} onChange={event => setPrep(event.target.checked)}/> Write three questions before your chat</label>
   <label>Private notes<textarea value={notes} maxLength={4000} rows={3} disabled={command.busy} onChange={event => setNotes(event.target.value)}/></label>
   {command.error && <p className="socials-error" role="alert">{command.error}</p>}
   <div className="socials-actions"><button className="btn ghost sm" disabled={!changed || command.busy}>Save follow-up</button>
    {conflict && <button type="button" className="btn ghost sm" onClick={refresh}>Reload chat</button>}
    {!changed && current.version !== booking.version && <span role="status" className="small">Saved</span>}
   </div>
  </form>
 </details>;
}

export function BookingDetails({ booking, token, refresh, report }: { booking: ChatBooking; token: string; refresh: () => void; report: () => void }) {
 return <article className="card socials-booking" id={`booking-${booking.id}`}>
  <header><div><h3>{booking.expert_name}</h3><p className="small">{chatTime(booking.starts_at)} · {booking.duration_minutes} min · Online</p></div>
   <span className={`socials-state is-${booking.status}`}>{chatStatus[booking.status]}</span>
  </header>
  {booking.meeting_url && <a className="btn ghost sm" href={booking.meeting_url} target="_blank" rel="noreferrer">Open meeting link</a>}
  {booking.status === 'accepted' && <FollowUp key={booking.version} booking={booking} token={token} refresh={refresh}/>}
  {booking.status !== 'submitting' && booking.status !== 'slot_unavailable' && <button className="btn ghost sm" type="button" onClick={report}>Report</button>}
 </article>;
}

export function ExpertBooking({ booking, token, saved, report }: { booking: ChatBooking; token: string; saved: (booking: ChatBooking) => void; report: () => void }) {
 const [meeting, setMeeting] = useState('');
 const command = useChatCommand<DecideChat, ChatBooking>(body => decideChat(token, booking.id, body));
 return <article className="card socials-booking">
  <header><div><h3>{booking.member_name}</h3><p className="small">{chatTime(booking.starts_at)} · {booking.duration_minutes} min · Online</p></div>
   <span className={`socials-state is-${booking.status}`}>{chatStatus[booking.status]}</span>
  </header>
  {booking.question && <p className="socials-question">{booking.question}</p>}
  {booking.status === 'requested' && <form className="socials-form" onSubmit={event => {
   event.preventDefault();
   if (meeting.trim()) void command.run({ expected_version: booking.version, decision: 'accept', meeting_url: meeting.trim() }, saved);
  }}>
   <label>Meeting link<input required type="url" maxLength={2048} placeholder="https://…" value={meeting} disabled={command.busy} onChange={event => setMeeting(event.target.value)}/></label>
   <div className="socials-actions"><button className="btn pri sm" disabled={command.busy || !meeting.trim()}>Accept</button>
    <button className="btn ghost sm" type="button" disabled={command.busy} onClick={() => { void command.run({ expected_version: booking.version, decision: 'decline' }, saved); }}>Decline</button></div>
  </form>}
  {command.error && <p role="alert" className="socials-error">{command.error}</p>}
  {booking.meeting_url && <a className="btn ghost sm" href={booking.meeting_url} target="_blank" rel="noreferrer">Open meeting link</a>}
  <button className="btn ghost sm" type="button" onClick={report}>Report</button>
 </article>;
}
