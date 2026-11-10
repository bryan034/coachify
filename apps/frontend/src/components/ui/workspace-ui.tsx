"use client";
import { useId, useState, type ReactNode } from 'react';
import { Icon } from './icon';
export function PageTitle({ title, children, info }: { title: string; children?: ReactNode; info?: ReactNode }) {
 if (!info) return <div className="ptitle"><h1>{title}</h1>{children}</div>;
 // The tip sits beside the heading, not inside it, so the heading's name stays the page title.
 return <div className="ptitle"><div className="ptitle-heading"><h1>{title}</h1><InfoTip label={`About ${title}`}>{info}</InfoTip></div>{children}</div>;
}
/** The one place on a page for caveats and disclaimers, so cards don't repeat them. */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
 const [open, setOpen] = useState(false);
 const id = useId();
 return <span className={`info-tip${open ? ' is-open' : ''}`} onKeyDown={event => { if (event.key === 'Escape') setOpen(false); }}>
  <button type="button" className="info-tip-button" aria-label={label} aria-expanded={open} aria-describedby={id} onClick={() => setOpen(value => !value)} onBlur={() => setOpen(false)}>i</button>
  <span role="tooltip" id={id} className="info-tip-text">{children}</span>
 </span>;
}
/** Grey placeholder shaped like the content that is loading. Screen readers hear the label once. */
export function Skeleton({ label, children, className = '' }: { label: string; children: ReactNode; className?: string }) {
 return <div className={`skeleton ${className}`} role="status" aria-label={label}><span className="visually-hidden">{label}</span><div aria-hidden="true">{children}</div></div>;
}
export function SkeletonLine({ width = '100%', height = 12 }: { width?: string | number; height?: number }) {
 return <span className="skeleton-line" style={{ width, height }}/>;
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
/** A card-shaped placeholder: a title line and a few lines of body text. */
export function CardSkeleton({ label, lines = 3 }: { label: string; lines?: number }) {
 return <Skeleton label={label}><SkeletonLine width="45%" height={16}/>{Array.from({ length: lines }, (_, index) => <SkeletonLine key={index} width={`${92 - index * 14}%`}/>)}</Skeleton>;
}
/** A page placeholder: title, intro line and a grid of cards, shaped like most workspace pages. */
export function PageSkeleton({ label, cards = 2 }: { label: string; cards?: number }) {
 return <Skeleton label={label}><SkeletonLine width="34%" height={30}/><SkeletonLine width="58%"/><div className="skeleton-grid">{Array.from({ length: cards }, (_, index) => <div className="skeleton-card" key={index}><SkeletonLine width="50%" height={16}/><SkeletonLine/><SkeletonLine width="76%"/></div>)}</div></Skeleton>;
}
/** A conversation placeholder: alternating message bubbles. */
export function ChatSkeleton({ label }: { label: string }) {
 return <Skeleton label={label} className="chat-skeleton"><SkeletonLine width="62%" height={44}/><span style={{ alignSelf: 'flex-end', width: '48%' }}><SkeletonLine height={36}/></span><SkeletonLine width="70%" height={52}/></Skeleton>;
}
