"use client";
import Link from 'next/link';
import { Icon } from '@/components/ui/icon';
import { Skeleton, SkeletonLine } from '@/components/ui/workspace-ui';
import { useProfile } from '@/features/profile/profile-provider';
import { loadGoal, loadRoadmap, useSection } from '@/lib/api/workspace-summary';
import { careerApi } from '@/lib/api/career';
import { cvApi } from '@/lib/api/cv';
import '@/styles/chats.css';

type Discovery = { id: string; title: string; last_message: string; updated_at?: string };
type Row = { key: string; kind: string; title: string; last: string; when: string | null; href: string; action: string; icon: string; tone: 'ink' | 'mint' | 'cloud' };

const loadDiscoveries = (token: string, signal: AbortSignal) => careerApi<{ items: Discovery[] }>('/discoveries', token, { signal });
const loadCvChats = async (token: string, signal: AbortSignal) => {
 const [list, cvs] = await Promise.all([cvApi.conversations(null, token, signal), cvApi.list(token, signal)]);
 const names = new Map(cvs.cvs.map(cv => [cv.id, cv.display_name || cv.file_name]));
 return Promise.all(list.conversations.slice(0, 20).map(async item => {
  const chat = await cvApi.conversation(item.id, token, signal);
  const last = chat.messages.at(-1);
  return { ...item, name: item.cv_id ? names.get(item.cv_id) ?? 'Your CV' : null, last: last ? `${last.role === 'user' ? 'You' : 'elo'}: ${last.text}` : '' };
 }));
};

const dayKey = (date: Date) => date.toLocaleDateString('en-CA', { timeZone: 'Asia/Singapore' });
/** "Today, 14:12", "Yesterday", or a short date: the same words the design uses. */
export function whenLabel(iso: string, now = new Date()) {
 const date = new Date(iso);
 if (Number.isNaN(date.getTime())) return null;
 const yesterday = new Date(now.getTime() - 86400000);
 if (dayKey(date) === dayKey(now)) return `Today, ${date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Singapore' })}`;
 if (dayKey(date) === dayKey(yesterday)) return 'Yesterday';
 return date.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Asia/Singapore' });
}

function ListSkeleton() {
 return <Skeleton label="Loading conversations…" className="conversation-skeleton">{[0, 1, 2].map(index => <span key={index} className="conversation-skeleton-row"><SkeletonLine width={40} height={40}/><span><SkeletonLine width="38%" height={14}/><SkeletonLine width="64%"/></span></span>)}</Skeleton>;
}

export function ChatsPreview() {
 const { token } = useProfile();
 const goal = useSection(loadGoal, token), roadmap = useSection(loadRoadmap, token), discoveries = useSection(loadDiscoveries, token), reviews = useSection(loadCvChats, token);
 const sources = [goal, roadmap, discoveries, reviews];
 const dated: (Row & { at: string })[] = [];
 if (reviews.state.status === 'ready') for (const item of reviews.state.data) dated.push({ key: item.id, at: item.updated_at, kind: item.cv_id ? 'CV review' : 'Skills Profile chat', title: item.name ?? 'Skills Profile conversation', last: item.last, when: whenLabel(item.updated_at), href: item.cv_id ? `/cv?review=${item.cv_id}&conversation=${item.id}` : '/cv?chat=manual', action: item.cv_id && !item.read_only ? 'Continue review' : item.read_only ? 'Open' : 'Resume', icon: 'doc', tone: item.cv_id ? 'ink' : 'cloud' });
 if (roadmap.state.status === 'ready' && roadmap.state.data.messages.length) { const last = roadmap.state.data.messages.at(-1)!; dated.push({ key: 'roadmap', at: last.created_at, kind: 'Roadmap', title: 'Plan helper', last: `${last.role === 'user' ? 'You' : 'elo'}: ${last.content}`, when: whenLabel(last.created_at), href: '/roadmap?chat=1', action: 'Resume', icon: 'road', tone: 'mint' }); }
 if (discoveries.state.status === 'ready') for (const item of discoveries.state.data.items ?? []) dated.push({ key: item.id, at: item.updated_at ?? '', kind: 'Career discovery', title: item.title, last: item.last_message ? `elo: ${item.last_message}` : '', when: item.updated_at ? whenLabel(item.updated_at) : null, href: `/career-goal/discovery?session=${item.id}`, action: 'Resume', icon: 'search', tone: 'cloud' });
 dated.sort((a, b) => b.at.localeCompare(a.at));
 // The goal chat has no saved time, so it leads the list rather than being guessed into date order.
 const rows: Row[] = [
  ...(goal.state.status === 'ready' && goal.state.data.goal ? [{ key: 'goal', kind: 'Career Goal chat', title: goal.state.data.goal.role, last: '', when: null, href: '/career-goal/chat', action: 'Resume', icon: 'brief', tone: 'mint' as const }] : []),
  ...dated,
 ];
 const loading = sources.some(source => source.state.status === 'loading');
 const settled = sources.every(source => source.state.status !== 'loading');
 return <section className="page on chats-page">
  <header className="chats-head"><h1>Conversations</h1><p>Every chat you’ve had with elo, newest first. Pick up where you left off.</p></header>
  {sources.map((source, index) => source.state.status === 'error' ? <div key={index} className="chats-error" role="alert"><p>{source.state.message}</p><button type="button" className="btn ghost sm" onClick={source.retry}>Try again</button></div> : null)}
  {rows.length > 0 ? <section className="conversation-list" aria-label="Your conversations">{rows.map(item => <div className="conversation-row" key={item.key}>
   <span className={`conversation-icon tone-${item.tone}`} aria-hidden="true"><Icon name={item.icon}/></span>
   <div className="conversation-text"><p className="conversation-title"><strong>{item.title}</strong><span>{[item.kind, item.when].filter(Boolean).join(' · ')}</span></p><p className="conversation-last">{item.last || 'No messages yet.'}</p></div>
   <Link className="btn ghost sm" href={item.href}>{item.action}</Link>
  </div>)}{loading && <ListSkeleton/>}</section> : loading ? <section className="conversation-list" aria-label="Your conversations"><ListSkeleton/></section> : null}
  {!rows.length && settled && <div className="chats-empty"><p>No conversations yet. Start with your career direction or your Skills Profile.</p><div className="row"><Link className="btn pri" href="/career-goal/discovery">Explore careers</Link><Link className="btn ghost" href="/cv?chat=manual">Talk through my skills</Link></div></div>}
  <section className="socials-teaser" aria-labelledby="socials-title"><span className="conversation-icon" aria-hidden="true"><Icon name="people"/></span><div><h2 id="socials-title">Socials are on the way</h2><p>Soon you’ll be able to talk to peers and mentors here. Nothing to set up yet.</p></div></section>
 </section>;
}
