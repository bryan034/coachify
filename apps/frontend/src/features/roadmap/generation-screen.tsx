"use client";
import { useEffect, useRef } from 'react';

/** Stages of a saved generation. Each has a fixed share, because the model reports no finer progress. */
const steps = [['assessing', 'Comparing your skills with your goal', 20], ['writing', 'Writing your roadmap', 50], ['detailing', 'Writing your next two weeks', 80]] as const;
const CORRECTING = 'correcting';
export const isGenerationStage = (stage?: string) => stage === CORRECTING || steps.some(([key]) => key === stage);

export function GenerationScreen({ stage }: { stage?: string }) {
 const heading = useRef<HTMLHeadingElement>(null);
 // The form this replaces held focus, so move it here for keyboard and screen-reader users.
 useEffect(() => { heading.current?.focus(); }, []);
 const correcting = stage === CORRECTING;
 const position = steps.findIndex(([key]) => key === stage);
 const percent = correcting ? 90 : position >= 0 ? steps[position][2] : 5;
 const current = correcting ? 'Fixing what the schedule check found' : position >= 0 ? steps[position][1] : 'Getting started';
 return <div className="generation-screen">
  <h2 ref={heading} tabIndex={-1}>Generating your roadmap</h2>
  <p className="small">This can take a few minutes. You can leave this page; it keeps going and reconnects when you return.</p>
  <div className="generation-bar" role="progressbar" aria-label="Roadmap generation" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={current}><i style={{ width: `${percent}%` }} /></div>
  <p className="generation-current" role="status">{current}</p>
  <ol className="generation-steps">
   {steps.map(([key, label], index) => {
    const done = correcting || index < position;
    return <li key={key} className={done ? 'done' : !correcting && index === position ? 'current' : ''}>{label}</li>;
   })}
  </ol>
 </div>;
}
