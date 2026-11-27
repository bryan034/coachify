import {fireEvent, render, screen, waitFor, within} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {SkillsOverview,targetGap} from './skills-overview';
import {evaluatedSkill, skillCards, skillCardGroups, skillStatus} from './skill-cards';
import type {Comparison} from '@/features/assessment/comparison';
import {rateSkill, reevaluateSkill, skillChat, skillChatHistory, skillRatings} from '@/lib/api/assessment';

vi.mock('@/lib/api/assessment', async original => ({...await original<typeof import('@/lib/api/assessment')>(), skillRatings: vi.fn(), rateSkill: vi.fn(), reevaluateSkill: vi.fn(), skillChat: vi.fn(), skillChatHistory: vi.fn()}));
import type {CvDetail, CvSkill, ListedSkill, SkillEstimate, SkillList} from './types';
import type {Assessment} from '@/features/roadmap/types';

const skill = (name: string, category = 'unspecified', item = 'project-one'): CvSkill => ({skill_id: name.toLowerCase(), name, category, proficiency: null, experience_months: null, context: null, evidence: [], evidence_type: 'explicit', explicit: true, item_ids: [item],
 sources: [{item_id: item, evidence_type: 'explicit', explicit: true, support_uncertain: false, attribution: 'personal', assistance: 'assisted', proficiency: null, experience_months: null, evidence: [{id: 'evidence-one', excerpt: `Used ${name} on a synthetic project.`, location: 'Page 1'}]}]});
const estimate = (skill_name: string, level: SkillEstimate['level'], item_id = 'project-one'): SkillEstimate => ({item_id, skill_name, level, explanation: 'Synthetic explanation.', evidence_refs: ['private-ref']});
const groups = {Python: 'Technical coding', FastAPI: 'Technical coding', SQL: 'Data & analytics', 'Data processing': 'Data & analytics'};
const cv = (skills: CvSkill[], skill_estimates: SkillEstimate[] = []) => ({skills, skill_estimates, skill_groups: groups, items: [{id: 'project-one', kind: 'project', title: 'Reporting API'}]}) as unknown as CvDetail;

import {cvApi} from '@/lib/api/cv';
const outcome = (changes: Partial<Assessment['job_skill_gaps'][number]>) => ({ref: 'job:x', name: 'X', match_status: 'partial' as const, components: [], ...changes});
const comparison = (job_skill_gaps: Assessment['job_skill_gaps']) => ({job_skill_gaps, evidence: {}} as unknown as Assessment);
const judged = (skills: Partial<NonNullable<Assessment['skill_profile']>['skills'][number]>[]) => ({job_skill_gaps: [], evidence: {}, skill_profile: {status: 'evaluated', rubric_version: 'skill-profile-llm-v1',
 skills: skills.map(item => ({name: 'Python', canonical_skill_id: null, category: 'Technical coding', subcategory: null, relevance: 'high', competence_score: null, required_score: null, explanation: 'Synthetic explanation.', evidence_refs: [], requirement_refs: [], ...item}))}} as unknown as Assessment);

beforeEach(()=>{vi.mocked(skillRatings).mockResolvedValue({version:0,ratings:[]});vi.mocked(rateSkill).mockReset();vi.mocked(skillChatHistory).mockReset().mockResolvedValue({turns:[]});});
const noComparison={current:null,context:null,result:null,matches:null,outcomes:null,error:'',busy:false,compare:vi.fn(),retry:vi.fn()} as unknown as Comparison;
const ready=(goal:object|null=null)=>({status:'ready' as const,data:{goal,selection_version:1,dependent_results_need_review:false}}) as never;
const listed = (name: string, fields: Partial<ListedSkill> = {}): ListedSkill => ({
 key: name.toLowerCase(), name, basis: 'none', sources: [], ...fields,
});
const response = (data: ListedSkill[], categories = groups): SkillList => ({
 cv_id: null, cv_version: null, profile_version: 0, declarations_version: 0, skills: data,
 skill_groups: categories, skill_subgroups: {},
});
const fromCv = (detail: CvDetail | null) => response((detail?.skills ?? []).map(skill => {
 const estimate = detail?.skill_estimates?.find(value => value.skill_name === skill.name)?.level;
 const application = estimate === 'insufficient_evidence' ? null : estimate;
 return listed(skill.name, {canonical_skill_id: skill.canonical_skill_id, level: skill.skill_level, application,
  basis: skill.skill_level ? 'level' : application ? 'application' : 'none', note: detail?.review_summary?.skill_notes?.[skill.skill_id]});
}), {...Object.fromEntries((detail?.skills ?? []).filter(skill => skill.category !== 'unspecified').map(skill => [skill.name, skill.category])), ...groups});
const view=(detail:CvDetail|null,_profile:null=null,_declarations:null=null,assessment:Assessment|null=null,goal=ready())=>{
 const data = fromCv(detail);
 return render(<SkillsOverview token="synthetic" skills={skillCards(data)} categories={skillCardGroups(data)} assessment={assessment} comparison={noComparison} goal={goal} goalRole="Product Manager"/>);
};
const chip=(name:string)=>screen.getByRole('button',{name:new RegExp(`^${name},`)});
const dialog=(name:string)=>screen.getByRole('dialog',{name});

it('before a comparison, lists every skill under the backend’s categories with the strongest first',()=>{
 view(cv([skill('FastAPI'),skill('Python'),skill('SQL')],[estimate('Python','complex_application')]));
 expect(screen.getAllByRole('heading',{level:3}).map(heading=>heading.textContent)).toEqual(['Technical coding','Data & analytics']);
 expect(within(screen.getByRole('region',{name:'Technical coding'})).getAllByRole('button').map(button=>button.getAttribute('aria-label')?.split(',')[0])).toEqual(['Python','FastAPI']);
 expect(screen.queryByRole('button',{name:/Show all skills/})).not.toBeInTheDocument();
 expect(skillCards(fromCv(cv([skill('Python')],[estimate('Python','independent_application')])))[0].label).toBe('Independent');
});

it('shows only the skills the goal needs with level and target, and the rest behind Show all skills',()=>{
 const detail=cv([{...skill('Python'),canonical_skill_id:'python'},skill('SQL'),skill('Tableau')]);
 const goal=ready({skills:[{name:'Python',canonical_skill_id:'python',priority:'required'},{name:'SQL',priority:'unspecified'}]});
 view(detail,null,null,judged([
  {name:'Python',relevance:'high',competence_score:6,required_score:8},
  {name:'SQL',relevance:'medium',competence_score:8,required_score:8,category:'Data & analytics'},
  {name:'Tableau',category:'Data & analytics',relevance:'medium',competence_score:3}]),goal);
 expect(chip('Python')).toHaveTextContent('Python6/8');
 expect(chip('SQL')).toHaveTextContent('SQL8/8');
 expect(chip('Python').querySelector('.lv')?.className).toBe('lv near');expect(chip('SQL').querySelector('.lv')?.className).toBe('lv met');
 expect(chip('Python')).toHaveClass('important');
 expect(screen.queryByRole('button',{name:/^Tableau/})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'Show all skills (1 more)'}));
 expect(chip('Tableau')).toHaveTextContent('Tableau3');
 expect(chip('Tableau').querySelector('.lv')?.className).toBe('lv');
 fireEvent.click(screen.getByRole('button',{name:'Show fewer'}));
 expect(screen.queryByRole('button',{name:/^Tableau/})).not.toBeInTheDocument();
});

it('shows the CV review level without a comparison and never invents one for insufficient evidence',()=>{
 const python={...skill('Python'),skill_level:{level:2,status:'rated' as const,rationale:'Guided use.',source:'review' as const,evidence:[]}};
 view(cv([python,skill('SQL')],[estimate('SQL','insufficient_evidence')]));
 expect(chip('Python')).toHaveAccessibleName('Python, Level 2 out of 10. Talk it through');
 expect(chip('SQL')).toHaveAccessibleName('SQL, Not rated. Talk it through');
 expect(screen.queryByText(/insufficient/i)).not.toBeInTheDocument();
 expect(skillCards(fromCv(cv([skill('SQL')],[estimate('SQL','insufficient_evidence')])))[0].established).toBe(false);
});

it('opens the Skills Helper on a skill, with the role’s target, review note and where the level comes from',()=>{
 const python={...skill('Python'),canonical_skill_id:'python'};
 const goal=ready({skills:[{name:'Python',canonical_skill_id:'python',competence_target:{level:8,explanation:'You can ship it unaided.'},learning_items:[{name:'Build a CLI',reason:'Shows independent delivery.'}]}]});
 view({...cv([python]),review_summary:{answered_questions:1,experiences:1,skills_added:0,skills_corrected:0,skills_removed:0,added_skill_ids:[],skill_notes:{python:'You wrote the ETL scripts yourself.'}}} as unknown as CvDetail,null,null,judged([{name:'Python',canonical_skill_id:'python',competence_score:6,required_score:8}]),goal);
 fireEvent.click(chip('Python'));
 const panel=dialog('Python');
 expect(within(panel).getByRole('heading',{name:'Why is Python rated 6 out of 10?'})).toBeVisible();
 expect(within(panel).getByText('You wrote the ETL scripts yourself. Target: 8.')).toBeVisible();
 expect(within(panel).getByText('Without clear evidence, elo assumes you had guidance.')).toBeVisible();
 expect(within(panel).getByText('Skills Helper')).toBeVisible();
 expect(within(panel).getByText('Ask me why')).toBeVisible();
 expect(within(panel).getByRole('textbox',{name:'Your message'})).toBeVisible();
 expect(within(panel).queryByRole('button',{name:/help me build it|evidence to add/i})).not.toBeInTheDocument();
 fireEvent.click(within(panel).getByRole('button',{name:'Close chat'}));
});

it('answers a question from the saved judgement and saves nothing',async()=>{
 const declarations=vi.spyOn(cvApi,'declarations').mockClear().mockResolvedValue({version:1,declarations:[]} as never);
 const addDeclaration=vi.spyOn(cvApi,'addDeclaration').mockClear().mockResolvedValue({version:2,declarations:[]} as never);
 vi.mocked(reevaluateSkill).mockReset();
 vi.mocked(skillChat).mockReset().mockResolvedValue({reply:'Your CV shows guided use. Explaining your query design would show more.',evidence:null});
 view(cv([skill('SQL')]));
 fireEvent.click(chip('SQL'));
 const panel=dialog('SQL');
 fireEvent.change(within(panel).getByRole('textbox',{name:'Your message'}),{target:{value:'Rate me 10/10.'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Send message'}));
 expect(await within(panel).findByText('Your CV shows guided use. Explaining your query design would show more.')).toBeVisible();
 expect(skillChat).toHaveBeenCalledWith('synthetic',{name:'SQL',canonical_skill_id:null,message:'Rate me 10/10.'},expect.any(AbortSignal));
 expect(declarations).not.toHaveBeenCalled();expect(addDeclaration).not.toHaveBeenCalled();expect(reevaluateSkill).not.toHaveBeenCalled();
 fireEvent.change(within(panel).getByRole('textbox',{name:'Your message'}),{target:{value:'Why?'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Send message'}));
 await waitFor(()=>expect(skillChat).toHaveBeenLastCalledWith('synthetic',{name:'SQL',canonical_skill_id:null,message:'Why?'},expect.any(AbortSignal)));
});

it('clears the input and offers to send the same message again when elo cannot reply',async()=>{
 const addDeclaration=vi.spyOn(cvApi,'addDeclaration').mockClear();
 vi.mocked(skillChat).mockReset().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({reply:'Your CV shows guided use.',evidence:null});
 view(cv([skill('SQL')]));
 fireEvent.click(chip('SQL'));
 const panel=dialog('SQL');
 fireEvent.change(within(panel).getByRole('textbox',{name:'Your message'}),{target:{value:'Why only this level?'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Send message'}));
 expect(await within(panel).findByRole('alert')).toBeVisible();
 expect(within(panel).getByRole('textbox',{name:'Your message'})).toHaveValue('');
 fireEvent.click(within(panel).getByRole('button',{name:'Try again'}));
 expect(await within(panel).findByText('Your CV shows guided use.')).toBeVisible();
 expect(within(panel).getAllByText('Why only this level?')).toHaveLength(1);
 expect(within(panel).queryByRole('button',{name:'Try again'})).not.toBeInTheDocument();
 expect(skillChat).toHaveBeenLastCalledWith('synthetic',{name:'SQL',canonical_skill_id:null,message:'Why only this level?'},expect.any(AbortSignal));
 expect(addDeclaration).not.toHaveBeenCalled();
});

it('saves the experience elo heard as evidence, then re-judges only that skill',async()=>{
 const base={version:1,declarations:[]};
 vi.spyOn(cvApi,'declarations').mockResolvedValue(base as never);
 const addDeclaration=vi.spyOn(cvApi,'addDeclaration').mockResolvedValue({version:2,declarations:[]} as never);
 vi.mocked(skillChat).mockReset().mockResolvedValue({reply:'That helps. I’ll save it and check SQL again.',evidence:'I cleaned café sales data with SQL on my own.'});
 vi.mocked(reevaluateSkill).mockReset().mockResolvedValue({version:3,skill:{name:'SQL',canonical_skill_id:null,competence_score:5,required_score:7,relevance:'high',explanation:'You cleaned sales data yourself.'}});
 view(cv([skill('SQL'),skill('Excel')]));
 fireEvent.click(chip('SQL'));
 const panel=dialog('SQL');
 fireEvent.change(within(panel).getByRole('textbox',{name:'Your message'}),{target:{value:'i did the cafe sales cleanup myself lol'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Send message'}));
 await waitFor(()=>expect(addDeclaration).toHaveBeenCalledWith(expect.objectContaining({expected_version:1,name:'SQL',description:'I cleaned café sales data with SQL on my own.',mode:'new'}),'synthetic',expect.any(AbortSignal)));
 expect(within(panel).getByText('Saving to your Skills Profile: “I cleaned café sales data with SQL on my own.”')).toBeVisible();
 expect(reevaluateSkill).toHaveBeenCalledWith('synthetic',{name:'SQL',canonical_skill_id:null},expect.any(AbortSignal));
 expect(await within(panel).findByText('SQL: Not rated → 5')).toBeVisible();
 expect(within(panel).getByText('You cleaned sales data yourself.')).toBeVisible();
 await waitFor(()=>expect(within(panel).getByRole('textbox',{name:'Your message'})).toBeEnabled());
 vi.mocked(skillChat).mockResolvedValue({reply:'Noted.',evidence:null});
 fireEvent.change(within(panel).getByRole('textbox',{name:'Your message'}),{target:{value:'What next?'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Send message'}));
 await waitFor(()=>expect(skillChat).toHaveBeenLastCalledWith('synthetic',{name:'SQL',canonical_skill_id:null,message:'What next?'},expect.any(AbortSignal)));
});

it('shows the saved conversation for that skill when the helper opens again',async()=>{
 vi.mocked(skillChatHistory).mockResolvedValue({turns:[
  {role:'person',text:'I cleaned café sales data myself.',evidence:null,level:null,created_at:'2026-11-27T00:00:00Z'},
  {role:'elo',text:'That helps. I’ll save it and check SQL again.',evidence:'I cleaned café sales data with SQL on my own.',level:null,created_at:'2026-11-27T00:00:01Z'},
  {role:'elo',text:'You cleaned sales data yourself.',evidence:null,level:{before:null,after:5},created_at:'2026-11-27T00:00:02Z'}]});
 view(cv([skill('SQL'),skill('Excel')]));
 fireEvent.click(chip('SQL'));
 const panel=dialog('SQL');
 expect(await within(panel).findByText('I cleaned café sales data myself.')).toBeVisible();
 expect(within(panel).getByText('That helps. I’ll save it and check SQL again.')).toBeVisible();
 expect(within(panel).getByText('Your experience: “I cleaned café sales data with SQL on my own.”')).toBeVisible();
 expect(within(panel).getByText('SQL: Not rated → 5')).toBeVisible();
 expect(within(panel).getByText('You cleaned sales data yourself.')).toBeVisible();
 expect(skillChatHistory).toHaveBeenCalledWith('synthetic',{name:'SQL',canonical_skill_id:null},expect.any(AbortSignal));
});

it('offers to save the experience again instead of resending the message when saving fails',async()=>{
 vi.spyOn(cvApi,'declarations').mockResolvedValue({version:1,declarations:[]} as never);
 const addDeclaration=vi.spyOn(cvApi,'addDeclaration').mockClear().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({version:2,declarations:[]} as never);
 vi.mocked(skillChat).mockReset().mockResolvedValue({reply:'Thanks.',evidence:'I cleaned café sales data.'});
 vi.mocked(reevaluateSkill).mockReset().mockResolvedValue({version:3,skill:{name:'SQL',canonical_skill_id:null,competence_score:4,required_score:7,relevance:'high',explanation:'You cleaned data yourself.'}});
 view(cv([skill('SQL')]));
 fireEvent.click(chip('SQL'));
 const panel=dialog('SQL');
 fireEvent.change(within(panel).getByRole('textbox',{name:'Your message'}),{target:{value:'Cleaned café sales.'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Send message'}));
 fireEvent.click(await within(panel).findByRole('button',{name:'Try saving again'}));
 expect(within(panel).getByRole('textbox',{name:'Your message'})).toHaveValue('');
 expect(await within(panel).findByText('SQL: Not rated → 4')).toBeVisible();
 expect(addDeclaration).toHaveBeenCalledTimes(2);expect(skillChat).toHaveBeenCalledTimes(1);
});

it('keeps the evidence saved and says so when the skill cannot be re-judged yet',async()=>{
 vi.spyOn(cvApi,'declarations').mockResolvedValue({version:1,declarations:[]} as never);
 vi.spyOn(cvApi,'addDeclaration').mockResolvedValue({version:2,declarations:[]} as never);
 vi.mocked(skillChat).mockReset().mockResolvedValue({reply:'Thanks.',evidence:'I cleaned café sales data.'});
 vi.mocked(reevaluateSkill).mockReset().mockRejectedValue(Object.assign(new Error('x'),{status:409,code:'full_evaluation_required'}));
 view(cv([skill('SQL')]));
 fireEvent.click(chip('SQL'));
 const panel=dialog('SQL');
 fireEvent.change(within(panel).getByRole('textbox',{name:'Your message'}),{target:{value:'Cleaned café sales.'}});
 fireEvent.click(within(panel).getByRole('button',{name:'Send message'}));
 expect(await within(panel).findByText(/Your answer is saved\. Your level updates the next time/)).toBeVisible();
});

it('counts skills the evaluation linked to a goal skill or that are part of one, and shows missing smaller skills dotted',()=>{
 const goal=ready({skills:[{item_id:'py',name:'Python',priority:'required',learning_items:[{name:'pytest',reason:'Tests show reliable code.'},{name:'Type hints',reason:'Readable interfaces.'}]}]});
 const assessment={...comparison([outcome({ref:'job:py',name:'Python',profile_skills:[{name:'Pandas',competence_score:6,required_score:8}]})]),inputs:{goal_id:'g',goal_version:1,cv_id:null}} as Assessment;
 view(cv([skill('Python'),skill('Pandas'),skill('pytest'),skill('Docker')]),null,null,assessment,goal);
 for(const name of ['Python','Pandas','pytest'])expect(chip(name)).toHaveClass('important');
 expect(screen.queryByRole('button',{name:/^Docker,/})).not.toBeInTheDocument();
 expect(chip('Type hints')).toHaveAccessibleName('Type hints, Part of Python, not in your skills yet. Talk it through');
 expect(chip('Type hints')).toHaveClass('missing');
 expect(screen.queryByRole('button',{name:/^pytest, Part of/})).not.toBeInTheDocument();
});

it('lists only goal skills in each category, most important first, until Show all skills adds the rest',()=>{
 const goal=ready({skills:[{name:'FastAPI',priority:'preferred'},{name:'SQL',priority:'unspecified'},{name:'Python',priority:'required'}]});
 view(cv([skill('Docker','Cloud & DevOps'),skill('FastAPI'),skill('Python'),skill('SQL')]),null,null,null,goal);
 const names=(region:string)=>within(screen.getByRole('region',{name:region})).getAllByRole('button').map(button=>button.getAttribute('aria-label')?.split(',')[0]);
 expect(names('Technical coding')).toEqual(['Python','FastAPI']);
 expect(names('Data & analytics')).toEqual(['SQL']);
 expect(screen.queryByRole('button',{name:/^Docker,/})).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:/relevant to your goal/})).not.toBeInTheDocument();
 const toggle=screen.getByRole('button',{name:'Show all skills (1 more)'});
 expect(toggle.compareDocumentPosition(screen.getByRole('button',{name:/^Python,/}))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 fireEvent.click(toggle);
 expect(screen.getByRole('button',{name:/^Docker,/})).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'Show fewer'}));
 expect(screen.queryByRole('button',{name:/^Docker,/})).not.toBeInTheDocument();
});

it('adds goal skills the CV does not show with a dotted outline, explained in the legend',()=>{
 const goal={status:'ready' as const,data:{goal:{skills:[{name:'Python',priority:'required'},{name:'Kubernetes',canonical_skill_id:'kubernetes',priority:'required',competence_target:{level:6,explanation:'Deploys a service.'}},{name:'Cobol',priority:'conflicting'}]},skill_groups:{Kubernetes:'Cloud & DevOps'},selection_version:1,dependent_results_need_review:false}} as never;
 view(cv([skill('Python'),skill('SQL')]),null,null,null,goal);
 const expected=screen.getByRole('button',{name:'Kubernetes, Expected by your goal, not in your skills yet, target 6. Talk it through'});
 expect(expected).toHaveClass('ws-sc','missing','important');
 expect(within(screen.getByRole('region',{name:'Cloud & DevOps'})).getByRole('button',{name:/^Kubernetes,/})).toBe(expected);
 expect(chip('Python')).not.toHaveClass('missing');
 expect(screen.queryByRole('button',{name:/^Cobol,/})).not.toBeInTheDocument();
 expect(screen.getByText('Expected by your goal, not in your skills yet')).toBeInTheDocument();
 fireEvent.click(expected);
 expect(dialog('Kubernetes')).toBeVisible();
});

it('renders the merged skill once and labels the evidence returned by the service',()=>{
 const data = response([
  listed('Python', {basis:'application', application:'guided_application', sources:[
   {kind:'cv', id:'one', title:'Reporting API'}, {kind:'chat', id:'two', title:'Weekly reports'},
  ]}),
  listed('Data processing', {basis:'draft'}),
  listed('Technical writing', {basis:'declared'}),
 ]);
 const cards = skillCards(data);
 expect(cards.map(item => [item.name, item.label])).toEqual([
  ['Python', 'Guided'], ['Data processing', 'Proposed — review before saving'], ['Technical writing', 'Added by you'],
 ]);
 expect(cards[0].sources).toEqual(['Reporting API', 'Weekly reports']);
});

it.each([
 ['no related goal requirement',[],'not_needed'],
 ['a requirement the review has not covered',[outcome({canonical_skill_id:'python',score_status:'not_reviewed',relevance:'high'})],'not_recorded'],
 ['a requirement without enough evidence',[outcome({canonical_skill_id:'python',score_status:'insufficient_evidence',relevance:'medium'})],'unknown'],
])('reads exactly one state for %s',(_,gaps,state)=>{
 const [python]=skillCards(fromCv(cv([{...skill('Python'),canonical_skill_id:'python'}])));
 expect(skillStatus(python,comparison(gaps)).state).toBe(state);
 expect(skillStatus(python,null).state).toBe('not_compared');
});

it('uses the comparison’s per-skill judgement, falling back to requirement outcomes for skills it does not cover',()=>{
 const [python,sql]=skillCards(fromCv(cv([{...skill('Python'),canonical_skill_id:'python'},skill('SQL')])));
 const value={...judged([{name:'SQL',relevance:'medium',competence_score:5,required_score:7}]),job_skill_gaps:[outcome({canonical_skill_id:'python',relevance:'low',competence_score:4,required_score:6,score_status:'estimated'})]} as Assessment;
 expect(evaluatedSkill(sql,value)?.name).toBe('SQL');
 expect(skillStatus(sql,value)).toMatchObject({relevance:'medium',state:'score',score:5,need:7});
 expect(skillStatus(python,value)).toMatchObject({relevance:'low',state:'score',score:4,need:6});
});

it('shows a saved own rating on the chip when elo has no score for the skill',async()=>{
 vi.mocked(skillRatings).mockResolvedValue({version:3,ratings:[{key:'fastapi',name:'FastAPI',canonical_skill_id:null,score:7,updated_at:'2026-11-12T00:00:00Z'}]});
 view(cv([skill('FastAPI')]));
 await waitFor(()=>expect(chip('FastAPI')).toHaveAccessibleName('FastAPI, Level 7 out of 10, your rating. Talk it through'));
});

it('colours a rating by its distance from the target',()=>{
 expect([targetGap(9,8),targetGap(8,8),targetGap(6,8),targetGap(5,8),targetGap(2,9),targetGap(4,null)]).toEqual(['met','met','near','far','far',null]);
});

it('labels assumed CV ratings as estimates on the skill chip', () => {
 const python = {...skill('Python'), skill_level:{level:2, status:'assumed' as const, rationale:'Limited evidence.', source:'review' as const, evidence:[]}};
 view(cv([python]));
 expect(chip('Python')).toHaveAccessibleName('Python, Estimated level 2 out of 10. Talk it through');
 expect(chip('Python')).toHaveTextContent('est.');
 fireEvent.click(chip('Python'));
 expect(within(dialog('Python')).getByRole('heading', {name:'Why is Python estimated at 2 out of 10?'})).toBeVisible();
});

it('keeps focus in the message box when the page re-renders while the helper is open',async()=>{
 const data=fromCv(cv([skill('SQL')]));
 const page=()=><SkillsOverview token="synthetic" skills={skillCards(data)} categories={skillCardGroups(data)} assessment={null} comparison={noComparison} goal={ready()} goalRole="Product Manager"/>;
 const {rerender}=render(page());
 fireEvent.click(chip('SQL'));
 const box=within(dialog('SQL')).getByRole('textbox',{name:'Your message'});
 await new Promise(resolve=>setTimeout(resolve,100));
 box.focus();
 rerender(page());
 await new Promise(resolve=>setTimeout(resolve,100));
 expect(box).toHaveFocus();
});
