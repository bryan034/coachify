"use client";
import Link from 'next/link';
import { Icon } from '@/components/ui/icon';
import { EmptyState, SectionTitle } from '@/components/ui/workspace-ui';
import { AccountPanel } from '@/features/profile/account-panel';
import { useProfile } from '@/features/profile/profile-provider';
import { statuses, studyYearLabel } from '@/features/profile/types';
export function HomeDashboard() {
 const { profile, loading } = useProfile();
 const status = statuses.find(s => s.id === profile?.occupational_status)?.label;
 const year = profile?.current_study_year && profile.school_category ? studyYearLabel(profile.school_category, profile.current_study_year) : null;
 return <section className="page on">
  <div className="ptitle"><div><p className="small">Your next chapter starts here</p><h1 className="home-heading">Welcome to Coachify</h1></div><span className="chip"><Icon name="brief"/>Your career copilot</span></div>
  <AccountPanel/>
  <div className="grid hero">
   <div className="card hero-card row"><div className="ring empty-ring" aria-hidden="true"><svg width="132" height="132" viewBox="0 0 132 132"><circle cx="66" cy="66" r="56" fill="none" stroke="var(--soft2)" strokeWidth="12"/></svg><div className="lab"><Icon name="road"/><span className="small">Your journey</span></div></div><div className="grow"><p className="k">Your starting point</p><h2>A clearer path to your next role.</h2><p className="small">Start with your background. Your career roadmap, skills and next steps will live here as Coachify grows.</p><Link href="/profile" className="btn pri cond">{profile?.occupational_status ? 'Review your profile' : 'Set up your profile'} <span aria-hidden="true">↗</span></Link></div></div>
   <div><SectionTitle title="Your background"><Link className="small text-link" href="/profile">Edit profile ↗</Link></SectionTitle><div className="card pad background-card" aria-label="Saved background">
    <div className="tag tone-user"><Icon name="user"/></div><h3>{loading ? 'Loading your profile…' : status || 'Make it yours'}</h3>
    {(profile?.education.institution || profile?.education.course || year) ? <>{profile?.education.institution && <p className="institution-name">{profile.education.institution.name}</p>}<p className="small">{[profile?.education.course, year].filter(Boolean).join(' · ') || 'No course added'}</p></> : <p className="small">Your education and current status help establish where you are today.</p>}
    {profile?.education_review_required && <p className="notice">Your education details need a review.</p>}
    <Link href="/profile" className="text-link small">{profile?.occupational_status ? 'View saved details' : 'Add your background'} →</Link>
   </div></div>
  </div>
  <SectionTitle title="Up next"><Link href="/calendar" className="small text-link">View calendar →</Link></SectionTitle>
  <div className="card split next-steps"><Link className="row" href="/profile"><div className="tag tone-user"><Icon name="user"/></div><div className="grow"><strong>Your profile</strong><p className="small">{profile?.occupational_status ? 'Keep your background up to date' : 'Add your education and status'}</p></div><span aria-hidden="true">→</span></Link><div className="row"><div className="tag tone-book"><Icon name="book"/></div><div><strong>Learning & skills</strong><p className="small">Personalised steps · coming soon</p></div></div><div className="row"><div className="tag tone-chat"><Icon name="chat"/></div><div><strong>Expert conversations</strong><p className="small">Find your people · coming soon</p></div></div></div>
  <div className="grid c3 home-features"><div className="card pad"><div className="row between"><h2 className="k">Roadmap</h2><span className="pill n">Coming soon</span></div><EmptyState icon="road" title="Your path, at your pace" compact>Milestones and progress will appear once roadmap planning is available.</EmptyState><Link href="/roadmap" className="text-link small">Explore roadmap →</Link></div><div className="card pad"><div className="row between"><h2 className="k">New for you</h2><span className="pill n">Coming soon</span></div><EmptyState icon="bolt" title="Room for new opportunities" compact>Relevant internships, projects and events will appear here.</EmptyState><Link href="/calendar" className="text-link small">Explore events →</Link></div><div className="card pad"><div className="row between"><h2 className="k">Suggested chat</h2><span className="pill n">Coming soon</span></div><EmptyState icon="chat" title="A conversation can open doors" compact>Expert suggestions will appear when coffee chats are available.</EmptyState><Link href="/chats" className="text-link small">Explore chats →</Link></div></div>
 </section>;
}
