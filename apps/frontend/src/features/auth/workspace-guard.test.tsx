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
