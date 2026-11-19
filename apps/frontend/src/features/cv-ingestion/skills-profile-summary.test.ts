import {expect, it, vi} from 'vitest';
vi.mock('@/features/assessment/comparison', () => ({announceInputsChanged: vi.fn(), useComparison: vi.fn()}));
import {skillsUsed} from './skills-profile-summary';
import type {CvDetail, ReviewFact} from './types';

const fact = (skill_name: string | null, changes: Partial<ReviewFact> = {}): ReviewFact => ({field: 'skill_use', skill_name, attribution: 'personal', status: 'supported', value: 'Synthetic use.', evidence: [{source_id: 'answer:q1', quote: 'Synthetic quote.'}], ...changes});
const item = {id: 'role-one', review_evidence: [fact('Python'), fact('python'), fact('Model output evaluation'), fact('Team reporting', {attribution: 'team'}), fact('Unstated', {status: 'unknown', value: null}), fact(null)]} as unknown as CvDetail['items'][number];
const cv = {skills: [{name: 'Python', item_ids: ['role-one']}, {name: 'SQL', item_ids: ['other-role']}], clarifications: []} as unknown as CvDetail;

it('lists the role’s skills and the skills taken from answered questions, without the answers', () => {
 expect(skillsUsed(cv, item)).toEqual(['Python', 'Model output evaluation']);
});
