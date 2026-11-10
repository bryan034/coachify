import { describe, expect, it } from 'vitest';
import { formatDate, formatDateTime, formatDayMonthYear, formatDuration, formatRunwaySpan, humaniseText } from './format';

describe('formatDate', () => {
 it('writes calendar days with weekday, day, month and year', () => {
  expect(formatDate('2027-05-04')).toBe('Tue, 4 May 2027');
  expect(formatDayMonthYear('2027-05-04')).toBe('4 May 2027');
 });
 it('leaves unreadable values unchanged', () => {
  expect(formatDate('soon')).toBe('soon');
 });
 it('adds a 12-hour time to timestamps', () => {
  expect(formatDateTime(new Date(2026, 10, 10, 19, 5))).toBe('Tue, 10 Nov 2026, 7:05 pm');
 });
});

describe('formatDuration', () => {
 it.each([[600, '10 hours'], [60, '1 hour'], [90, '1 hour 30 minutes'], [45, '45 minutes'], [1, '1 minute'], [0, '0 minutes'], [121, '2 hours 1 minute']])('%i minutes reads as %s', (minutes, text) => {
  expect(formatDuration(minutes)).toBe(text);
 });
});

describe('humaniseText', () => {
 it('rewrites ISO dates and long minute counts in chat replies', () => {
  expect(humaniseText('Finish by 2027-05-04 with 600 minutes a week.')).toBe('Finish by Tue, 4 May 2027 with 10 hours a week.');
 });
 it('keeps short durations and timestamps', () => {
  expect(humaniseText('Use 45 minutes. Saved 2026-11-10T09:00:00Z.')).toBe('Use 45 minutes. Saved 2026-11-10T09:00:00Z.');
 });
});

describe('formatRunwaySpan', () => {
 it('adds a month breakdown once the runway passes a month', () => {
  expect(formatRunwaySpan(24)).toBe('24 weeks (5 months + 2 weeks)');
  expect(formatRunwaySpan(26)).toBe('26 weeks (6 months)');
  expect(formatRunwaySpan(1)).toBe('1 week');
 });
 it('states spare days instead of rounding them away', () => {
  expect(formatRunwaySpan(2, 5)).toBe('2 weeks, 5 days');
  expect(formatRunwaySpan(8, 1)).toBe('8 weeks, 1 day (1 month + 4 weeks)');
 });
});
