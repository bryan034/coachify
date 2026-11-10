import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import { WorkspaceGuard } from './workspace-guard';
const replace = vi.hoisted(() => vi.fn());
let developmentToolsEnabled = false; let complete = true;
vi.mock('next/navigation', () => ({ usePathname: () => '/onboarding/preview', useRouter: () => ({ replace }) }));
vi.mock('@/features/profile/profile-provider', () => ({ useProfile: () => ({ developmentToolsEnabled, account: { id: 'synthetic' }, token: 'synthetic', profile: { onboarding_complete: complete }, loading: false, configError: '', loadError: '' }) }));
beforeEach(() => { replace.mockReset(); developmentToolsEnabled = false; complete = true; });
test('production cannot render the preview even through a direct URL or browser flag', async () => {
  localStorage.setItem('development_tools_enabled','true');
  render(<WorkspaceGuard><p>Preview content</p></WorkspaceGuard>);
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/profile'));
  expect(screen.queryByText('Preview content')).not.toBeInTheDocument();
});
test('development permits preview for completed profiles', () => {
  developmentToolsEnabled = true; render(<WorkspaceGuard><p>Preview content</p></WorkspaceGuard>);
  expect(screen.getByText('Preview content')).toBeInTheDocument(); expect(replace).not.toHaveBeenCalled();
});
test('unfinished users continue real onboarding instead of previewing', async () => {
  developmentToolsEnabled = true; complete = false; render(<WorkspaceGuard><p>Preview content</p></WorkspaceGuard>);
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/onboarding'));
  expect(screen.queryByText('Preview content')).not.toBeInTheDocument();
});
test('inside the workspace shell the check shows a page-shaped placeholder, not a second main region', async () => {
  const { container } = render(<WorkspaceGuard inShell><p>Preview content</p></WorkspaceGuard>);
  expect(container.querySelector('main')).toBeNull();
  expect(screen.getByRole('status', { name: 'Checking your session and setup…' })).toBeInTheDocument();
  expect(container.querySelector('.skeleton-line')).not.toBeNull();
  await waitFor(() => expect(replace).toHaveBeenCalledWith('/profile'));
});
