"use client";

import Link from 'next/link';
import { useProfile } from '@/features/profile/profile-provider';
import { loadChatAgenda } from '@/lib/api/socials';
import { useSection } from '@/lib/api/workspace-summary';
import { chatTime } from './chat-controls';
import '@/styles/chats-socials.css';

function Agenda({ token }: { token: string }) {
 const agenda = useSection(loadChatAgenda, token);
 if (agenda.state.status !== 'ready' || !agenda.state.data.length) return null;
 return <section className="socials-agenda" aria-labelledby="socials-agenda-title">
  <h2 id="socials-agenda-title">Expert chats</h2>
  <ul>{agenda.state.data.map(chat => <li className="card socials-panel" key={chat.id}>
   <strong>{chat.expert_name}</strong>
   <time dateTime={chat.starts_at}>{chatTime(chat.starts_at)}</time>
   <span className="small">{chat.prep_done ? 'Prep done' : 'Prep: write three questions'} · Notes after the chat</span>
   <Link href={`/chats-socials#booking-${encodeURIComponent(chat.id)}`}>Open chat follow-up</Link>
  </li>)}</ul>
 </section>;
}

export function ChatAgenda() {
 const { account, token } = useProfile();
 return account && token ? <Agenda key={`${account.id}:${token}`} token={token}/> : null;
}
