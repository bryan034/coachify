import {fireEvent, render, screen, within} from '@testing-library/react';
import {expect, it} from 'vitest';
import {SkillProfile, profileSkillGroups, profileSkillList} from './skill-cards';
import {OTHER_SKILLS} from '@/lib/skill-groups';
import type {CvDetail, CvSkill, Declarations, SkillEstimate, SkillsProfile} from './types';
import type {Assessment} from '@/features/roadmap/types';

const skill = (name: string, category = 'unspecified', item = 'project-one'): CvSkill => ({skill_id: name.toLowerCase(), name, category, proficiency: null, experience_months: null, context: null, evidence: [], evidence_type: 'explicit', explicit: true, item_ids: [item],
 sources: [{item_id: item, evidence_type: 'explicit', explicit: true, support_uncertain: false, attribution: 'personal', assistance: 'assisted', proficiency: null, experience_months: null, evidence: [{id: 'evidence-one', excerpt: `Used ${name} on a synthetic project.`, location: 'Page 1'}]}]});
const estimate = (skill_name: string, level: SkillEstimate['level'], item_id = 'project-one'): SkillEstimate => ({item_id, skill_name, level, explanation: 'Synthetic explanation.', evidence_refs: ['private-ref']});
const groups = {Python: 'Technical coding', FastAPI: 'Technical coding', SQL: 'Data & analytics', 'Data processing': 'Data & analytics'};
const cv = (skills: CvSkill[], skill_estimates: SkillEstimate[] = []) => ({skills, skill_estimates, skill_groups: groups, items: [{id: 'project-one', kind: 'project', title: 'Reporting API'}]}) as unknown as CvDetail;
const view = (detail: CvDetail | null, profile: SkillsProfile | null = null, declarations: Declarations | null = null, comparison: Assessment | null = null) => render(<SkillProfile skills={profileSkillList(detail, profile, declarations)} categories={profileSkillGroups(detail, profile, declarations)} comparison={comparison}/>);
const group = (name: string) => screen.getByRole('region', {name});
const profile = (status: 'draft' | 'saved', name = 'Data processing') => ({status, entries: [{id: 'entry-one', kind: 'work', title: 'Weekly reports', fields: {}, skills: [{name, description: 'Described in chat.', dimensions: {}, evidence: []}]}]}) as unknown as SkillsProfile;

const chips = (name: string) => within(group(name)).getAllByRole('button').map(button => button.textContent);
const open = (name: string) => fireEvent.click(screen.getByRole('button', {name: new RegExp(`^${name}`)}));
const panel = () => screen.getByRole('complementary', {name: /./});
const outcome = (changes: Partial<Assessment['job_skill_gaps'][number]>) => ({ref: 'job:x', name: 'X', match_status: 'partial' as const, components: [], ...changes});
const comparison = (job_skill_gaps: Assessment['job_skill_gaps']) => ({job_skill_gaps, evidence: {}} as unknown as Assessment);

it('lays out one row per category with its skills as chips', () => {
 view(cv([skill('Python'), skill('FastAPI'), skill('SQL')], [estimate('Python', 'independent_application'), estimate('SQL', 'guided_application')]));
 expect(within(group('Technical coding')).getByRole('heading', {name: 'Technical coding'})).toBeVisible();
 expect(chips('Technical coding')).toEqual(['Python', 'FastAPI']);
 expect(chips('Data & analytics')).toEqual(['SQL']);
 expect(profileSkillList(cv([skill('Python')],[estimate('Python','independent_application')]),null,null)[0].label).toBe('Independent');
});

it('shows only the categories the backend sent, with unknown skills under Other, last', () => {
 view(cv([skill('Basket weaving', 'Technical'), skill('Python')]));
 expect(screen.getAllByRole('heading', {level: 3}).map(heading => heading.textContent)).toEqual(['Technical coding', OTHER_SKILLS]);
});

it('lists the strongest skills first', () => {
 view(cv([skill('FastAPI'), skill('Python')], [estimate('Python', 'complex_application')]));
 expect(chips('Technical coding')).toEqual(['Python', 'FastAPI']);
});

it('opens a short panel with where the skill was used and one competence state', () => {
 view(cv([skill('Python')]));
 open('Python');
 expect(screen.getByRole('button', {name: /^Python/})).toHaveAttribute('aria-pressed', 'true');
 expect(within(panel()).getByText('Reporting API')).toBeVisible();
 expect(within(panel()).getByText('Evaluate your skills with your Career Goal to see how this skill counts for it.')).toBeVisible();
 expect(screen.queryByText(/private-ref|Used Python on a synthetic project/)).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', {name: 'Close skill panel'}));
 expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
});

it.each([
 ['no related goal requirement', [], 'Not needed for your current goal.'],
 ['a requirement the review has not covered', [outcome({canonical_skill_id: 'python', score_status: 'not_reviewed', relevance: 'high'})], 'Competence not recorded yet.'],
 ['a requirement without enough evidence', [outcome({canonical_skill_id: 'python', score_status: 'insufficient_evidence', relevance: 'medium'})], 'Level unknown from your CV review.'],
])('shows exactly one state for %s', (_, gaps, text) => {
 const detail = cv([{...skill('Python'), canonical_skill_id: 'python'}]);
 view(detail, null, null, comparison(gaps));
 open('Python');
 expect(within(panel()).getByText(text)).toBeVisible();
 expect(within(panel()).queryByRole('img')).not.toBeInTheDocument();
});

it('shows a competence bar and colours the chip by relevance when the comparison scored the skill', () => {
 const detail = cv([{...skill('Python'), canonical_skill_id: 'python'}, skill('SQL')]);
 view(detail, null, null, comparison([outcome({canonical_skill_id: 'python', relevance: 'high', competence_score: 7, score_status: 'estimated'})]));
 expect(screen.getByRole('button', {name: /^Python/})).toHaveClass('relevance-high');
 expect(screen.getByRole('button', {name: /^SQL/})).toHaveClass('relevance-none');
 open('Python');
 expect(within(panel()).getByRole('img', {name: '7 out of 10 for your goal'})).toBeInTheDocument();
 expect(within(panel()).queryByText('Not needed for your current goal.')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button', {name: 'Relevance to goal'}));
 expect(screen.getByRole('heading', {name: 'Skills by relevance to your goal'})).toBeVisible();
 expect(chips('High relevance · Core to your goal')).toEqual(['Python, High relevance']);
});

it('never presents insufficient evidence as a level or invents one', () => {
 view(cv([skill('SQL')], [estimate('SQL', 'insufficient_evidence')]));
 expect(screen.queryByText(/insufficient/i)).not.toBeInTheDocument();
 expect(profileSkillList(cv([skill('SQL')],[estimate('SQL','insufficient_evidence')]),null,null)[0].established).toBe(false);
});

it('includes described and manually added skills with their own labels', () => {
 const declarations = {version: 1, declarations: [{id: 'manual-one', name: 'Technical writing', description: 'Wrote synthetic guides.'}]} as unknown as Declarations;
 view(null, profile('draft'), declarations);
 expect(profileSkillList(null,profile('draft'),declarations).find(skill=>skill.name==='Data processing')?.label).toBe('Proposed — review before saving');
 expect(profileSkillList(null,profile('draft'),declarations).find(skill=>skill.name==='Technical writing')?.label).toBe('Added by you');
 open('Technical writing');
 expect(within(panel()).getByText('Added through your Skills Profile.')).toBeVisible();
});

it('merges the same skill from several sources into one chip', () => {
 view(cv([skill('Python')], [estimate('Python', 'guided_application')]), profile('saved', 'python'));
 expect(screen.getAllByRole('button', {name: /^Python$/i})).toHaveLength(1);
 expect(profileSkillList(cv([skill('Python')],[estimate('Python','guided_application')]),profile('saved','python'),null)[0].label).toBe('Guided');
 open('Python');
 expect(within(panel()).getByText('Reporting API')).toBeInTheDocument();
 expect(within(panel()).getByText('Weekly reports')).toBeInTheDocument();
});

const judged = (skills: Partial<NonNullable<Assessment['skill_profile']>['skills'][number]>[]) => ({job_skill_gaps: [], evidence: {}, skill_profile: {status: 'evaluated', rubric_version: 'skill-profile-llm-v1',
 skills: skills.map(item => ({name: 'Python', canonical_skill_id: null, category: 'Technical coding', subcategory: null, relevance: 'high', competence_score: null, required_score: null, explanation: 'Synthetic explanation.', evidence_refs: [], requirement_refs: [], ...item}))}} as unknown as Assessment);

it('uses the comparison\'s per-skill judgement for category, sub-category, relevance and competence', () => {
 view(cv([skill('Python'), skill('SQL'), skill('Tableau')]), null, null, judged([
  {name: 'Python', subcategory: 'Languages', competence_score: 7, required_score: 8, explanation: 'You wrote the ETL scripts yourself.'},
  {name: 'SQL', category: 'Technical coding', subcategory: 'Data stores', relevance: 'medium'},
  {name: 'Tableau', category: 'Data & analytics', relevance: 'none'}]));
 expect(chips('Technical coding · Languages')).toEqual(['Python, High relevance']);
 expect(chips('Data stores')).toEqual(['SQL, Medium relevance']);
 expect(chips('Data & analytics')).toEqual(['Tableau, Not needed']);
 open('Python');
 expect(within(panel()).getByText('Goal needs about 8 / 10')).toBeVisible();
 expect(within(panel()).getByText('You wrote the ETL scripts yourself.')).toBeVisible();
 open('SQL');
 expect(within(panel()).getByText('Level unknown from your CV review.')).toBeVisible();
 open('Tableau');
 expect(within(panel()).getByText('Not needed for your current goal.')).toBeVisible();
});

it('falls back to requirement outcomes for skills the judgement does not cover', () => {
 const value = {...judged([{name: 'SQL'}]), job_skill_gaps: [outcome({canonical_skill_id: 'python', relevance: 'low', competence_score: 4, score_status: 'estimated'})]} as Assessment;
 view(cv([{...skill('Python'), canonical_skill_id: 'python'}, skill('SQL')]), null, null, value);
 expect(screen.getByRole('button', {name: /^Python/})).toHaveClass('relevance-low');
});
