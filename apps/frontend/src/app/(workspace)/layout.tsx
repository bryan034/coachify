import type { ReactNode } from 'react';
import { WorkspaceShell } from '@/components/layout/workspace-shell';
import {WorkspaceActivity} from '@/features/auth/workspace-activity';
import { WorkspaceGuard } from '@/features/auth/workspace-guard';
export default function WorkspaceLayout({ children }: { children: ReactNode }) {
 return <WorkspaceGuard><WorkspaceActivity><WorkspaceShell>{children}</WorkspaceShell></WorkspaceActivity></WorkspaceGuard>;
}
