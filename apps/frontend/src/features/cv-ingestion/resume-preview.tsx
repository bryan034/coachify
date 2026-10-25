import Link from 'next/link';
import { Icon } from '@/components/ui/icon';
import { EmptyState, EmptyTable, PageTitle, FeatureNotice, PendingAction, SectionTitle } from '@/components/ui/workspace-ui';
export function ResumePreview() {
 return <section className="page on"><PageTitle title="Resume & Tracker"><div className="row"><PendingAction primary><Icon name="up"/>Upload resume</PendingAction><PendingAction>↻ Re-scan</PendingAction></div></PageTitle>
 <FeatureNotice>Dedicated resume upload, skill assessment and application tracking are not available yet. <Link href="/career-goal?explore=1">Explore career goals with an optional temporary CV attachment</Link>.</FeatureNotice>
 <div className="grid resume-grid"><div className="card"><EmptyState icon="doc" title="Your resume, in one place">A resume and its analysis will appear here once uploads are available.</EmptyState></div><div className="card pad"><div className="row between"><h2 className="k">Skill gaps</h2><span className="small">Your capabilities → role requirements</span></div><div className="skill-placeholders">{['Current skills','Role requirements','Skills to develop','Readiness'].map(t=><div key={t}><div className="row between"><strong>{t}</strong><span className="small">—</span></div><div className="bar"/></div>)}</div><p className="small">No assessment yet. Scores will appear after your resume and target role are assessed.</p></div></div>
 <div className="grid resume-grid"><div><SectionTitle title="Missing from your CV"/><div className="card pad"><p className="small">Suggestions will appear after a resume review.</p></div></div><div><SectionTitle title="Roles you fit today"/><div className="card pad"><p className="small">Role matches will appear when career assessment is available.</p></div></div></div>
 <SectionTitle title="Application tracker"><span className="small">Coming soon</span></SectionTitle><EmptyTable columns={['Company & role','Applied','Stage','Match','Next action']} message="Applications will appear here when tracking is available."/>
 </section>;
}
