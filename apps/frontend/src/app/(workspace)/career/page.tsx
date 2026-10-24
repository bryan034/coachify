import Link from 'next/link';
import { EmptyState, PageTitle, FeatureNotice } from '@/components/ui/workspace-ui';
export default function CareerPage() { return <section><PageTitle title="Career assessment"/><FeatureNotice>Career assessment is not available yet.</FeatureNotice><div className="card"><EmptyState icon="brief" title="Find the gaps, plan the steps">Role requirements and skill gaps will appear when assessments are available.</EmptyState></div><Link className="btn ghost" href="/cv">Go to Resume & Tracker →</Link></section>; }
