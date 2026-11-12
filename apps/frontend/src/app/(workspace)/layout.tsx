import type { ReactNode } from 'react';
import { WorkspaceShell } from '@/components/layout/workspace-shell';
import { WorkspaceGuard } from '@/features/auth/workspace-guard';
import { JobApplicationCheck } from '@/features/jobs/application-check';
import { ChangeBanner } from '@/features/assessment/change-banner';
export default function WorkspaceLayout({ children }: { children: ReactNode }) {
 return <WorkspaceShell><WorkspaceGuard inShell><ChangeBanner/>{children}<JobApplicationCheck/></WorkspaceGuard></WorkspaceShell>;
}
