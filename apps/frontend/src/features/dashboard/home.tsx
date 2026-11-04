"use client";
import Link from 'next/link';
import { SectionTitle } from '@/components/ui/workspace-ui';
import { AccountPanel } from '@/features/profile/account-panel';
import { useProfile } from '@/features/profile/profile-provider';
import { statuses, studyYearLabel } from '@/features/profile/types';
export function HomeDashboard() {
 const { profile, loading } = useProfile();
 const status = statuses.find(s => s.id === profile?.occupational_status)?.label;
 const year = profile?.current_study_year && profile.school_category ? studyYearLabel(profile.school_category, profile.current_study_year) : null;
 return <section className="page on home">
  <div className="home-hero"><div className="home-hero-copy"><p className="home-hero-lede">Your next chapter starts here</p><h1>Welcome to elo</h1><p>A clearer path to your next role. See the skills your goal needs, the skills you have, and the time it takes to close the gap.</p><div className="home-hero-actions"><Link href="/career-goal" className="btn pri">Open your career goal</Link><Link href="/cv" className="btn ghost">Open your Skills Profile</Link></div></div></div>
  <AccountPanel/>
  <section className="home-path" aria-labelledby="home-path-title"><h2 id="home-path-title">Your path</h2>
   <ol>
    <li><Link href="/career-goal"><strong>Choose your goal</strong><span>Bring a job description or explore careers. See the skills it needs, by category.</span></Link></li>
    <li><Link href="/cv"><strong>Show what you can do</strong><span>Add your CV or chat it through. See your skills and the experience behind them.</span></Link></li>
    <li><Link href="/roadmap"><strong>Plan the route</strong><span>Fit the gap around your week, with timed sessions and milestones.</span></Link></li>
   </ol>
  </section>
  <div className="home-more">
   <section><SectionTitle title="Your background"><Link className="small text-link" href="/profile/edit">Edit profile</Link></SectionTitle><div className="card pad background-card" aria-label="Saved background">
    <h3>{loading ? 'Loading your profile…' : status || 'Make it yours'}</h3>
    {(profile?.education.institution || profile?.education.course || year) ? <>{profile?.education.institution && <p className="institution-name">{profile.education.institution.name}</p>}<p className="small">{[profile?.education.course, year].filter(Boolean).join(' · ') || 'No course added'}</p></> : <p className="small">Your education and current status help establish where you are today.</p>}
    {profile?.education_review_required && <p className="notice">Your education details need a review.</p>}
    <Link href="/profile" className="text-link small">{profile?.occupational_status ? 'View saved details' : 'Add your background'}</Link>
   </div></section>
   <section><SectionTitle title="Coming soon"/><ul className="home-soon">
    <li><Link href="/calendar"><strong>Events</strong><span>Relevant internships, projects and events.</span></Link></li>
    <li><Link href="/chats"><strong>Expert conversations</strong><span>Coffee chats with people who have done the role.</span></Link></li>
   </ul></section>
  </div>
 </section>;
}
