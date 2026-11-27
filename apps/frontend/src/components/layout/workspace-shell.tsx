"use client";
import { ThemePreference } from '@/features/settings/theme-preference';
import { BrandLogo } from '@/components/ui/brand-logo';
import { featureFlags } from '@/lib/feature-flags';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useRef, useState, type MouseEvent, type ReactNode } from 'react';
import { Icon } from '@/components/ui/icon';
import { DevTools } from '@/features/dev/dev-tools';
import { useProfile } from '@/features/profile/profile-provider';
import { statuses, studyYearLabel } from '@/features/profile/types';
const nav = [
 { href: '/dashboard', label: 'Home', icon: 'home' },
 { href: '/career-goal', label: 'Career Goal', icon: 'brief' },
 { href: '/cv', label: 'Skills Profile', icon: 'doc' },
 { href: '/roadmap', label: 'Roadmap', icon: 'road' },
 { href: '/jobs', label: 'Search Jobs', icon: 'search' },
];
const more = [
 { href: '/chats-socials', label: 'Chats & Socials', icon: 'chat' },
 { href: '/calendar', label: 'Calendar', icon: 'cal' },
];
const tabLabels: Record<string, string> = { '/dashboard': 'Home', '/career-goal': 'Goal', '/cv': 'Skills', '/roadmap': 'Roadmap', '/jobs': 'Jobs' };
export function pageTitle(pathname: string) {
 if (pathname.startsWith('/settings')) return 'Settings';
 if (pathname === '/profile' || pathname.startsWith('/profile/')) return 'My profile';
 return [...nav, ...more].find(item => pathname === item.href || pathname.startsWith(`${item.href}/`))?.label ?? 'elo';
}
export function sectionHome(pathname: string) {
 if (pathname.startsWith('/settings')) return '/settings';
 if (pathname === '/profile' || pathname.startsWith('/profile/')) return '/profile';
 return [...nav, ...more].find(item => pathname === item.href || pathname.startsWith(`${item.href}/`))?.href ?? '/dashboard';
}
export function WorkspaceShell({ children }: { children: ReactNode }) {
 const pathname = usePathname();
 const [menuOpen, setMenuOpen] = useState(false);
 const menuButton = useRef<HTMLButtonElement>(null);
 const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
 const home = sectionHome(pathname);
 const goHome = (event: MouseEvent<HTMLAnchorElement>) => {
  if (pathname !== home || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  if (window.location.search || window.location.hash) { window.history.pushState(null, '', home); window.dispatchEvent(new PopStateEvent('popstate')); }
  window.scrollTo?.({ top: 0 });
 };
 const { profile, account, mode, token, signOut, loading, configError, loadError, sessionChecking, sessionError } = useProfile();
 const locked = Boolean(sessionChecking || sessionError);
 const chatRoute = pathname.startsWith('/career-goal/chat') || pathname.startsWith('/career-goal/discovery');
 const status = statuses.find(s => s.id === profile?.occupational_status)?.label;
 const year = profile?.current_study_year && profile.school_category ? studyYearLabel(profile.school_category, profile.current_study_year) : null;
 const detail = loading ? 'Loading your background…' : configError || loadError ? 'Profile unavailable' : mode === 'google' && !token ? 'Sign in to get started' : [year || status, profile?.education.institution?.name].filter(Boolean).join(' · ') || 'Add your background';
 return <div className="app"><ThemePreference/>
  <a href="#main-content" className="skip-link">Skip to content</a>
  <div className="workspace-topbar" hidden={locked}>
   <div className="workspace-topbar-title"><Link href={home} className="brand" aria-label={`elo: back to ${pageTitle(home)}`} onClick={goHome}><BrandLogo/></Link><span aria-hidden="true"/><strong>{pageTitle(pathname)}</strong></div>
   <button ref={menuButton} type="button" className="workspace-menu btn ghost sm" aria-expanded={menuOpen} aria-controls="workspace-sidebar" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? 'Close navigation' : 'Menu'}</button>
  </div>
  <aside id="workspace-sidebar" hidden={locked} inert={locked} className={`side${menuOpen ? ' is-open' : ''}`} aria-label="Workspace" onKeyDown={event => { if (event.key === 'Escape') { setMenuOpen(false); menuButton.current?.focus(); } }} onClick={event => { if ((event.target as HTMLElement).closest('a')) setMenuOpen(false); }}>
   <Link href={home} className="brand" aria-label={`elo: back to ${pageTitle(home)}`} onClick={goHome}><BrandLogo/></Link>
   <nav className="nav" aria-label="Main navigation">{nav.map(n => <Link key={n.href} href={n.href} className={isActive(n.href) ? 'on' : ''} aria-current={isActive(n.href) ? 'page' : undefined}><Icon name={n.icon}/>{n.label}</Link>)}</nav>
   <hr className="nav-divider"/>
   <nav className="nav" aria-label="More">{more.map(n => <Link key={n.href} href={n.href} className={isActive(n.href) ? 'on' : ''} aria-current={isActive(n.href) ? 'page' : undefined}><Icon name={n.icon}/>{n.label}</Link>)}</nav>
   <div className="side-bottom">{featureFlags.settings && <Link href="/settings" className={`profile-link ${isActive('/settings') ? 'on' : ''}`} aria-current={isActive('/settings') ? 'page' : undefined}>Settings</Link>}<Link href="/profile" className={`profile-link ${isActive('/profile') ? 'on' : ''}`} aria-current={isActive('/profile') ? 'page' : undefined}><Icon name="user"/>My profile</Link>
    <div className="me"><div className="avatar"><Icon name="user"/></div><div><strong>{account?.name || 'Your workspace'}</strong><div className="small">{detail}</div></div></div>
   <button type="button" className="btn ghost sm" onClick={signOut}>Sign out</button></div>
  </aside>
  <main id="main-content" tabIndex={-1}><DevTools/>{children}</main>
  <nav className="workspace-tabbar" hidden={locked || chatRoute} aria-label="Main sections">{nav.map(n => <Link key={n.href} href={n.href} className={isActive(n.href) ? 'on' : ''} aria-current={isActive(n.href) ? 'page' : undefined}><Icon name={n.icon}/>{tabLabels[n.href]}</Link>)}</nav>
 </div>;
}
