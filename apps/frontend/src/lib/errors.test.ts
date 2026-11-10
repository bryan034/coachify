import { afterEach, describe, expect, it, vi } from 'vitest';
import { friendlyError, friendlyOperationError, isAbortError } from './errors';

afterEach(() => vi.restoreAllMocks());

describe('isAbortError', () => {
 it('recognises aborted requests in every form browsers report them', () => {
  expect(isAbortError(new DOMException('Aborted', 'AbortError'))).toBe(true);
  expect(isAbortError(new Error('signal is aborted without reason'))).toBe(true);
  expect(isAbortError(new Error('The operation was aborted.'))).toBe(true);
  expect(isAbortError(new Error('Could not load saved CVs.'))).toBe(false);
 });
});

describe('friendlyError', () => {
 it('shows nothing for aborted requests', () => {
  expect(friendlyError(new Error('signal is aborted without reason'), 'Could not load.')).toBeNull();
 });
 it('replaces technical model validation messages and logs the original', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  expect(friendlyError(new Error('Use the source-scoped personal skill claim, not its whole team/project item.'), 'Could not finish.', 'assessment_output')).toBe('We couldn’t compare your skills this time. Try again.');
  expect(friendlyError(new Error('Chat interpretation is unavailable. Your message is saved; retry.'), 'We couldn’t process your answer.')).toBe('We couldn’t process your answer.');
  expect(warn).toHaveBeenCalled();
 });
 it('turns network failures into one actionable line', () => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  expect(friendlyError(new TypeError('Failed to fetch'), 'Could not load.')).toBe('We couldn’t reach elo. Check your connection and try again.');
 });
 it('keeps messages that are already written for people', () => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  expect(friendlyError(new Error('This file exceeds the upload limit. Choose a smaller file.'), 'Could not upload.')).toBe('This file exceeds the upload limit. Choose a smaller file.');
 });
});

describe('friendlyOperationError', () => {
 it('maps failed operations by code and falls back otherwise', () => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  expect(friendlyOperationError({ detail: 'Use the source-scoped personal skill claim.', code: 'assessment_output' }, 'Your plan could not be prepared.')).toBe('We couldn’t compare your skills this time. Try again.');
  expect(friendlyOperationError({ detail: 'Your inputs changed before the next comparison step.', code: 'inputs_changed' }, 'x')).toBe('Your inputs changed before the next comparison step.');
  expect(friendlyOperationError(null, 'Your plan could not be prepared.')).toBe('Your plan could not be prepared.');
 });
});
