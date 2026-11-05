import type { ReactNode } from 'react';
import { WorkspaceShell } from '@/components/layout/workspace-shell';
import { WorkspaceGuard } from '@/features/auth/workspace-guard';
import { JobApplicationCheck } from '@/features/jobs/application-check';
export default function WorkspaceLayout({ children }: { children: ReactNode }) {
 return <WorkspaceGuard><WorkspaceShell>{children}<JobApplicationCheck/></WorkspaceShell></WorkspaceGuard>;
}
