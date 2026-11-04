/** The three connected points of the elo mark. The last point is always the goal, in Mint. */
export function PathMark({ reversed = false }: { reversed?: boolean }) {
 const line = reversed ? '#FFFFFF' : '#111827';
 return <svg className="path-mark" viewBox="0 0 240 160" fill="none" aria-hidden="true">
  <path d="M28 136 120 80l92-56" stroke={line} strokeWidth="2" strokeDasharray="2 8" strokeLinecap="round"/>
  <circle cx="28" cy="136" r="10" fill={line}/>
  <circle cx="120" cy="80" r="14" fill={reversed ? '#111827' : '#FFFFFF'} stroke={line} strokeWidth="2"/>
  <circle cx="212" cy="24" r="22" fill="#34D399"/>
 </svg>;
}
