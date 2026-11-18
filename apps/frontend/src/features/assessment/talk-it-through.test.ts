import { describe, expect, it } from 'vitest';
import { ratingReason } from './talk-it-through';

const count = (value: string) => value.trim().split(/\s+/).length;
describe('ratingReason', () => {
 it('says when there is nothing to rate from', () => {
  expect(ratingReason({ name: 'SQL', level: null, sources: [] })).toBe('I couldn’t find enough in your CV to rate this.');
 });
 it('names up to two sources and stays under 20 words', () => {
  expect(ratingReason({ name: 'SQL', level: 4, sources: ['Reporting API', 'Cafe sales'] })).toBe('Rated 4 out of 10 based on Reporting API and Cafe sales.');
  const long = ratingReason({ name: 'SQL', level: 4, sources: ['one two three four five six seven eight nine ten eleven twelve thirteen fourteen', 'x'] });
  expect(count(long)).toBeLessThan(20);
 });
 it('falls back to the CV and review answers', () => {
  expect(ratingReason({ name: 'SQL', level: 4 })).toBe('Rated 4 out of 10 based on your CV and review answers.');
 });
});
