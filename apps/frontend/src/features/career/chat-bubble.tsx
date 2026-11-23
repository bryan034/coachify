import type {ReactNode} from 'react';
import {BrandLogo} from '@/components/ui/brand-logo';

export function ChatBubble({role,children}:{role:'assistant'|'user';children:ReactNode}){
 return <div className={`agent-message ${role}`}>{role==='assistant'&&<span className="agent-message-avatar" aria-hidden="true"><BrandLogo compact decorative/></span>}<span className="agent-message-label">{role==='user'?'You':'elo'}</span><div className="agent-bubble">{children}</div></div>;
}
