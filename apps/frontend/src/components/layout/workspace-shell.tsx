"use client";
import { BrandLogo } from '@/components/ui/brand-logo';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useRef, useState, type ReactNode } from 'react';
import { Icon } from '@/components/ui/icon';
import { useProfile } from '@/features/profile/profile-provider';
import { statuses, studyYearLabel } from '@/features/profile/types';
/** The journey order: background → goal → skills → roadmap → applications. */
const nav = [
 { href: '/dashboard', label: 'Home', icon: 'home' },
 { href: '/career-goal', label: 'Career Goal', icon: 'brief' },
 { href: '/cv', label: 'Skills Profile', icon: 'doc' },
 { href: '/roadmap', label: 'Roadmap', icon: 'road' },
 { href: '/jobs', label: 'Search Jobs', icon: 'search' },
];
/** Supporting pages sit below a divider. */
const more = [
 { href: '/calendar', label: 'Calendar', icon: 'cal' },
];
/** Short labels for the phone tab bar; same destinations and order as the sidebar. */
const tabLabels: Record<string, string> = { '/dashboard': 'Home', '/career-goal': 'Goal', '/cv': 'Skills', '/roadmap': 'Roadmap', '/jobs': 'Jobs' };
export function pageTitle(pathname: string) {
 if (pathname === '/profile' || pathname.startsWith('/profile/')) return 'My profile';
 return [...nav, ...more].find(item => pathname === item.href || pathname.startsWith(`${item.href}/`))?.label ?? 'elo';
}
export function WorkspaceShell({ children }: { children: ReactNode }) {
 const pathname = usePathname();
 const [menuOpen, setMenuOpen] = useState(false);
 const menuButton = useRef<HTMLButtonElement>(null);
 const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
 const { profile, account, mode, token, signOut, loading, configError, loadError, sessionChecking, sessionError } = useProfile();
 // While a session is being rechecked, nothing private is reachable: the guard locks the page and the shell hides its links.
 const locked = Boolean(sessionChecking || sessionError);
 // Full-screen chats keep their composer at the bottom, so the phone tab bar steps aside.
 const chatRoute = pathname.startsWith('/career-goal/chat') || pathname.startsWith('/career-goal/discovery');
 const status = statuses.find(s => s.id === profile?.occupational_status)?.label;
 const year = profile?.current_study_year && profile.school_category ? studyYearLabel(profile.school_category, profile.current_study_year) : null;
 const detail = loading ? 'Loading your background…' : configError || loadError ? 'Profile unavailable' : mode === 'google' && !token ? 'Sign in to get started' : [year || status, profile?.education.institution?.name].filter(Boolean).join(' · ') || 'Add your background';
 return <div className="app">
  <a href="#main-content" className="skip-link">Skip to content</a>
  <div className="workspace-topbar" hidden={locked}>
   <div className="workspace-topbar-title"><Link href="/dashboard" className="brand" aria-label="elo home"><BrandLogo/></Link><span aria-hidden="true"/><strong>{pageTitle(pathname)}</strong></div>
   <button ref={menuButton} type="button" className="workspace-menu btn ghost sm" aria-expanded={menuOpen} aria-controls="workspace-sidebar" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? 'Close navigation' : 'Menu'}</button>
  </div>
  <aside id="workspace-sidebar" hidden={locked} inert={locked} className={`side${menuOpen ? ' is-open' : ''}`} aria-label="Workspace" onKeyDown={event => { if (event.key === 'Escape') { setMenuOpen(false); menuButton.current?.focus(); } }} onClick={event => { if ((event.target as HTMLElement).closest('a')) setMenuOpen(false); }}>
   <Link href="/dashboard" className="brand" aria-label="elo home"><BrandLogo/></Link>
   <nav className="nav" aria-label="Main navigation">{nav.map(n => <Link key={n.href} href={n.href} className={isActive(n.href) ? 'on' : ''} aria-current={isActive(n.href) ? 'page' : undefined}><Icon name={n.icon}/>{n.label}</Link>)}</nav>
   <hr className="nav-divider"/>
   <nav className="nav" aria-label="More">{more.map(n => <Link key={n.href} href={n.href} className={isActive(n.href) ? 'on' : ''} aria-current={isActive(n.href) ? 'page' : undefined}><Icon name={n.icon}/>{n.label}</Link>)}</nav>
   <div className="side-bottom"><Link href="/profile" className={`profile-link ${isActive('/profile') ? 'on' : ''}`} aria-current={isActive('/profile') ? 'page' : undefined}><Icon name="user"/>My profile</Link>
    <div className="me"><div className="avatar"><Icon name="user"/></div><div><strong>{account?.name || 'Your workspace'}</strong><div className="small">{detail}</div></div></div>
   <button type="button" className="btn ghost sm" onClick={signOut}>Sign out</button></div>
  </aside>
  <main id="main-content" tabIndex={-1}>{children}</main>
  <nav className="workspace-tabbar" hidden={locked || chatRoute} aria-label="Main sections">{nav.map(n => <Link key={n.href} href={n.href} className={isActive(n.href) ? 'on' : ''} aria-current={isActive(n.href) ? 'page' : undefined}><Icon name={n.icon}/>{tabLabels[n.href]}</Link>)}</nav>
 </div>;
}
