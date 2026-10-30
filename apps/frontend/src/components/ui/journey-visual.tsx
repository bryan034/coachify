import { useId } from 'react';

/** A decorative path built from the three connected points in the Elo mark. */
export function JourneyVisual() {
 const id = useId().replace(/:/g, '');
 return <div className="journey-visual" aria-hidden="true"><svg viewBox="0 0 600 540" fill="none">
  <defs>
   <linearGradient id={`${id}-edge`} x1="110" y1="460" x2="485" y2="110" gradientUnits="userSpaceOnUse"><stop stopColor="#475569"/><stop offset=".5" stopColor="#111827"/><stop offset="1" stopColor="#475569"/></linearGradient>
   <linearGradient id={`${id}-top`} x1="180" y1="100" x2="400" y2="390" gradientUnits="userSpaceOnUse"><stop stopColor="#FFFFFF"/><stop offset=".55" stopColor="#F1F5F9"/><stop offset="1" stopColor="#475569"/></linearGradient>
   <linearGradient id={`${id}-mint`} x1="370" y1="100" x2="450" y2="190" gradientUnits="userSpaceOnUse"><stop stopColor="#ECFDF5"/><stop offset=".5" stopColor="#34D399"/><stop offset="1" stopColor="#111827"/></linearGradient>
   <radialGradient id={`${id}-shadow`}><stop stopColor="#111827" stopOpacity=".16"/><stop offset="1" stopColor="#111827" stopOpacity="0"/></radialGradient>
  </defs>
  <ellipse cx="310" cy="455" rx="240" ry="60" fill={`url(#${id}-shadow)`}/>
  <g stroke="#111827" strokeOpacity=".09"><path d="m45 335 315-182 200 115M45 390l315-182 200 115M100 422l315-182M155 453l315-182M95 250l310 179M150 218l310 179M205 186l310 179"/></g>
  <g fill="#111827" fillOpacity=".12"><ellipse cx="115" cy="270" rx="9" ry="5"/><ellipse cx="207" cy="217" rx="9" ry="5"/><ellipse cx="299" cy="164" rx="9" ry="5"/><ellipse cx="299" cy="376" rx="9" ry="5"/><ellipse cx="391" cy="323" rx="9" ry="5"/><ellipse cx="483" cy="270" rx="9" ry="5"/></g>
  <path d="m153 352 211-216 57 33-211 216Z" fill={`url(#${id}-edge)`}/>
  <path d="m153 335 211-216 57 33-211 216Z" fill={`url(#${id}-top)`}/>
  <path d="m153 335 57 33v17l-57-33Z" fill="#111827"/>
  <path d="m210 368 211-216v17L210 385Z" fill={`url(#${id}-edge)`}/>
  <path d="M125 346v32c0 23 30 42 67 42s67-19 67-42v-32" fill={`url(#${id}-edge)`}/>
  <ellipse cx="192" cy="346" rx="67" ry="39" fill={`url(#${id}-top)`}/>
  <ellipse cx="192" cy="346" rx="47" ry="27" stroke="#FFFFFF" strokeOpacity=".7"/>
  <path d="M230 243v33c0 23 30 42 67 42s67-19 67-42v-33" fill={`url(#${id}-edge)`}/>
  <ellipse cx="297" cy="243" rx="67" ry="39" fill={`url(#${id}-top)`}/>
  <ellipse cx="297" cy="243" rx="47" ry="27" stroke="#FFFFFF" strokeOpacity=".7"/>
  <path d="M335 140v33c0 23 30 42 67 42s67-19 67-42v-33" fill={`url(#${id}-edge)`}/>
  <ellipse cx="402" cy="140" rx="67" ry="39" fill={`url(#${id}-mint)`}/>
  <ellipse cx="402" cy="140" rx="47" ry="27" stroke="#FFFFFF" strokeOpacity=".65"/>
  <circle cx="402" cy="108" r="27" fill={`url(#${id}-mint)`}/>
 </svg></div>;
}
