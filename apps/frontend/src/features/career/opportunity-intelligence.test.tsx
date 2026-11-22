import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {OpportunityIntelligence} from './opportunity-intelligence';
import {careerApi,type OpportunityView} from '@/lib/api/career';
import {roleGoal,roleResearch,roleResearchSources} from '../../../tests/fixtures/role-research';
import {interviewResearch,interviewResearchSources} from '../../../tests/fixtures/interview-research';
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));

const base={status:'completed' as const,findings:[],missing_fields:[],warnings:[],error_code:null,researched_at:'2026-11-21T08:00:00Z',expires_at:null,searches:1,model_calls:1,latency_ms:100,estimated_cost_usd:null};
let research:OpportunityView;
const scrolled=vi.fn();
function mockApi(overrides:{fail?:boolean}={}){
 vi.mocked(careerApi).mockImplementation(async(path:string,_token,init)=>{
  if(path.endsWith('/progress'))return {result_version:'v1',finished:true} as never;
  if(path.includes('/v2/')||path.endsWith('/role-summary')||path.endsWith('/interview-prep'))throw new Error('No summary should be requested.');
  if(overrides.fail)throw new Error('unavailable');
  return research as never;
 });
}
beforeEach(()=>{
 vi.resetAllMocks();
 Element.prototype.scrollIntoView=scrolled;
 research={available:true,status:'completed',finished:true,job_id:'job',career_target_id:'goal',research_id:'research',error_code:null,
  sources:structuredClone([...interviewResearchSources,...roleResearchSources]),categories:{interview_intelligence:structuredClone(interviewResearch),...structuredClone(roleResearch)}};
 mockApi();
});
const renderRole=()=>render(<OpportunityIntelligence section="role" goalId="goal" goal={roleGoal}/>);
const renderInterview=()=>render(<OpportunityIntelligence section="interview" goalId="goal"/>);
const panel=(name:string)=>screen.getByRole('region',{name});
const roundCard=(number:number,name:string)=>within(panel(`Round ${number}: ${name}`));

it('displays all role finding values directly without requesting a summary',async()=>{
 renderRole();
 const topics=await screen.findByRole('region',{name:'What it is like'});
 const pay=panel('Pay and what comes after');
 for(const [category,result] of Object.entries(roleResearch)){
  expect(result!.findings.length).toBeGreaterThan(0);
  for(const finding of result!.findings)expect(category==='internship_insights'&&finding.field!=='compensation'||category==='company_intelligence'?topics:pay).toHaveTextContent(finding.value.replace(/\*\*/g,''));
 }
 expect(screen.getByRole('note')).toHaveTextContent('Researched 21 Nov 2026 from 7 public sources.');
 expect(screen.queryByRole('alert')).toBeNull();
 expect(vi.mocked(careerApi).mock.calls.every(call=>call[0].includes('/opportunity-research')&&call[2]?.method!=='POST')).toBe(true);
});

it('keeps the saved eligibility and duties verbatim alongside role findings',async()=>{
 renderRole();
 expect(await screen.findByText(roleGoal.requirements[0])).toBeVisible();
 const duties=within(panel('What you would do'));
 expect(duties.getByText(roleGoal.duties[0])).toBeVisible();
 expect(duties.getAllByRole('listitem')).toHaveLength(4);
 const more=duties.getByRole('button',{name:'Show 2 more'});
 expect(more).toHaveAttribute('aria-expanded','false');
 fireEvent.click(more);
 expect(duties.getAllByRole('listitem')).toHaveLength(6);
 expect(duties.getByRole('button',{name:'Show fewer'})).toHaveAttribute('aria-expanded','true');
});

it('preserves complete reports, bold terms, conflicts, related context and limited evidence',async()=>{
 renderRole();
 const topics=within(await screen.findByRole('region',{name:'What it is like'}));
 expect(topics.getByText(roleResearch.internship_insights!.findings[2].value)).toBeVisible();
 expect(topics.getAllByText('Conflicting reports')).toHaveLength(2);
 expect(topics.getByText('paid leave').tagName).toBe('STRONG');
 expect(topics.getByText('Estimated')).toBeVisible();
 expect(within(panel('Pay and what comes after')).getByText('Related role · Limited evidence')).toBeVisible();
});

it('numbers only role sources in reading order and resolves every citation',async()=>{
 research.sources=[...research.sources!].reverse();
 renderRole();
 await screen.findByRole('region',{name:'Sources'});
 const sources=within(panel('Sources'));
 expect(sources.getAllByRole('listitem')).toHaveLength(5);
 fireEvent.click(sources.getByRole('button',{name:'Show all 7 sources'}));
 expect(sources.getAllByRole('listitem').map(li=>li.textContent)).toEqual(roleResearchSources.map((source,index)=>`${index+1}${source.title} (opens in a new tab)example.test`));
 const chips=[...document.querySelectorAll<HTMLAnchorElement>('a.brief-cite')];
 expect(chips).toHaveLength(16);
 for(const chip of chips){
  const n=Number(chip.textContent);
  expect(chip.getAttribute('href')).toBe(`#role-src-${n}`);
  expect(chip).toHaveAccessibleName(`Source ${n}: ${roleResearchSources[n-1].title}`);
  expect(document.getElementById(`role-src-${n}`)).toHaveTextContent(roleResearchSources[n-1].title!);
 }
 fireEvent.click(sources.getByRole('button',{name:'Show fewer sources'}));
 expect(sources.getAllByRole('listitem')).toHaveLength(5);
});

it('reveals hidden role sources, scrolls to them and moves keyboard focus',async()=>{
 renderRole();
 const pay=within(await screen.findByRole('region',{name:'Pay and what comes after'}));
 fireEvent.click(pay.getAllByRole('link',{name:'Source 7: Role report 7'})[0]);
 const row=document.getElementById('role-src-7')!;
 await waitFor(()=>expect(row).toHaveClass('is-flash'));
 expect(scrolled).toHaveBeenCalled();
 expect(within(row).getByRole('link')).toHaveFocus();
});

it('hides missing role findings and names each absent topic without inventing values',async()=>{
 for(const key of ['career_progression','conversion_outcomes'] as const)research.categories[key]!.findings=[];
 research.categories.internship_insights!.findings=research.categories.internship_insights!.findings.filter(finding=>!['benefits','compensation'].includes(finding.field));
 renderRole();
 await screen.findByRole('region',{name:'What it is like'});
 expect(screen.queryByRole('region',{name:'Pay and what comes after'})).toBeNull();
 const gaps=within(panel('Not found yet'));
 expect(gaps.getByText('Benefits')).toBeVisible();
 expect(gaps.getByText('Intern pay')).toBeVisible();
 expect(gaps.getByText('Conversion rate')).toBeVisible();
 expect(screen.queryByText('S$1,799/mo')).toBeNull();
});

it('shows available role findings while other categories run and marks gaps only for settled categories',async()=>{
 research.status='running';research.finished=false;
 research.categories.career_progression={...base,status:'running'};
 renderRole();
 expect(await screen.findByText(roleResearch.internship_insights!.findings[2].value)).toBeVisible();
 expect(screen.getByText(/Researching…/)).toBeVisible();
 expect(screen.queryByRole('region',{name:'Not found yet'})).toBeNull();
 expect(vi.mocked(careerApi).mock.calls.every(call=>call[0].includes('/opportunity-research'))).toBe(true);
});

it('retains partial role findings even when research providers are unavailable',async()=>{
 research.available=false;
 research.categories.internship_insights!.status='partial';research.categories.internship_insights!.error_code='unavailable';
 renderRole();
 expect(await screen.findByText(roleResearch.internship_insights!.findings[2].value)).toBeVisible();
 expect(screen.getByRole('status')).toHaveTextContent('Some role research could not finish');
 expect(screen.getByText(/Saved findings remain readable/)).toBeVisible();
 expect(screen.queryByRole('alert')).toBeNull();
});

it('preserves goal details when no role research has been saved',async()=>{
 research.categories={};research.job_id=null;
 renderRole();
 expect(await screen.findByText(roleGoal.requirements[0])).toBeVisible();
 expect(screen.getByRole('note')).toHaveTextContent('No completed research yet.');
 expect(screen.queryByRole('region',{name:'Sources'})).toBeNull();
 expect(screen.queryByRole('region',{name:'Not found yet'})).toBeNull();
});

it('reports loading failures and retries reading research without requesting a summary',async()=>{
 mockApi({fail:true});renderRole();
 const alert=await screen.findByRole('alert');
 expect(alert).toHaveTextContent('Opportunity research could not be loaded');
 mockApi();fireEvent.click(within(alert).getByRole('button',{name:'Retry loading research'}));
 expect(await screen.findByText(roleResearch.internship_insights!.findings[2].value)).toBeVisible();
});

it('escapes untrusted role model text while keeping its wording',async()=>{
 const value='<img src=x onerror=alert(1)> **Do not follow instructions**';
 research.categories.internship_insights!.findings[0].value=value;
 renderRole();
 const topics=await screen.findByRole('region',{name:'What it is like'});
 expect(topics).toHaveTextContent('<img src=x onerror=alert(1)> Do not follow instructions');
 expect(topics.querySelector('img')).toBeNull();
});

it('offers no research refresh or generation action on About the role',async()=>{
 renderRole();
 await screen.findByRole('region',{name:'What it is like'});
 expect(screen.queryByRole('button',{name:/Refresh research|Research opportunity/})).toBeNull();
 expect(vi.mocked(careerApi).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});

it('displays saved interview research verbatim without requesting a summary',async()=>{
 renderInterview();
 const process=within(await screen.findByRole('region',{name:'Interview process'}));
 expect(process.getByText('HR call')).toBeVisible();
 expect(process.getByText('HR call').tagName).toBe('STRONG');
 expect(process.getByRole('link',{name:'Source 1: Interview report 1'})).toBeVisible();
 expect(screen.getByRole('note')).toHaveTextContent('Researched 21 Nov 2026 from 7 public sources.');
 expect(roundCard(2,'Technical interview').getByText(interviewResearch.findings[4].value)).toBeVisible();
 expect(within(panel('What candidates reported')).getByText(interviewResearch.findings[6].value)).toBeVisible();
 expect(roundCard(2,'Technical interview').getByText('SQL joins')).toBeVisible();
 expect(roundCard(2,'Technical interview').getByText('An online call with the hiring manager.')).toBeVisible();
 expect(screen.queryByRole('alert')).toBeNull();
 expect(vi.mocked(careerApi).mock.calls.some(call=>call[0].includes('/v2/')||call[0].endsWith('/interview-prep'))).toBe(false);
 expect(vi.mocked(careerApi).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});

it('keeps interview citations in reading order and reveals hidden sources',async()=>{
 research.sources=[...interviewResearchSources].reverse();
 renderInterview();
 const reports=within(await screen.findByRole('region',{name:'What candidates reported'}));
 fireEvent.click(reports.getByRole('link',{name:'Source 7: Interview report 7'}));
 const row=document.getElementById('interview-src-7')!;
 await waitFor(()=>expect(row).toHaveClass('is-flash'));
 expect(within(row).getByRole('link')).toHaveFocus();
 expect(scrolled).toHaveBeenCalled();
 expect(within(panel('Sources')).getAllByRole('listitem').map(li=>li.textContent)).toEqual([0,1,3,2,4,5,6].map((source,index)=>`${index+1}${interviewResearchSources[source].title} (opens in a new tab)example.test`));
});

it('shows related context, limited evidence, conflicts and estimates without rewriting findings',async()=>{
 const result=research.categories.interview_intelligence!;
 result.findings[4]={...result.findings[4],scope:'related_role',confidence:'low',conflict_group:'question-reports',evidence_type:'inferred'};
 renderInterview();
 const questions=within(await screen.findByRole('region',{name:'Round 2: Technical interview'}));
 expect(questions.getByText('Related role · Limited evidence')).toBeVisible();
 expect(questions.getByText('Conflicting reports')).toBeVisible();
 expect(questions.getByText('Estimated')).toBeVisible();
 expect(questions.getByText(interviewResearch.findings[4].value)).toBeVisible();
});

it('shows empty interview topics as gaps and preserves available partial research',async()=>{
 const result=research.categories.interview_intelligence!;
 result.status='partial';result.error_code='unavailable';result.findings=result.findings.filter(finding=>finding.field==='interview_questions');
 renderInterview();
 expect(await screen.findByText(interviewResearch.findings[4].value)).toBeVisible();
 expect(screen.getByRole('status')).toHaveTextContent('Some interview research could not finish');
 expect(screen.queryByRole('region',{name:'How to prepare'})).toBeNull();
 expect(within(panel('Not found yet')).getByText('How to prepare')).toBeVisible();
 expect(screen.getByRole('note')).toHaveTextContent('1 public source.');
});

it('displays retained interview findings while research runs without requesting a summary',async()=>{
 research={...research,status:'running',finished:false};
 research.categories.interview_intelligence!.status='running';
 renderInterview();
 expect(await screen.findByText(interviewResearch.findings[4].value)).toBeVisible();
 expect(screen.getByText(/Researching…/)).toBeVisible();
 expect(vi.mocked(careerApi).mock.calls.some(call=>call[0].includes('/v2/'))).toBe(false);
});

it('offers no research refresh or generation action on Interview preparation',async()=>{
 renderInterview();
 await screen.findByRole('region',{name:'Round 2: Technical interview'});
 expect(screen.queryByRole('button',{name:/Refresh research|Research opportunity/})).toBeNull();
 expect(vi.mocked(careerApi).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});

it('groups every reported round into its own card with matching expectations and preparation',async()=>{
 renderInterview();
 const rounds=within(await screen.findByRole('region',{name:'Interview rounds'}));
 expect(rounds.getAllByRole('heading',{level:4}).map(heading=>heading.textContent)).toEqual(['HR call','Technical interview','Final interview']);
 const hr=roundCard(1,'HR call'),technical=roundCard(2,'Technical interview'),final=roundCard(3,'Final interview');
 for(const card of [hr,technical,final]){
  expect(card.getByRole('heading',{name:'What to expect'})).toBeVisible();
  expect(card.getByRole('heading',{name:'How to prepare'})).toBeVisible();
 }
 expect(hr.getByText(interviewResearch.findings[7].value)).toBeVisible();
 expect(hr.getByText(interviewResearch.findings[8].value)).toBeVisible();
 expect(hr.queryByText('SQL joins')).toBeNull();
 expect(technical.getByText('SQL joins')).toBeVisible();
 expect(technical.queryByText(interviewResearch.findings[8].value)).toBeNull();
 expect(final.getByText('Preparation guidance was not found for this round.')).toBeVisible();
 expect(vi.mocked(careerApi).mock.calls.every(call=>call[0].includes('/opportunity-research')&&call[2]?.method!=='POST')).toBe(true);
});

it('keeps unassigned findings separate and never invents missing rounds or round-specific advice',async()=>{
 const result=research.categories.interview_intelligence!;
 result.findings=result.findings.filter(finding=>finding.round_number!==1&&finding.round_number!==3);
 result.findings.push({...result.findings[0],finding_id:'f0000000000000011',field:'preparation_topics',value:'Review the role requirements before applying.',round_number:null,round_name:null});
 renderInterview();
 const rounds=within(await screen.findByRole('region',{name:'Interview rounds'}));
 expect(rounds.getAllByRole('heading',{level:4}).map(heading=>heading.textContent)).toEqual(['Technical interview']);
 expect(rounds.queryByText('Review the role requirements before applying.')).toBeNull();
 expect(within(panel('How to prepare')).getByText('Review the role requirements before applying.')).toBeVisible();
});

it('shows older research without round metadata as general findings without fabricating a process',async()=>{
 research.categories.interview_intelligence!.findings=research.categories.interview_intelligence!.findings.map(finding=>({...finding,round_number:null,round_name:null}));
 renderInterview();
 expect(await screen.findByRole('region',{name:'Questions reported'})).toHaveTextContent(interviewResearch.findings[4].value);
 expect(screen.queryByRole('region',{name:'Interview rounds'})).toBeNull();
 expect(within(panel('How to prepare')).getByText('SQL joins')).toBeVisible();
});

it('shows the round count and overview before all other interview content',async()=>{
 renderInterview();
 const count=await screen.findByRole('heading',{name:'3 reported interview rounds'});
 const container=document.getElementById('interview-preparation')!;
 expect([...container.querySelectorAll('h3')][0]).toBe(count);
 const overview=within(screen.getByRole('region',{name:'3 reported interview rounds'}));
 expect(overview.getAllByRole('link').map(link=>link.textContent)).toEqual(['1HR call','2Technical interview','3Final interview']);
 expect(overview.getByRole('link',{name:'Technical interview'})).toHaveAttribute('href','#interview-round-2-title');
 const boxes=overview.getAllByRole('listitem');
 expect(boxes.map(box=>within(box).getByRole('heading',{level:4}).textContent)).toEqual(['1HR call','2Technical interview','3Final interview']);
 expect(boxes[0].querySelector('p')).toHaveTextContent(interviewResearch.findings[7].value);
 expect(boxes[1].querySelector('p')).toHaveTextContent(interviewResearch.findings[2].value);
 expect(boxes[2].querySelector('p')).toHaveTextContent(interviewResearch.findings[9].value);
 const cards=screen.getByRole('region',{name:'Interview rounds'});
 expect(cards.querySelectorAll(':scope > .brief-round')).toHaveLength(3);
});

it('counts only reported rounds without filling gaps in their numbering',async()=>{
 const result=research.categories.interview_intelligence!;
 result.findings=result.findings.filter(finding=>finding.round_number!==1&&finding.round_number!==3);
 renderInterview();
 expect(await screen.findByRole('heading',{name:'1 reported interview round'})).toBeVisible();
 expect(screen.queryByRole('region',{name:'Round 1: HR call'})).toBeNull();
});

it('keeps a round description unknown when only questions or preparation are saved',async()=>{
 const result=research.categories.interview_intelligence!;
 result.findings=result.findings.filter(finding=>finding.round_number===2&&['interview_questions','preparation_topics'].includes(finding.field));
 renderInterview();
 const overview=within(await screen.findByRole('region',{name:'1 reported interview round'}));
 expect(overview.getByRole('heading',{level:4})).toHaveTextContent('Technical interview');
 expect(overview.getByText('A description of this round was not found in the sources.')).toBeVisible();
 expect(overview.queryByText(interviewResearch.findings[4].value)).toBeNull();
 expect(vi.mocked(careerApi).mock.calls.every(call=>call[0].includes('/opportunity-research')&&call[2]?.method!=='POST')).toBe(true);
});

it('uses saved short round titles in overview and card headings without rewriting descriptions',async()=>{
 const original='Technical interview with the hiring manager';
 for(const finding of research.categories.interview_intelligence!.findings)if(finding.round_number===2)finding.round_name=original;
 research.round_titles={'2':'Technical interview'};
 renderInterview();
 const overview=within(await screen.findByRole('region',{name:'3 reported interview rounds'}));
 expect(overview.getByRole('heading',{name:'Technical interview'})).toBeVisible();
 expect(roundCard(2,'Technical interview').getByRole('heading',{name:'Technical interview'})).toBeVisible();
 expect(overview.getByText(interviewResearch.findings[2].value)).toBeVisible();
 for(const title of document.querySelectorAll('.brief-round-overview h4,.brief-round h4'))expect(title.textContent!.replace(/^\d+/, '').trim().split(/\s+/).length).toBeLessThanOrEqual(3);
 expect(research.categories.interview_intelligence!.findings.find(finding=>finding.round_number===2)!.round_name).toBe(original);
 expect(vi.mocked(careerApi).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});
