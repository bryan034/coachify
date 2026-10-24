import type { ReactNode } from 'react';
import { WorkspaceGuard } from '@/features/auth/workspace-guard';

export default function SetupLayout({ children }: { children: ReactNode }) {
  return <WorkspaceGuard>{children}</WorkspaceGuard>;
}
