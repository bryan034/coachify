"use client";
import {useEffect, useState} from 'react';
import type { CvSummary } from './types';

// These are display ceilings between observed backend milestones, not provider
// completion measurements. Only a ready response may display 100%.
const ceilings: Record<string, number> = {
 queued: 9, source_read: 24, document_parse: 44, model_request: 74,
 extraction_validation: 84, model_repair: 94, publication: 99, ready: 100,
};

export function CvProcessingProgress({cv}: {cv: CvSummary}) {
 return <PreparationProgress key={`${cv.id}:${cv.operation_id}`} cv={cv}/>;
}

function PreparationProgress({cv}: {cv: CvSummary}) {
 const progress = cv.processing_progress;
 const actual = cv.status === 'ready' ? 100 : Math.min(progress?.percent ?? 0, 99);
 const [displayed, setDisplayed] = useState(actual);
 const [reducedMotion, setReducedMotion] = useState(false);
 useEffect(() => {
  const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  if (!media) return;
  const update = () => setReducedMotion(media.matches);
  update(); media.addEventListener('change', update);
  return () => media.removeEventListener('change', update);
 }, []);
 useEffect(() => {
  setDisplayed(previous => cv.status === 'queued' || reducedMotion ? actual : Math.max(previous, actual));
  if (cv.status !== 'processing' || !progress || reducedMotion) return;
  const ceiling = Math.max(actual, Math.min(99, ceilings[progress.stage] ?? actual));
  const timer = window.setInterval(() => {
   setDisplayed(previous => previous >= ceiling ? previous : previous + (ceiling - previous) * .008);
  }, 250);
  return () => window.clearInterval(timer);
 }, [cv.status, actual, progress?.stage, Boolean(progress), reducedMotion]);
 const percent = cv.status === 'ready' ? 100 : Math.min(99, Math.round(Math.max(actual, displayed)));
 const active = cv.status === 'queued' || cv.status === 'processing';
 const message = progress?.message ?? 'Reading your experience and skills…';
 return <div className="cv-processing-progress">
  <div className="row between"><span>Preparing your review</span><strong>{progress ? `${percent}%` : 'In progress'}</strong></div>
  <div className={`cv-preparation-track${active ? ' is-active' : ''}${!progress ? ' is-indeterminate' : ''}`}
   role="progressbar" aria-label="CV preparation progress" aria-valuemin={0} aria-valuemax={100}
   aria-valuenow={progress ? percent : undefined} aria-valuetext={progress ? `${percent}% estimated. ${message}` : message} aria-busy={active}>
   <span className="cv-preparation-fill" style={{width: progress ? `${cv.status === 'ready' ? 100 : Math.min(99, Math.max(actual, displayed))}%` : '35%'}}/>
  </div>
  <p role="status" aria-live="polite">{message}</p>
  <p className="small">Estimated progress. Processing time varies.</p>
 </div>;
}
