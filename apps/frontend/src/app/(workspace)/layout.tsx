import type { ReactNode } from 'react';
import { WorkspaceShell } from '@/components/layout/workspace-shell';
import { ProfileProvider } from '@/features/profile/profile-provider';
export default function WorkspaceLayout({ children }: { children: ReactNode }) {
 return <ProfileProvider><WorkspaceShell>{children}</WorkspaceShell></ProfileProvider>;
}
