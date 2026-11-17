import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {SkillsOverview} from './skills-overview';
import {evaluatedSkill, profileSkillGroups, profileSkillList, skillStatus} from './skill-cards';
import type {Comparison} from '@/features/assessment/comparison';
import {rateSkill, skillRatings} from '@/lib/api/assessment';

vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(), skillRatings: vi.fn(), rateSkill: vi.fn()}));
import type {CvDetail, CvSkill, Declarations, SkillEstimate, SkillsProfile} from './types';
import type {Assessment} from '@/features/roadmap/types';

const skill = (name: string, category = 'unspecified', item = 'project-one'): CvSkill => ({skill_id: name.toLowerCase(), name, category, proficiency: null, experience_months: null, context: null, evidence: [], evidence_type: 'explicit', explicit: true, item_ids: [item],
 sources: [{item_id: item, evidence_type: 'explicit', explicit: true, support_uncertain: false, attribution: 'personal', assistance: 'assisted', proficiency: null, experience_months: null, evidence: [{id: 'evidence-one', excerpt: `Used ${name} on a synthetic project.`, location: 'Page 1'}]}]});
const estimate = (skill_name: string, level: SkillEstimate['level'], item_id = 'project-one'): SkillEstimate => ({item_id, skill_name, level, explanation: 'Synthetic explanation.', evidence_refs: ['private-ref']});
const groups = {Python: 'Technical coding', FastAPI: 'Technical coding', SQL: 'Data & analytics', 'Data processing': 'Data & analytics'};
const cv = (skills: CvSkill[], skill_estimates: SkillEstimate[] = []) => ({skills, skill_estimates, skill_groups: groups, items: [{id: 'project-one', kind: 'project', title: 'Reporting API'}]}) as unknown as CvDetail;

import {cvApi} from '@/lib/api/cv';
const profile = (status: 'draft' | 'saved', name = 'Data processing') => ({status, entries: [{id: 'entry-one', kind: 'work', title: 'Weekly reports', fields: {}, skills: [{name, description: 'Described in chat.', dimensions: {}, evidence: []}]}]}) as unknown as SkillsProfile;
const outcome = (changes: Partial<Assessment['job_skill_gaps'][number]>) => ({ref: 'job:x', name: 'X', match_status: 'partial' as const, components: [], ...changes});
const comparison = (job_skill_gaps: Assessment['job_skill_gaps']) => ({job_skill_gaps, evidence: {}} as unknown as Assessment);
const judged = (skills: Partial<NonNullable<Assessment['skill_profile']>['skills'][number]>[]) => ({job_skill_gaps: [], evidence: {}, skill_profile: {status: 'evaluated', rubric_version: 'skill-profile-llm-v1',
 skills: skills.map(item => ({name: 'Python', canonical_skill_id: null, category: 'Technical coding', subcategory: null, relevance: 'high', competence_score: null, required_score: null, explanation: 'Synthetic explanation.', evidence_refs: [], requirement_refs: [], ...item}))}} as unknown as Assessment);

beforeEach(()=>{vi.mocked(skillRatings).mockResolvedValue({version:0,ratings:[]});vi.mocked(rateSkill).mockReset();});
const noComparison={current:null,context:null,result:null,matches:null,outcomes:null,error:'',busy:false,compare:vi.fn(),retry:vi.fn()} as unknown as Comparison;
const ready=(goal:object|null=null)=>({status:'ready' as const,data:{goal,selection_version:1,dependent_results_need_review:false}}) as never;
const view=(detail:CvDetail|null,profileValue:SkillsProfile|null=null,declarations:Declarations|null=null,assessment:Assessment|null=null,goal=ready())=>render(<SkillsOverview token="synthetic" skills={profileSkillList(detail,profileValue,declarations)} categories={profileSkillGroups(detail,profileValue,declarations)} assessment={assessment} comparison={noComparison} goal={goal} goalRole="Product Manager"/>);
const chip=(name:string)=>screen.getByRole('button',{name:new RegExp(`^${name},`)});
const dialog=(name:string)=>screen.getByRole('dialog',{name});

it('before a comparison, lists every skill under the backend’s categories with the strongest first',()=>{
 view(cv([skill('FastAPI'),skill('Python'),skill('SQL')],[estimate('Python','complex_application')]));
 expect(screen.getAllByRole('heading',{level:3}).map(heading=>heading.textContent)).toEqual(['Technical coding','Data & analytics']);
 expect(within(screen.getByRole('region',{name:'Technical coding'})).getAllByRole('button').map(button=>button.getAttribute('aria-label')?.split(',')[0])).toEqual(['Python','FastAPI']);
 expect(screen.queryByRole('button',{name:/Show all skills/})).not.toBeInTheDocument();
 expect(profileSkillList(cv([skill('Python')],[estimate('Python','independent_application')]),null,null)[0].label).toBe('Independent');
});

it('puts the skills the goal needs first with level and target, and the rest behind Show all skills',()=>{
 const detail=cv([{...skill('Python'),canonical_skill_id:'python'},skill('SQL'),skill('Tableau')]);
 view(detail,null,null,judged([
  {name:'Python',relevance:'high',competence_score:6,required_score:8},
  {name:'SQL',relevance:'medium',competence_score:8,required_score:8,category:'Data & analytics'},
  {name:'Tableau',category:'Data & analytics',relevance:'none',competence_score:3}]));
 expect(screen.getByRole('heading',{name:'Relevant to Product Manager'})).toBeVisible();
 expect(chip('Python')).toHaveTextContent('Python6/8');
 expect(chip('SQL')).toHaveTextContent('SQL8/8');
 expect(chip('Python').querySelector('.lv')).toHaveClass('getting');expect(chip('SQL').querySelector('.lv')).toHaveClass('ready');
 expect(screen.queryByRole('button',{name:/^Tableau/})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Show all skills (1 more)'}));
 expect(chip('Tableau')).toHaveTextContent('Tableau3');
 expect(chip('Tableau').querySelector('.lv')).toHaveClass('neutral');
 fireEvent.click(screen.getByRole('button',{name:'Show fewer'}));
 expect(screen.queryByRole('button',{name:/^Tableau/})).not.toBeInTheDocument();
});

it('shows the CV review level without a comparison and never invents one for insufficient evidence',()=>{
 const python={...skill('Python'),skill_level:{level:2,status:'rated' as const,rationale:'Guided use.',source:'review' as const,evidence:[]}};
 view(cv([python,skill('SQL')],[estimate('SQL','insufficient_evidence')]));
 expect(chip('Python')).toHaveAccessibleName('Python, Level 2 out of 10. Talk it through');
 expect(chip('SQL')).toHaveAccessibleName('SQL, Not rated. Talk it through');
 expect(screen.queryByText(/insufficient/i)).not.toBeInTheDocument();
 expect(profileSkillList(cv([skill('SQL')],[estimate('SQL','insufficient_evidence')]),null,null)[0].established).toBe(false);
});

it('opens Talk it through on a skill, with the role’s target, review note and where the level comes from',()=>{
 const python={...skill('Python'),canonical_skill_id:'python'};
 const goal=ready({skills:[{name:'Python',canonical_skill_id:'python',competence_target:{level:8,explanation:'You can ship it unaided.'},learning_items:[{name:'Build a CLI',reason:'Shows independent delivery.'}]}]});
 view({...cv([python]),review_summary:{answered_questions:1,experiences:1,skills_added:0,skills_corrected:0,skills_removed:0,added_skill_ids:[],skill_notes:{python:'You wrote the ETL scripts yourself.'}}} as unknown as CvDetail,null,null,judged([{name:'Python',canonical_skill_id:'python',competence_score:6,required_score:8}]),goal);
 fireEvent.click(chip('Python'));
 const panel=dialog('Python');
 expect(panel).toHaveTextContent(/target for Python is 8 out of 10\. You can ship it unaided\./);
 expect(within(panel).getByText(/You’re at 6 now, based on Reporting API\. From your CV review: You wrote the ETL scripts yourself\./)).toBeVisible();
 fireEvent.click(within(panel).getByRole('button',{name:'Not yet, help me build it'}));
 expect(within(panel).getByText('Build a CLI')).toBeVisible();
 expect(within(panel).getByRole('button',{name:'Add to my roadmap'})).toBeVisible();
 fireEvent.click(within(panel).getByRole('button',{name:'Close chat'}));
});

it('saves what the person tells elo as evidence on the Skills Profile and can take it back',async()=>{
 const base={version:1,declarations:[]};
 const added={version:2,declarations:[{id:'d1',name:'SQL',description:'Cleaned café sales.',skill_id:'skill:sql',provenance:'user_declared',contributions:[{id:'c1',description:'Cleaned café sales.\nTools used: Excel',created_at:'2026-11-17T00:00:00Z'}],created_at:'2026-11-17T00:00:00Z',updated_at:'2026-11-17T00:00:00Z'}]};
 vi.spyOn(cvApi,'declarations').mockResolvedValueOnce(base as never).mockResolvedValue(added as never);
 const addDeclaration=vi.spyOn(cvApi,'addDeclaration').mockResolvedValue(added as never);
 const withdraw=vi.spyOn(cvApi,'withdrawDeclaration').mockResolvedValue(base as never);
 view(cv([skill('SQL'),skill('Excel')]));
 fireEvent.click(chip('SQL'));
 const panel=dialog('SQL');
 fireEvent.click(within(panel).getByRole('button',{name:'Yes, let me tell you'}));
 fireEvent.change(within(panel).getByRole('textbox',{name:'Your answer'}),{target:{value:'Cleaned café sales.'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Send'}));
 fireEvent.click(await within(panel).findByRole('button',{name:'Excel'}));
 fireEvent.click(within(panel).getByRole('button',{name:'Done'}));
 await waitFor(()=>expect(addDeclaration).toHaveBeenCalledWith(expect.objectContaining({expected_version:1,name:'SQL',description:'Cleaned café sales.\nTools used: Excel',mode:'new'}),'synthetic',expect.any(AbortSignal)));
 expect(await within(panel).findByText(/I’ve added it to your Skills Profile/)).toBeVisible();
 expect(withdraw).not.toHaveBeenCalled();
});

it('merges the same skill from several sources into one chip and labels described and added skills',()=>{
 view(cv([skill('Python')],[estimate('Python','guided_application')]),profile('saved','python'));
 expect(screen.getAllByRole('button',{name:/^Python,/i})).toHaveLength(1);
 expect(profileSkillList(cv([skill('Python')],[estimate('Python','guided_application')]),profile('saved','python'),null)[0].label).toBe('Guided');
 const declarations={version:1,declarations:[{id:'manual-one',name:'Technical writing',description:'Wrote synthetic guides.'}]} as unknown as Declarations;
 expect(profileSkillList(null,profile('draft'),declarations).find(item=>item.name==='Data processing')?.label).toBe('Proposed — review before saving');
 expect(profileSkillList(null,profile('draft'),declarations).find(item=>item.name==='Technical writing')?.label).toBe('Added by you');
});

it.each([
 ['no related goal requirement',[],'not_needed'],
 ['a requirement the review has not covered',[outcome({canonical_skill_id:'python',score_status:'not_reviewed',relevance:'high'})],'not_recorded'],
 ['a requirement without enough evidence',[outcome({canonical_skill_id:'python',score_status:'insufficient_evidence',relevance:'medium'})],'unknown'],
])('reads exactly one state for %s',(_,gaps,state)=>{
 const [python]=profileSkillList(cv([{...skill('Python'),canonical_skill_id:'python'}]),null,null);
 expect(skillStatus(python,comparison(gaps)).state).toBe(state);
 expect(skillStatus(python,null).state).toBe('not_compared');
});

it('uses the comparison’s per-skill judgement, falling back to requirement outcomes for skills it does not cover',()=>{
 const [python,sql]=profileSkillList(cv([{...skill('Python'),canonical_skill_id:'python'},skill('SQL')]),null,null);
 const value={...judged([{name:'SQL',relevance:'medium',competence_score:5,required_score:7}]),job_skill_gaps:[outcome({canonical_skill_id:'python',relevance:'low',competence_score:4,required_score:6,score_status:'estimated'})]} as Assessment;
 expect(evaluatedSkill(sql,value)?.name).toBe('SQL');
 expect(skillStatus(sql,value)).toMatchObject({relevance:'medium',state:'score',score:5,need:7});
 expect(skillStatus(python,value)).toMatchObject({relevance:'low',state:'score',score:4,need:6});
});

it('rates an unrated skill the person’s own level',async()=>{
 vi.mocked(skillRatings).mockResolvedValue({version:3,ratings:[]});
 vi.mocked(rateSkill).mockResolvedValue({version:4,ratings:[]});
 view(cv([skill('FastAPI')]),null,null,judged([{name:'FastAPI',competence_score:null}]));
 fireEvent.click(chip('FastAPI'));
 const panel=dialog('FastAPI');
 fireEvent.click(await within(panel).findByRole('button',{name:'Set my own level'}));
 fireEvent.change(within(panel).getByRole('slider'),{target:{value:'7'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Save my rating'}));
 await waitFor(()=>expect(rateSkill).toHaveBeenCalledWith('synthetic',{expected_version:3,name:'FastAPI',canonical_skill_id:null,score:7}));
 expect(await within(panel).findByText(/You set FastAPI to 7 \/ 10/)).toBeVisible();
});

it('shows a saved own rating on the chip when elo has no score for the skill',async()=>{
 vi.mocked(skillRatings).mockResolvedValue({version:3,ratings:[{key:'fastapi',name:'FastAPI',canonical_skill_id:null,score:7,updated_at:'2026-11-12T00:00:00Z'}]});
 view(cv([skill('FastAPI')]));
 await waitFor(()=>expect(chip('FastAPI')).toHaveAccessibleName('FastAPI, Level 7 out of 10, your rating. Talk it through'));
});
