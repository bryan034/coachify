import {act, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {CvProcessingProgress} from './cv-processing-progress';
import {savedCv} from '../../../tests/fixtures/cv';

const extracting = () => ({...savedCv(), status: 'processing' as const, processing_progress: {stage: 'model_request' as const, percent: 45, message: 'Identifying your experience and skills.'}});
afterEach(() => {vi.useRealTimers(); vi.unstubAllGlobals();});

describe('CV preparation progress', () => {
 it('moves smoothly while the same extraction stage is pending, without restarting on polling', () => {
  vi.useFakeTimers();
  const cv = extracting();
  const view = render(<CvProcessingProgress cv={cv}/>);
  const bar = screen.getByRole('progressbar', {name: 'CV preparation progress'});
  expect(bar).toHaveAttribute('aria-valuenow', '45');
  act(() => vi.advanceTimersByTime(20000));
  const intermediate = Number(bar.getAttribute('aria-valuenow'));
  expect(intermediate).toBeGreaterThan(45);
  expect(intermediate).toBeLessThan(75);
  view.rerender(<CvProcessingProgress cv={{...cv, processing_progress: {...cv.processing_progress}}}/>);
  expect(Number(bar.getAttribute('aria-valuenow'))).toBe(intermediate);
  act(() => vi.advanceTimersByTime(20000));
  expect(Number(bar.getAttribute('aria-valuenow'))).toBeGreaterThan(intermediate);
  expect(screen.getByText(/Estimated progress/)).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent(cv.processing_progress.message);
 });
 it('honors observed stages and reserves 100 percent for backend readiness', () => {
  vi.useFakeTimers();
  const cv = extracting();
  const view = render(<CvProcessingProgress cv={cv}/>);
  act(() => vi.advanceTimersByTime(60000));
  view.rerender(<CvProcessingProgress cv={{...cv, processing_progress: {stage: 'extraction_validation', percent: 75, message: 'Checking extracted facts and source evidence.'}}}/>);
  const bar = screen.getByRole('progressbar');
  expect(bar).toHaveAttribute('aria-valuenow', '75');
  expect(screen.getByRole('status')).toHaveTextContent('Checking extracted facts and source evidence.');
  view.rerender(<CvProcessingProgress cv={{...cv, processing_progress: {stage: 'publication', percent: 95, message: 'Saving your CV review.'}}}/>);
  act(() => vi.advanceTimersByTime(600000));
  expect(Number(bar.getAttribute('aria-valuenow'))).toBeLessThanOrEqual(99);
  expect(bar).toHaveClass('is-active');
  view.rerender(<CvProcessingProgress cv={{...cv, status: 'ready', processing_progress: {stage: 'ready', percent: 100, message: 'Your CV is ready for review.'}}}/>);
  expect(bar).toHaveAttribute('aria-valuenow', '100');
  expect(bar).not.toHaveClass('is-active');
 });
 it('stops estimated progress and activity animation when processing fails', () => {
  vi.useFakeTimers();
  const cv = extracting();
  const view = render(<CvProcessingProgress cv={cv}/>);
  act(() => vi.advanceTimersByTime(20000));
  view.rerender(<CvProcessingProgress cv={{...cv, status: 'failed'}}/>);
  const bar = screen.getByRole('progressbar');
  const paused = bar.getAttribute('aria-valuenow');
  act(() => vi.advanceTimersByTime(60000));
  expect(bar).toHaveAttribute('aria-valuenow', paused);
  expect(bar).not.toHaveClass('is-active');
 });
 it('resets display estimates for a different saved upload', () => {
  vi.useFakeTimers();
  const cv = extracting();
  const view = render(<CvProcessingProgress cv={cv}/>);
  act(() => vi.advanceTimersByTime(60000));
  view.rerender(<CvProcessingProgress cv={{...cv, id: 'another-cv'}}/>);
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '45');
 });
 it('starts a fresh estimate for an explicit retry of the same saved operation', () => {
  vi.useFakeTimers();
  const cv = extracting();
  const view = render(<CvProcessingProgress cv={cv}/>);
  act(() => vi.advanceTimersByTime(60000));
  view.rerender(<CvProcessingProgress cv={{...cv, status: 'failed'}}/>);
  view.rerender(<CvProcessingProgress cv={{...cv, status: 'queued', processing_progress: {stage: 'queued', percent: 0, message: 'Upload saved. Waiting to start.'}}}/>);
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
  view.rerender(<CvProcessingProgress cv={cv}/>);
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '45');
 });
 it('keeps observed milestones without estimated motion when reduced motion is requested', () => {
  vi.useFakeTimers();
  vi.stubGlobal('matchMedia', () => ({matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn()}));
  render(<CvProcessingProgress cv={extracting()}/>);
  act(() => vi.advanceTimersByTime(60000));
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '45');
 });
 it('uses indeterminate progress for older servers without stage data', () => {
  render(<CvProcessingProgress cv={{...savedCv(), status: 'processing'}}/>);
  expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  expect(screen.getByRole('progressbar')).toHaveClass('is-indeterminate');
  expect(screen.getByText('In progress')).toBeVisible();
 });
});
