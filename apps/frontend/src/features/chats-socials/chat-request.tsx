"use client";

import { useCallback, useState } from 'react';
import { loadChatSlots, requestChat, SocialsError, type ChatBooking, type ChatDuration, type Expert, type RequestChat } from '@/lib/api/socials';
import { useSection } from '@/lib/api/workspace-summary';
import { CardSkeleton } from '@/components/ui/workspace-ui';
import { ChatDialog, chatTime, useChatCommand } from './chat-controls';

export function ChatRequest({ expert, token, credits, onClose, onSaved }: {
 expert: Expert; token: string; credits: number; onClose: () => void; onSaved: (booking: ChatBooking) => void;
}) {
 const load = useCallback((marker: string, signal: AbortSignal) => loadChatSlots(marker, expert.id, signal), [expert.id]);
 const slots = useSection(load, token);
 const command = useChatCommand<RequestChat, ChatBooking>(body => requestChat(token, body));
 const [duration, setDuration] = useState<ChatDuration>(30);
 const [slotId, setSlotId] = useState('');
 const [question, setQuestion] = useState('');
 const [adult, setAdult] = useState(false);
 const available = slots.state.status === 'ready' ? slots.state.data.filter(slot => slot.durations.includes(duration)) : [];
 const selected = available.find(slot => slot.id === slotId);
 const cost = duration / 30;

 return <ChatDialog title={`Request a chat with ${expert.name}`} close={onClose} busy={command.busy}>
  <form className="socials-form" onSubmit={event => {
   event.preventDefault();
   if (!selected || !adult || credits < cost) return;
   void command.run({ expert_id: expert.id, slot_id: selected.id, slot_version: selected.version, duration_minutes: duration, question: question.trim(), adult_attested: true }, onSaved, cause => {
    if (cause instanceof SocialsError && cause.status === 409) { setSlotId(''); slots.retry(); }
   });
  }}>
   <fieldset disabled={command.busy}>
    <legend>How long?</legend>
    <div className="socials-options">
     <label><input type="radio" name="duration" checked={duration === 30} onChange={() => { setDuration(30); setSlotId(''); }}/> 30 minutes · 1 credit</label>
     <label><input type="radio" name="duration" checked={duration === 60} disabled={credits < 2} onChange={() => { setDuration(60); setSlotId(''); }}/> 1 hour · 2 credits</label>
    </div>
   </fieldset>
   <fieldset disabled={command.busy}>
    <legend>Pick a time</legend>
    {slots.state.status === 'loading' && <CardSkeleton label="Loading available times" lines={1}/>}
    {slots.state.status === 'error' && <div role="alert"><p>{slots.state.message}</p><button type="button" className="btn ghost sm" onClick={slots.retry}>Retry times</button></div>}
    {slots.state.status === 'ready' && (available.length ? <div className="socials-options">
     {available.map(slot => <label key={slot.id}><input type="radio" name="time" checked={slotId === slot.id} onChange={() => setSlotId(slot.id)}/> {chatTime(slot.starts_at)}</label>)}
    </div> : <p className="small">No {duration}-minute times are available.</p>)}
   </fieldset>
   <p className="small">Your expert will share a meeting link when they accept.</p>
   <label>What would you like to ask? <span className="small">Optional</span>
    <textarea value={question} maxLength={1000} rows={3} disabled={command.busy} onChange={event => setQuestion(event.target.value)} placeholder="What does a typical week in your role look like?"/>
   </label>
   <label className="socials-check"><input type="checkbox" checked={adult} disabled={command.busy} onChange={event => setAdult(event.target.checked)}/> I confirm I’m 18 or over.</label>
   {command.error && <p role="alert" className="socials-error">{command.error}</p>}
   <div className="socials-actions"><button className="btn pri" disabled={command.busy || !selected || !adult || credits < cost}>{command.busy ? 'Sending request…' : 'Send request'}</button><span className="small">Uses {cost} {cost === 1 ? 'credit' : 'credits'}</span></div>
  </form>
 </ChatDialog>;
}
