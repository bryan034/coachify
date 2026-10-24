import type { ReactNode } from 'react';
import { Icon } from './icon';
export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
 return <div className="ptitle"><h1>{title}</h1>{children}</div>;
}
export function PendingAction({ children, primary = false }: { children: ReactNode; primary?: boolean }) {
 return <button type="button" className={`btn ${primary ? 'pri' : 'ghost'}`} disabled title="Coming soon">{children}</button>;
}
export function FeatureNotice({ children }: { children: ReactNode }) {
 return <p className="feature-notice"><span className="pill n">Coming soon</span>{children}</p>;
}
export function EmptyState({ icon, title, children, compact = false }: { icon: string; title: string; children: ReactNode; compact?: boolean }) {
 return <div className={`empty-state ${compact ? 'compact' : ''}`}><div className={`tag tone-${icon}`}><Icon name={icon}/></div><h3>{title}</h3><p className="small">{children}</p></div>;
}
export function SectionTitle({ title, children }: { title: string; children?: ReactNode }) {
 return <div className="sec-h"><h2 className="k">{title}</h2>{children}</div>;
}
export function EmptyTable({ columns, message }: { columns: string[]; message: string }) {
 return <div className="card tablewrap"><table><thead><tr>{columns.map(c => <th key={c} scope="col">{c}</th>)}</tr></thead><tbody><tr><td colSpan={columns.length} className="table-empty">{message}</td></tr></tbody></table></div>;
}
