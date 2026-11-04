import {render, screen, within} from '@testing-library/react';
import {expect, it} from 'vitest';
import {SkillProfile, profileSkillGroups, profileSkillList} from './skill-cards';
import {OTHER_SKILLS} from '@/lib/skill-groups';
import type {CvDetail, CvSkill, Declarations, SkillEstimate, SkillsProfile} from './types';

const skill = (name: string, category = 'unspecified', item = 'project-one'): CvSkill => ({skill_id: name.toLowerCase(), name, category, proficiency: null, experience_months: null, context: null, evidence: [], evidence_type: 'explicit', explicit: true, item_ids: [item],
 sources: [{item_id: item, evidence_type: 'explicit', explicit: true, support_uncertain: false, attribution: 'personal', assistance: 'assisted', proficiency: null, experience_months: null, evidence: [{id: 'evidence-one', excerpt: `Used ${name} on a synthetic project.`, location: 'Page 1'}]}]});
const estimate = (skill_name: string, level: SkillEstimate['level'], item_id = 'project-one'): SkillEstimate => ({item_id, skill_name, level, explanation: 'Synthetic explanation.', evidence_refs: ['private-ref']});
const groups = {Python: 'Technical coding', FastAPI: 'Technical coding', SQL: 'Data & analytics', 'Data processing': 'Data & analytics'};
const cv = (skills: CvSkill[], skill_estimates: SkillEstimate[] = []) => ({skills, skill_estimates, skill_groups: groups, items: [{id: 'project-one', kind: 'project', title: 'Reporting API'}]}) as unknown as CvDetail;
const view = (detail: CvDetail | null, profile: SkillsProfile | null = null, declarations: Declarations | null = null) => render(<SkillProfile skills={profileSkillList(detail, profile, declarations)} categories={profileSkillGroups(detail, profile, declarations)}/>);
const group = (name: string) => screen.getByRole('region', {name});
const row = (name: string) => screen.getByText(name, {selector: 'summary'}).closest('li')!;
const profile = (status: 'draft' | 'saved', name = 'Data processing') => ({status, entries: [{id: 'entry-one', kind: 'work', title: 'Weekly reports', fields: {}, skills: [{name, description: 'Described in chat.', dimensions: {}, evidence: []}]}]}) as unknown as SkillsProfile;

it('shows one card per category listing its skills and levels', () => {
 view(cv([skill('Python'), skill('FastAPI'), skill('SQL')], [estimate('Python', 'independent_application'), estimate('SQL', 'guided_application')]));
 const coding = group('Technical coding');
 expect(within(coding).getByRole('heading', {name: 'Technical coding'})).toBeVisible();
 expect(within(coding).getAllByRole('listitem')).toHaveLength(2);
 expect(within(coding).getByText('Independent')).toBeVisible();
 expect(within(coding).queryByText('SQL', {selector: 'summary'})).not.toBeInTheDocument();
 expect(within(group('Data & analytics')).getByText('SQL', {selector: 'summary'})).toBeVisible();
 expect(screen.getByText(/in 2 categories/)).toBeVisible();
});

it('links to each category with its skill count',() => {
 view(cv([skill('Python'), skill('FastAPI'), skill('SQL')]));
 const nav = screen.getByRole('navigation', {name: 'Categories of your skills'});
 const link = within(nav).getByRole('link', {name: /Technical coding/});
 expect(link).toHaveTextContent('Technical coding2');
 expect(link).toHaveAttribute('href', `#${group('Technical coding').id}`);
});

it('shows only the categories the backend sent, with unknown skills under Other, last', () => {
 view(cv([skill('Basket weaving', 'Technical'), skill('Python')]));
 expect(screen.getAllByRole('heading', {level: 3}).map(heading => heading.textContent)).toEqual(['Technical coding', OTHER_SKILLS]);
});

it('lists the strongest skills first', () => {
 view(cv([skill('FastAPI'), skill('Python')], [estimate('Python', 'complex_application')]));
 const names = within(group('Technical coding')).getAllByRole('listitem').map(item => item.querySelector('summary')!.firstChild!.textContent);
 expect(names).toEqual(['Python', 'FastAPI']);
});

it('shows the strongest level across experiences', () => {
 view(cv([skill('Python')], [estimate('Python', 'guided_application'), estimate('Python', 'independent_application', 'project-two')]));
 expect(within(row('Python')).getByText('Independent')).toBeVisible();
 expect(within(row('Python')).queryByText('Guided')).not.toBeInTheDocument();
});

it('never presents insufficient evidence as a level or invents one', () => {
 view(cv([skill('SQL')], [estimate('SQL', 'insufficient_evidence')]));
 expect(within(row('SQL')).getByText('Level not established')).toBeVisible();
 expect(row('SQL').querySelector('.skill-level-meter')).toBeNull();
 expect(screen.queryByText(/insufficient/i)).not.toBeInTheDocument();
 expect(screen.queryByText(/private-ref|project-one/)).not.toBeInTheDocument();
 expect(screen.getByText(/with an established level/)).toHaveTextContent('1 skill in 1 category, 0 with an established level');
});

it('keeps evidence and contribution behind the row details', () => {
 view(cv([skill('Python')]));
 const details = row('Python').querySelector('details')!;
 expect(details.open).toBe(false);
 expect(within(details).getByText('Used Python on a synthetic project.')).toBeInTheDocument();
 expect(within(details).getByText('Contribution: personal. Support: assisted.')).toBeInTheDocument();
});

it('includes described and manually added skills with their own labels', () => {
 const declarations = {version: 1, declarations: [{id: 'manual-one', name: 'Technical writing', description: 'Wrote synthetic guides.'}]} as unknown as Declarations;
 view(null, profile('draft'), declarations);
 expect(within(row('Data processing')).getByText('Proposed — review before saving')).toBeVisible();
 expect(within(row('Technical writing')).getByText('Added by you')).toBeVisible();
 expect(within(row('Technical writing')).getByText('Wrote synthetic guides.')).toBeInTheDocument();
});

it('merges the same skill from several sources into one row', () => {
 view(cv([skill('Python')], [estimate('Python', 'guided_application')]), profile('saved', 'python'));
 expect(screen.getAllByRole('listitem')).toHaveLength(1);
 expect(within(row('Python')).getByText('Guided')).toBeVisible();
 expect(within(row('Python')).getByText('Used Python on a synthetic project.')).toBeInTheDocument();
 expect(within(row('Python')).getByText('Described in chat.')).toBeInTheDocument();
});
