import type { ReactNode, Ref } from 'react';
import { BrandLogo } from './brand-logo';

/** Shared pieces of elo's in-chat helpers: header, status line, opening message and composer box. */

export function HelperHeader({ title, titleId, onClose, closeRef }: { title: string; titleId?: string; onClose: () => void; closeRef?: Ref<HTMLButtonElement> }) {
 return <div className="helper-head">
  <span className="helper-avatar" aria-hidden="true"><BrandLogo compact decorative /></span>
  <h2 id={titleId}>{title}</h2>
  <button ref={closeRef} type="button" className="helper-close" aria-label="Close chat" onClick={onClose}>Close</button>
 </div>;
}

/** The mint line under the header: what this helper is about, or what it still needs. */
export function HelperStatus({ children }: { children: ReactNode }) {
 return <p className="helper-status" role="status">{children}</p>;
}

/** The first thing the helper says: a heading and short paragraphs. */
export function HelperOpening({ title, children }: { title: string; children: ReactNode }) {
 return <div className="helper-opening"><h3>{title}</h3>{children}</div>;
}

export function HelperComposer({ children, hint, canSend }: { children: ReactNode; hint: string; canSend: boolean }) {
 return <div className="helper-compose-box">{children}
  <div className="helper-compose-foot"><span>{hint}</span><button type="submit" disabled={!canSend} aria-label="Send message">↑</button></div>
 </div>;
}
