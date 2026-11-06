"use client";
import Link from 'next/link';
import { useState } from 'react';
import { Icon } from '@/components/ui/icon';
import { useProfile } from '@/features/profile/profile-provider';
import { loadGoal, loadRoadmap, useSection } from '@/lib/api/workspace-summary';
import '@/styles/chats.css';

const people = [
 { icon: 'chat', title: 'Career conversations', body: 'Learn from people who have walked the path.' },
 { icon: 'brief', title: 'Industry perspectives', body: 'Explore what a role looks like from the inside.' },
 { icon: 'user', title: 'Connections that count', body: 'Find people who understand your next step.' },
];
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;

export function ChatsPreview() {
 const { token } = useProfile();
 const [filter, setFilter] = useState('For you');
 const goal = useSection(loadGoal, token), roadmap = useSection(loadRoadmap, token);
 const role = goal.state.status === 'ready' ? goal.state.data.goal?.role : undefined;
 const messages = roadmap.state.status === 'ready' ? roadmap.state.data.messages.length : 0;
 const available = [
  { icon: 'brief', title: 'Career goal chat', href: role ? '/career-goal/chat?refine=1' : '/career-goal/chat', body: role ? `Refine ${role} and ask about the role.` : 'Talk through a job description or a direction.' },
  { icon: 'search', title: 'Explore careers', href: '/career-goal/discovery', body: 'Talk through what you enjoy and see which roles fit.' },
  { icon: 'doc', title: 'Skills Profile chat', href: '/cv', body: 'Build your profile through guided questions, with or without a CV.' },
  { icon: 'road', title: 'Roadmap helper', href: '/roadmap', body: messages ? `${plural(messages, 'message')} saved. Pick up where you left off.` : 'Shape your study plan by chatting about your week.' },
 ];
 return <section className="page on chats-page">
  <div className="chats-title">
   <div className="chats-title-name"><h1>Chats &amp; Socials</h1><p className="feature-notice"><span className="pill n">Coming soon</span><span className="cv-visually-hidden">Expert discovery, chat requests and social connections are not available yet.</span></p></div>
   <button type="button" className="btn pri" disabled title="Coming soon">Find your people</button>
  </div>
  <div className="chips filter-row" aria-label="Expert filters" role="group">{['For you', 'Product', 'Finance', 'Tech'].map(f => <button key={f} type="button" className={`chip ${f === filter ? 'on' : ''}`} aria-pressed={f === filter} onClick={() => setFilter(f)}>{f}</button>)}</div>
  <div className="chats-people">{people.map((person, index) => <article key={person.title} className={`chats-person${index === 0 ? ' is-lead' : ''}`}>
   <span className={`chats-icon tone-${index}`}><Icon name={person.icon}/></span>
   <h2>{person.title}</h2><p>{person.body}</p>
   <div className="chats-person-foot"><button type="button" disabled title="Coming soon">Request a 20-min chat</button><em>Soon</em></div>
  </article>)}</div>
  <p className="small filter-caption">{filter === 'For you' ? 'Expert suggestions' : `${filter} experts`} will appear here once discovery is available.</p>
  <div className="chats-lower">
   <section className="chats-card chats-upcoming" aria-labelledby="chats-upcoming-title"><h2 id="chats-upcoming-title">Upcoming</h2><div className="chats-slot"><span className="chats-icon tone-1"><Icon name="cal"/></span><strong>Space for your next chat</strong><small>Confirmed conversations will appear here.</small></div></section>
   <section className="chats-card chats-network" aria-labelledby="chats-network-title"><h2 id="chats-network-title">Your conversation network</h2><div className="tablewrap"><table><thead><tr>{['Person', 'Field', 'Relationship', 'Recommendation'].map(c => <th key={c} scope="col">{c}</th>)}</tr></thead><tbody><tr><td colSpan={4} className="table-empty">Your connections will appear when networking is available.</td></tr></tbody></table></div></section>
   <section className="chats-card chats-grow" aria-labelledby="chats-grow-title"><div className="chats-avatars" aria-hidden="true">{[0, 1, 2, 3, 4].map(i => <span key={i}><Icon name="user"/></span>)}</div><h2 id="chats-grow-title">Grow together</h2><p>Peer and professional connections will appear here when socials are ready.</p></section>
  </div>
  <section className="chats-now" aria-labelledby="chats-now-title">
   <h2 id="chats-now-title">Talk to elo today</h2>
   <ul>{available.map(item => <li key={item.title}><Link href={item.href}><span className="chats-icon tone-2"><Icon name={item.icon}/></span><span><strong>{item.title}</strong><small>{item.body}</small></span></Link></li>)}</ul>
  </section>
 </section>;
}
