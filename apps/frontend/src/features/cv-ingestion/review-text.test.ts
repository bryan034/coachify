import {expect, it} from 'vitest';
import {reviewText} from './review-text';

it('removes bracketed source hashes and UUIDs, retaining titles and useful numbers', () => {
 expect(reviewText('Your project [12b476847583f093b7e8aaf5dac8d5d5] used 100 samples.')).toBe('Your project used 100 samples.');
 expect(reviewText('Your role (source_id: 13ccfbf9-224d-52d7-b47c-6c7fbca896e8), what changed?')).toBe('Your role, what changed?');
});
it('removes unbracketed known IDs while preserving unrelated technical hashes', () => {
 const id='12b476847583f093b7e8aaf5dac8d5d5', hash='abcdefabcdefabcdefabcdefabcdefab';
 expect(reviewText(`Source ${id} used commit ${hash}.`, [id])).toBe(`Source used commit ${hash}.`);
});

it('removes evidence fact references, answer IDs and source-block labels from older replies', () => {
 const fact='fact:aaaaaaaaaaaaaaaaaaaaaaaa';
 const answer='answer:11111111-1111-4111-8111-111111111111';
 expect(reviewText(`Your task [Evidence IDs: ${fact}, ${answer}] was supported.`)).toBe('Your task was supported.');
 expect(reviewText(`What did you do? Evidence ID: ${fact}`)).toBe('What did you do?');
 expect(reviewText('Your role [b1]. English (B1).')).toBe('Your role. English (B1).');
});
