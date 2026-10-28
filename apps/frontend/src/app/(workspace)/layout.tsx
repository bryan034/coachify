import type { ReactNode } from 'react';
import { WorkspaceShell } from '@/components/layout/workspace-shell';
import { WorkspaceGuard } from '@/features/auth/workspace-guard';
export default function WorkspaceLayout({ children }: { children: ReactNode }) {
 return <WorkspaceGuard><WorkspaceShell>{children}</WorkspaceShell></WorkspaceGuard>;
}
