import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent } from '@testing-library/react';
import { WorkspaceShell, pageTitle, sectionHome } from './workspace-shell';

const path = vi.hoisted(() => ({ current: '/cv' }));
const session = vi.hoisted(() => ({ checking: false }));
vi.mock('next/navigation', () => ({ usePathname: () => path.current }));
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => ({ profile: null, account: { name: 'Synthetic Student' }, mode: 'local', token: 't', signOut: vi.fn(), loading: false, configError: '', loadError: '', sessionChecking: session.checking, sessionError: '' }) }));

beforeEach(() => { path.current = '/cv'; session.checking = false; });

it('orders the sidebar by the journey and puts coming-soon pages below a divider', () => {
 render(<WorkspaceShell><p>Page</p></WorkspaceShell>);
 const main = within(screen.getByRole('navigation', { name: 'Main navigation' })).getAllByRole('link').map(link => link.textContent);
 expect(main).toEqual(['Home', 'Career Goal', 'Skills Profile', 'Roadmap', 'Search Jobs']);
 const more = within(screen.getByRole('navigation', { name: 'More' })).getAllByRole('link').map(link => link.textContent);
 expect(more).toEqual(['Calendar']);
 expect(screen.getByRole('separator')).toBeInTheDocument();
 expect(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name: 'Skills Profile' })).toHaveAttribute('aria-current', 'page');
});

it('names the current page beside the mobile menu button', () => {
 path.current = '/roadmap';
 const { container } = render(<WorkspaceShell><p>Page</p></WorkspaceShell>);
 expect(container.querySelector('.workspace-topbar')).toHaveTextContent('Roadmap');
 expect(within(container.querySelector('.workspace-topbar') as HTMLElement).getByRole('button', { name: 'Menu' })).toBeInTheDocument();
 expect(pageTitle('/profile/edit')).toBe('My profile');
 expect(pageTitle('/career-goal/chat')).toBe('Career Goal');
});

it('hides navigation while the session is being rechecked', () => {
 session.checking = true;
 render(<WorkspaceShell><p>Page</p></WorkspaceShell>);
 expect(screen.queryByRole('link', { name: 'Career Goal' })).not.toBeInTheDocument();
});

it('gives phones a tab bar with the five journey pages in sidebar order', () => {
 path.current = '/career-goal/interview';
 render(<WorkspaceShell><p>Page</p></WorkspaceShell>);
 const tabs = within(screen.getByRole('navigation', { name: 'Main sections' })).getAllByRole('link');
 expect(tabs.map(link => link.textContent)).toEqual(['Home', 'Goal', 'Skills', 'Roadmap', 'Jobs']);
 expect(tabs[1]).toHaveAttribute('aria-current', 'page');
});

it('steps the tab bar aside on full-screen chats so the composer stays reachable', () => {
 path.current = '/career-goal/chat';
 const { container } = render(<WorkspaceShell><p>Page</p></WorkspaceShell>);
 expect(container.querySelector('.workspace-tabbar')).toHaveAttribute('hidden');
});

it('sends the logo to the top page of the current section', () => {
 path.current = '/career-goal/interview';
 render(<WorkspaceShell><p>Page</p></WorkspaceShell>);
 for (const logo of screen.getAllByRole('link', { name: 'elo: back to Career Goal' })) expect(logo).toHaveAttribute('href', '/career-goal');
 expect(sectionHome('/profile/edit')).toBe('/profile');
 expect(sectionHome('/getting-started')).toBe('/dashboard');
});

it('clears an in-page view such as a CV review when the logo is pressed on its section page', () => {
 window.history.replaceState(null, '', '/cv?review=cv-1');
 const restored = vi.fn();
 window.addEventListener('popstate', restored);
 render(<WorkspaceShell><p>Page</p></WorkspaceShell>);
 fireEvent.click(screen.getAllByRole('link', { name: 'elo: back to Skills Profile' })[0]);
 expect(window.location.pathname + window.location.search).toBe('/cv');
 expect(restored).toHaveBeenCalledTimes(1);
 window.removeEventListener('popstate', restored);
});
