"use client";
import { BrandLogo } from '@/components/ui/brand-logo';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { Icon } from '@/components/ui/icon';
import { useProfile } from '@/features/profile/profile-provider';
import { statuses, studyYearLabel } from '@/features/profile/types';
const nav = [
 { href: '/dashboard', label: 'Home', icon: 'home' },
 { href: '/career-goal', label: 'Career Goal', icon: 'brief' },
 { href: '/roadmap', label: 'Roadmap', icon: 'road' },
 { href: '/cv', label: 'Resume & Tracker', icon: 'doc' },
 { href: '/chats', label: 'Chats & Socials', icon: 'chat' },
 { href: '/calendar', label: 'Calendar & Events', icon: 'cal' },
];
export function WorkspaceShell({ children }: { children: ReactNode }) {
 const pathname = usePathname();
 const { profile, account, mode, token, signOut, loading, configError, loadError } = useProfile();
 const status = statuses.find(s => s.id === profile?.occupational_status)?.label;
 const year = profile?.current_study_year && profile.school_category ? studyYearLabel(profile.school_category, profile.current_study_year) : null;
 const detail = loading ? 'Loading your background…' : configError || loadError ? 'Profile unavailable' : mode === 'google' && !token ? 'Sign in to get started' : [year || status, profile?.education.institution?.name].filter(Boolean).join(' · ') || 'Add your background';
 return <div className="app">
  <a href="#main-content" className="skip-link">Skip to content</a>
  <aside className="side">
   <Link href="/dashboard" className="brand" aria-label="elo home"><BrandLogo/></Link>
   <nav className="nav" aria-label="Main navigation">{nav.map(n => <Link key={n.href} href={n.href} className={pathname === n.href ? 'on' : ''} aria-current={pathname === n.href ? 'page' : undefined}><Icon name={n.icon}/>{n.label}</Link>)}</nav>
   <div className="side-bottom"><Link href="/profile" className={`profile-link ${pathname === '/profile' ? 'on' : ''}`} aria-current={pathname === '/profile' ? 'page' : undefined}><Icon name="user"/>My profile<span>↗</span></Link>
    <div className="me"><div className="avatar"><Icon name="user"/></div><div><strong>{account?.name || 'Your workspace'}</strong><div className="small">{detail}</div></div></div>
   <button type="button" className="btn ghost sm" onClick={signOut}>Sign out</button></div>
  </aside>
  <main id="main-content" tabIndex={-1}>{children}</main>
 </div>;
}
