import type { CSSProperties, ReactNode } from 'react';
const paths: Record<string, ReactNode> = {
 home: <path d="M3 11l9-7 9 7v9H14v-6h-4v6H3z" />,
 road: <><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M8 19h7a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h7"/></>,
 doc: <><path d="M14 3H5v18h14V8zM14 3v5h5M9 13h6M9 17h4"/></>,
 chat: <><path d="M17 8h1a3 3 0 0 1 0 6h-1M3 8h14v6a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5zM7 2v2M11 2v2"/></>,
 cal: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></>,
 bell: <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21h4"/>,
 book: <path d="M4 19V5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 1-2-2zM4 17h16"/>,
 brief: <><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V3h6v4"/></>,
 bolt: <path d="M13 2L4 14h7l-1 8 9-12h-7z"/>,
 user: <><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></>,
 up: <path d="M12 16V4M6 10l6-6 6 6M4 20h16"/>,
};
export function Icon({ name, style }: { name: string; style?: CSSProperties }) {
 return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={style}>{paths[name] || paths.doc}</svg>;
}
