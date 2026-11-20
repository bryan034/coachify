import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {OpportunityIntelligence} from './opportunity-intelligence';
import {careerApi,type BriefView,type InterviewBrief,type OpportunityView,type RoleBrief} from '@/lib/api/career';
import {interviewBrief,roleBrief} from '../../../tests/fixtures/research-brief';
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));

const base={status:'completed' as const,findings:[],missing_fields:[],warnings:[],error_code:null,researched_at:'2026-11-21T08:00:00Z',expires_at:null,searches:1,model_calls:1,latency_ms:100,estimated_cost_usd:null};
let research:OpportunityView;let role:BriefView<RoleBrief>;let interview:BriefView<InterviewBrief>;
const scrolled=vi.fn();
function mockApi(overrides:{post?:BriefView<RoleBrief|InterviewBrief>;fail?:boolean}={}){
 vi.mocked(careerApi).mockImplementation(async(path:string,_token,init)=>{
  if(path.endsWith('/progress'))return {result_version:'v1',finished:true} as never;
  if(path.includes('/v2/')){
   if(overrides.fail)throw new Error('unavailable');
   if(init?.method==='POST')return overrides.post as never;
   return (path.endsWith('/role-research')?role:interview) as never;
  }
  return research as never;
 });
}
beforeEach(()=>{
 vi.resetAllMocks();
 Element.prototype.scrollIntoView=scrolled;
 research={available:true,status:'completed',finished:true,job_id:'job',career_target_id:'goal',research_id:'research',error_code:null,
  categories:{interview_intelligence:base,internship_insights:base,career_progression:base,conversion_outcomes:base,company_intelligence:base}};
 role={status:'ready',brief:structuredClone(roleBrief)};interview={status:'ready',brief:structuredClone(interviewBrief)};
 mockApi();
});
const renderRole=()=>render(<OpportunityIntelligence section="role" goalId="goal" version={3} selectionVersion={2}/>);
const renderInterview=()=>render(<OpportunityIntelligence section="interview" goalId="goal" version={3} selectionVersion={2}/>);
const panel=(name:string)=>screen.getByRole('region',{name});

it('leads About the role with the summary, a four-fact strip and the research line',async()=>{
 renderRole();
 expect(await screen.findByText(roleBrief.summary)).toBeVisible();
 expect(screen.getByRole('note')).toHaveTextContent('Researched 21 Nov 2026 from 7 public sources. AI can get details wrong, so check the sources before relying on them.');
 expect(screen.getByRole('note')).toHaveTextContent('Items tagged Estimated are AI suggestions, not from a source.');
 const strip=document.querySelector<HTMLElement>('dl[aria-label="Key facts"]')!;
 expect(within(strip).getAllByRole('term').map(term=>term.textContent)).toEqual(['Who can apply','Work setup','Reviews','After the internship']);
 expect(within(strip).getByRole('link',{name:'Source 1: GenAI Intern job description'})).toHaveAttribute('href','#role-src-1');
 const after=within(strip).getByText('After the internship').parentElement!;
 expect(within(after).getByText('Estimated')).toBeVisible();
});

it('shows four duties and reveals the rest',async()=>{
 renderRole();
 const duties=within(await screen.findByRole('region',{name:'What you would do'}));
 expect(duties.getAllByRole('listitem')).toHaveLength(4);
 const more=duties.getByRole('button',{name:'Show 2 more'});
 expect(more).toHaveAttribute('aria-expanded','false');
 fireEvent.click(more);
 expect(duties.getAllByRole('listitem')).toHaveLength(6);
 expect(duties.getByRole('button',{name:'Show fewer'})).toHaveAttribute('aria-expanded','true');
});

it('keeps raw reports and their citations behind each topic toggle',async()=>{
 renderRole();
 const topics=within(await screen.findByRole('region',{name:'What it is like'}));
 const mentorship=topics.getByRole('heading',{name:'Mentorship'}).closest('article')!;
 expect(within(mentorship).getByText('Good when your team has time, thin when it is busy.')).toBeVisible();
 expect(within(mentorship).getByText('Mixed')).toBeVisible();
 expect(within(mentorship).getByText('Conflicting reports')).toBeVisible();
 expect(within(mentorship).queryByText(/limited time to mentor/)).not.toBeVisible();
 const toggle=within(mentorship).getByRole('button',{name:'Show 2 reports'});
 expect(toggle).toHaveAttribute('aria-expanded','false');
 fireEvent.click(toggle);
 expect(within(mentorship).getByText(/limited time to mentor/)).toBeVisible();
 expect(within(mentorship).getByRole('link',{name:'Source 5: Internship post'})).toBeVisible();
 expect(within(mentorship).getByRole('button',{name:'Hide reports'})).toHaveAttribute('aria-expanded','true');
 const team=topics.getByRole('heading',{name:'Team and culture'}).closest('article')!;
 expect(within(team).getByText('Estimated')).toBeVisible();
 expect(within(team).queryByRole('button')).toBeNull();
 expect(within(topics.getByRole('heading',{name:'Management'}).closest('article')!).getByText('Negative')).toBeVisible();
});

it('lists pay with citations, gaps as dashed chips, and the first five sources in citation order',async()=>{
 renderRole();
 const pay=within(await screen.findByRole('region',{name:'Pay and what comes after'}));
 expect(pay.getByText('S$1,799/mo')).toBeVisible();
 expect(pay.getByRole('link',{name:'Source 6: Business Analyst Intern salaries'})).toBeVisible();
 expect(within(panel('Not found yet')).getAllByRole('listitem').map(li=>li.textContent)).toEqual(['Benefits','Typical projects','Conversion rate','Intake size']);
 const sources=within(panel('Sources'));
 expect(sources.getAllByRole('listitem').map(li=>li.textContent)).toEqual([
  '1GenAI Intern job description (opens in a new tab)Example Health','2Encouraging and collaborative team (opens in a new tab)Glassdoor','3Employee reviews about management (opens in a new tab)Indeed',
  '4Example Health intern reviews (opens in a new tab)Glassdoor','5Internship post (opens in a new tab)LinkedIn']);
 expect(sources.getAllByRole('link')[0]).toHaveAttribute('href','https://example.test/source-1');
 const all=sources.getByRole('button',{name:'Show all 7 sources'});
 fireEvent.click(all);
 expect(sources.getAllByRole('listitem')).toHaveLength(7);
 fireEvent.click(sources.getByRole('button',{name:'Show fewer sources'}));
 expect(sources.getAllByRole('listitem')).toHaveLength(5);
});

it('opens the source list at a hidden citation, scrolls to it and highlights it',async()=>{
 renderRole();
 const pay=within(await screen.findByRole('region',{name:'Pay and what comes after'}));
 fireEvent.click(pay.getByRole('link',{name:'Source 7: Business Analyst salary estimate'}));
 const row=document.getElementById('role-src-7')!;
 await waitFor(()=>expect(row).toHaveClass('is-flash'));
 expect(scrolled).toHaveBeenCalled();
 expect(within(row).getByRole('link')).toHaveFocus();
 expect(within(panel('Sources')).getByRole('button',{name:'Show fewer sources'})).toHaveAttribute('aria-expanded','true');
});

it('resolves every citation chip to the source with the same number',async()=>{
 renderRole();
 await screen.findByText(roleBrief.summary);
 fireEvent.click(screen.getByRole('button',{name:'Show all 7 sources'}));
 document.querySelectorAll('[hidden]').forEach(node=>node.removeAttribute('hidden'));
 const chips=[...document.querySelectorAll<HTMLAnchorElement>('a.brief-cite')];
 expect(chips.length).toBeGreaterThan(10);
 for(const chip of chips){
  const n=chip.textContent!;
  const row=document.getElementById(`role-src-${n}`)!;
  expect(chip.getAttribute('href')).toBe(`#role-src-${n}`);
  expect(chip).toHaveAccessibleName(`Source ${n}: ${roleBrief.sources[Number(n)-1].title}`);
  expect(row.textContent).toContain(roleBrief.sources[Number(n)-1].title);
 }
});

it('hides empty sections and names them under Not found yet',async()=>{
 role={status:'ready',brief:{...structuredClone(roleBrief),duties:[],pay:[],notFound:['Benefits']}};
 renderRole();
 await screen.findByText(roleBrief.summary);
 expect(screen.queryByRole('region',{name:'What you would do'})).toBeNull();
 expect(screen.queryByRole('region',{name:'Pay and what comes after'})).toBeNull();
 expect(within(panel('Not found yet')).getAllByRole('listitem').map(li=>li.textContent)).toEqual(['Benefits','What you would do','Pay and what comes after']);
});

it('generates the brief once research settles and keeps waiting while it runs',async()=>{
 role={status:'missing',brief:null};
 mockApi({post:{status:'ready',brief:roleBrief}});
 renderRole();
 expect(await screen.findByText(roleBrief.summary)).toBeVisible();
 const post=vi.mocked(careerApi).mock.calls.find(call=>call[0]==='/goals/goal/v2/role-research'&&call[2]?.method==='POST')!;
 expect(JSON.parse(post[2]!.body as string)).toEqual({expected_version:3});
});

it('does not read the brief while research is still running',async()=>{
 research={...research,finished:false,status:'running',categories:{...research.categories,internship_insights:{...base,status:'running'}}};
 renderRole();
 expect(await screen.findByText(/Researching…/)).toBeVisible();
 expect(vi.mocked(careerApi).mock.calls.some(call=>call[0].includes('/v2/'))).toBe(false);
 expect(screen.getByRole('note')).toHaveTextContent('No completed research yet.');
});

it('reports a brief failure with a retry instead of showing stale prose',async()=>{
 mockApi({fail:true});
 renderRole();
 const alert=await screen.findByRole('alert');
 expect(alert).toHaveTextContent('The research summary could not be prepared.');
 mockApi();
 fireEvent.click(within(alert).getByRole('button',{name:'Retry summary'}));
 expect(await screen.findByText(roleBrief.summary)).toBeVisible();
});

it('rejects a malformed brief',async()=>{
 role={status:'ready',brief:{summary:'Prose only'} as RoleBrief};
 renderRole();
 expect(await screen.findByRole('alert')).toHaveTextContent('could not be prepared');
 expect(screen.queryByText('Prose only')).toBeNull();
});

it('refreshes role research for every role category',async()=>{
 renderRole();
 await screen.findByText(roleBrief.summary);
 fireEvent.click(screen.getByRole('button',{name:'Refresh research'}));
 await waitFor(()=>expect(vi.mocked(careerApi).mock.calls.some(call=>call[0]==='/goals/goal/opportunity-research'&&call[2]?.method==='POST')).toBe(true));
 const post=vi.mocked(careerApi).mock.calls.find(call=>call[0]==='/goals/goal/opportunity-research'&&call[2]?.method==='POST')!;
 expect(JSON.parse(post[2]!.body as string)).toMatchObject({expected_version:3,expected_selection_version:2,refresh:true,category:null});
});

it('shows the interview process, difficulty and one accordion of questions with how to prepare',async()=>{
 renderInterview();
 expect(await screen.findByText(interviewBrief.summary)).toBeVisible();
 const steps=within(screen.getByRole('list',{name:'Interview process'}));
 expect(steps.getAllByRole('listitem').map(li=>li.querySelector('.brief-cell-value')!.textContent)).toEqual(['Apply','HR call','Manager interview']);
 expect(screen.getByRole('img',{name:'Difficulty: Average, estimated'})).toBeVisible();
 expect(screen.getByText('Coordination, communication and health technology scenarios.')).toBeVisible();
 const practise=within(panel('Practise these'));
 expect(practise.getByText('Estimated')).toBeVisible();
 const buttons=practise.getAllByRole('button');
 expect(buttons.map(button=>button.getAttribute('aria-expanded'))).toEqual(['true','false','false','false']);
 expect(practise.getByText(interviewBrief.questions[0].prep)).toBeVisible();
 expect(practise.getByText(interviewBrief.questions[1].prep)).not.toBeVisible();
 fireEvent.click(buttons[1]);
 expect(practise.getByText(interviewBrief.questions[1].prep)).toBeVisible();
 expect(practise.getByText(interviewBrief.questions[0].prep)).not.toBeVisible();
 expect(buttons[1].closest('li')).toHaveClass('is-open');
 fireEvent.click(buttons[1]);
 expect(practise.getAllByRole('button').every(button=>button.getAttribute('aria-expanded')==='false')).toBe(true);
});

it('summarises candidate reports with cited chips, a situational example, tone and the raw list',async()=>{
 renderInterview();
 const reports=within(await screen.findByRole('region',{name:'What candidates reported'}));
 expect(reports.getByText('Asked about')).toBeVisible();
 expect(reports.getByText('Past projects')).toBeVisible();
 expect(reports.getByText('How would you handle a client unhappy with the developers?')).toBeVisible();
 expect(reports.getByRole('link',{name:'Source 5: Working experience and situational questions'})).toBeVisible();
 const toggle=reports.getByRole('button',{name:'Show all 4 reports'});
 expect(reports.getByText(/asked about themselves and past projects/)).not.toBeVisible();
 fireEvent.click(toggle);
 expect(reports.getByText(/asked about themselves and past projects/)).toBeVisible();
 expect(within(panel('Not found yet')).getAllByRole('listitem').map(li=>li.textContent)).toEqual(['Assessment centre','Offer timeline']);
 fireEvent.click(within(panel('Sources')).getByRole('button',{name:'Show all 6 sources'}));
 expect(within(panel('Sources')).getAllByRole('listitem')).toHaveLength(6);
});

it('marks individual questions when only some are estimated and refreshes only interview research',async()=>{
 interview={status:'ready',brief:{...structuredClone(interviewBrief),questions:[{...interviewBrief.questions[0],estimated:false},interviewBrief.questions[1]]}};
 renderInterview();
 const practise=within(await screen.findByRole('region',{name:'Practise these'}));
 const [first,second]=practise.getAllByRole('button');
 expect(within(first).queryByText('Estimated')).toBeNull();
 expect(within(second).getByText('Estimated')).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:'Refresh research'}));
 await waitFor(()=>expect(vi.mocked(careerApi).mock.calls.some(call=>call[2]?.method==='POST'&&call[0].endsWith('/opportunity-research'))).toBe(true));
 const post=vi.mocked(careerApi).mock.calls.find(call=>call[0].endsWith('/opportunity-research')&&call[2]?.method==='POST')!;
 expect(JSON.parse(post[2]!.body as string).category).toBe('interview_intelligence');
});
