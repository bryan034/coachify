import Link from 'next/link';
import { EmptyState, PageTitle, FeatureNotice } from '@/components/ui/workspace-ui';
export default function ReviewsPage() { return <section><PageTitle title="Progress reviews"/><FeatureNotice>Progress reviews are not available yet.</FeatureNotice><div className="card"><EmptyState icon="road" title="A moment to reflect">Pace reviews will appear when progress tracking is available.</EmptyState></div><Link className="btn ghost" href="/roadmap">Go to Roadmap →</Link></section>; }
