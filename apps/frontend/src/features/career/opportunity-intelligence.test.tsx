import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {OpportunityIntelligence} from './opportunity-intelligence';
import {careerApi,type OpportunityView,type IntelligenceResult,type InterviewSuggestionsView,type RoleSummaryView} from '@/lib/api/career';
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));
const result: IntelligenceResult={status:'completed',findings:[{finding_id:'f0000000000000001',field:'compensation',value:'SGD 1500 per month',confidence:'low',evidence_type:'candidate_reported',source_ids:['s1'],quotes:['Interns report SGD 1500 per month'],scope:'exact',conflict_group:'salary',last_verified_at:'2026-10-26T00:00:00Z'}],missing_fields:['benefits'],warnings:['Conflicting reports are preserved separately.'],error_code:null,researched_at:'2026-10-26T00:00:00Z',expires_at:null,searches:1,model_calls:1,latency_ms:100,estimated_cost_usd:null};
let value:OpportunityView;let suggestions:InterviewSuggestionsView;let digest:RoleSummaryView;
beforeEach(()=>{vi.resetAllMocks();value={available:true,status:'partial',finished:true,job_id:'job',career_target_id:'goal',categories:{interview_intelligence:{...result,findings:[],missing_fields:[],status:'failed'},internship_insights:result,company_intelligence:{...result,status:'completed',findings:[],missing_fields:['tech_stack']}},research_id:'research',sources:[{source_id:'s1',url:'https://example.test/intern',title:'Intern report',platform:'other',evidence:'Interns report SGD 1500 per month',published_date:null,reported_date:null,role_match:'related',reliability:'anecdotal',report_group:null}],error_code:null};suggestions={status:'ready',suggestions:null};digest={status:'ready',summary:null};vi.mocked(careerApi).mockImplementation(async(path:string)=>(path.endsWith('/interview-prep')?suggestions:path.endsWith('/role-summary')?digest:value) as never);});
const finding=(id:string,field:string,text:string,extra={})=>({...result.findings[0],finding_id:id,field,value:text,conflict_group:null,...extra});
const interview=(findings:ReturnType<typeof finding>[])=>({...result,status:'completed' as const,findings,missing_fields:[],warnings:[]});

it('keeps role research visible when interviews fail, with claims, labels and citations',async()=>{
 render(<OpportunityIntelligence section="role" goalId="goal" version={1} selectionVersion={2}/>);
 const card=(await screen.findByRole('heading',{name:'Salary'})).closest('article')!;
 expect(within(card).getByText('SGD 1500 per month')).toBeVisible();
 expect(within(card).queryByText('low confidence')).toBeNull();
 expect(within(card).getByText('Conflicting reports')).toBeVisible();
 expect(within(card).getByRole('link',{name:'Intern report ↗'})).toHaveAttribute('href','https://example.test/intern');
 expect(screen.getByRole('note')).toHaveTextContent('may be inaccurate or out of date');
  const empty=within(screen.getByRole('region',{name:'Not filled yet'}));
  expect(empty.getByText('Benefits')).toBeVisible();
});
const roleCards=[{card_id:'work',title:'What you would work on',icon:'code',items:[{ref:'summary',text:'Build reporting for finance. Partner with analysts on weekly reviews.',urls:['https://example.test/job']}]}];
it('splits role text into bullets per card until the AI summary is ready',async()=>{
 render(<OpportunityIntelligence section="role" goalId="goal" version={1} selectionVersion={2} roleCards={roleCards}/>);
 const work=(await screen.findByRole('heading',{name:'What you would work on'})).closest('article')!;
 expect(within(work).getAllByRole('listitem').map(li=>li.textContent)).toEqual(['Build reporting for finance.','Partner with analysts on weekly reviews.']);
 expect(within(work).getByRole('link',{name:'example.test ↗'})).toHaveAttribute('href','https://example.test/job');
 expect(within(work).queryByText(/Summarised by AI/)).not.toBeInTheDocument();
});
it('shows the cited AI digest as bullets once research settles',async()=>{
 digest={status:'missing',summary:null};
 const ready:RoleSummaryView={status:'ready',summary:{goal_id:'goal',goal_version:1,research_id:'research',generated_at:'2026-11-11T00:00:00Z',
  cards:[{card_id:'work',bullets:[{text:'Finance reporting with weekly analyst reviews',refs:['summary']}]},{card_id:'compensation',headline:'SGD 1500 a month',bullets:[{text:'About **SGD 1500** a month (reported) <b>x</b>',refs:['f0000000000000001']}]}],
  generated:[{card_id:'benefits',headline:'Typically standard cover',bullets:['Not publicly reported; typically **medical cover** and leave']}]}};
 vi.mocked(careerApi).mockImplementation(async(path:string,_t,init)=>(path.endsWith('/role-summary')?init?.method==='POST'?ready:digest:value) as never);
 render(<OpportunityIntelligence section="role" goalId="goal" version={1} selectionVersion={2} roleCards={roleCards}/>);
 expect(await screen.findByText('Finance reporting with weekly analyst reviews')).toBeVisible();
 const salary=screen.getByRole('heading',{name:'Salary'}).closest('article')!;
 expect(within(salary).getByText('SGD 1500 a month')).toBeVisible();
 expect(within(salary).getByText('SGD 1500',{selector:'strong'})).toBeVisible();
 expect(salary.querySelector('b')).toBeNull();
 expect(within(salary).getByText(/a month \(reported\) <b>x<\/b>/)).toBeVisible();
 expect(within(salary).queryByText('low confidence')).toBeNull();
 expect(within(salary).getByText('Summarised by AI from the sources')).toBeVisible();
 expect(within(salary).getByRole('link',{name:'Intern report ↗'})).toBeVisible();
 expect(screen.queryByText('Build reporting for finance.')).not.toBeInTheDocument();
 const benefits=screen.getByRole('heading',{name:/Benefits/}).closest('article')!;
 expect(within(benefits).getByText('Typically standard cover')).toBeVisible();
 expect(within(benefits).getByText('medical cover',{selector:'strong'})).toBeVisible();
 expect(benefits).toHaveTextContent('Not publicly reported; typically medical cover and leave');
 expect(within(benefits).getByRole('img',{name:/not found in any sources/})).toBeInTheDocument();
 expect(within(salary).queryByRole('img',{name:/not found in any sources/})).not.toBeInTheDocument();
 expect(screen.getByText(/Fields marked with this icon were made by an AI model/)).toBeVisible();
});
it('groups interview findings by round, keeping process-wide facts as headlines',async()=>{
 value.categories.interview_intelligence=interview([
  finding('f0000000000000010','recruitment_stages','Three stages are reported.'),
  finding('f0000000000000011','round_format','Two timed coding problems.',{round_number:1,round_name:'Online assessment'}),
  finding('f0000000000000012','interview_questions','Reverse a linked list.',{round_number:1,round_name:'Online assessment'}),
  finding('f0000000000000013','preparation_topics','Revise OOP basics.',{round_number:2,round_name:'Technical interview'}),
 ]);
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 const headlines=await screen.findByRole('list',{name:'Interview headline facts'});
 expect(within(headlines).getByText('Three stages are reported.')).toBeVisible();
 expect(screen.getByText('Sources describe 2 rounds.')).toBeVisible();
 expect(screen.queryByRole('button',{name:/Online assessment/})).not.toBeInTheDocument();
 expect(screen.getByText('Reverse a linked list.')).toBeVisible();
 expect(screen.getByText('Revise OOP basics.')).toBeVisible();
 expect(screen.getAllByText('Not filled yet.')).toHaveLength(2);
 expect(within(headlines).getAllByText('Not filled yet')).toHaveLength(2);
 expect(screen.getAllByText('Three stages are reported.')).toHaveLength(1);
});
it('bolds key terms in interview findings and AI predictions without showing asterisks',async()=>{
 value.categories.interview_intelligence=interview([
  finding('f0000000000000010','recruitment_stages','**Online test**, then **panel**'),
  finding('f0000000000000011','round_format','**45-minute** video call',{round_number:1,round_name:'Online assessment'}),
  finding('f0000000000000012','interview_questions','Explain a **SQL join**.',{round_number:1,round_name:'Online assessment'}),
 ]);
 suggestions={status:'ready',suggestions:{goal_id:'goal',goal_version:1,research_id:'research',generated_at:'2026-11-11T00:00:00Z',
  gaps:[],items:[{round_number:1,field:'preparation_topics',value:'Practise **window functions**'}]}};
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 const question=await screen.findByText('SQL join');
 expect(question.tagName).toBe('STRONG');
 expect(screen.getByText('45-minute').tagName).toBe('STRONG');
 expect(screen.getByText('window functions').tagName).toBe('STRONG');
 const headlines=screen.getByRole('list',{name:'Interview headline facts'});
 expect(within(headlines).getByText('Online test, then panel')).toBeVisible();
 expect(document.body.textContent).not.toContain('**');
});
it('shows a single round when that is all the sources describe, and says when rounds are unknown',async()=>{
 value.categories.interview_intelligence=interview([finding('f0000000000000011','round_format','A single coding test.',{round_number:1,round_name:'Coding test'})]);
 const {unmount}=render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 expect(await screen.findByText(/Sources describe one round/)).toBeVisible();
 unmount();
 value.categories.interview_intelligence=interview([finding('f0000000000000010','recruitment_stages','Three stages are reported.')]);
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 expect(await screen.findByText('Not filled yet: sources don’t break this process down by round. Refresh research to look again.')).toBeVisible();
 expect(screen.getByText('Questions to expect')).toBeVisible();
});
it('fills empty interview slots with labelled AI predictions once research settles',async()=>{
 value.categories.interview_intelligence=interview([finding('f0000000000000012','interview_questions','Reverse a linked list.',{round_number:1,round_name:'Online assessment'})]);
 suggestions={status:'missing',suggestions:null};
 const generated:InterviewSuggestionsView={status:'ready',suggestions:{goal_id:'goal',goal_version:4,research_id:'research',generated_at:'2026-11-11T00:00:00Z',
  gaps:[{round_number:1,round_name:'Online assessment',field:'preparation_topics'}],items:[{round_number:1,field:'preparation_topics',value:'Practise timed array problems'}]}};
 vi.mocked(careerApi).mockImplementation(async(path:string,_t,init)=>(path.endsWith('/interview-prep')?init?.method==='POST'?generated:suggestions:value) as never);
 render(<OpportunityIntelligence goalId="goal" version={4} selectionVersion={5}/>);
 expect(await screen.findByText('Practise timed array problems')).toBeVisible();
 expect(screen.getByText(/Fields marked with this icon were made by an AI model/)).toBeVisible();
 expect(within(screen.getByText('Practise timed array problems').closest('div')!).getByRole('img',{name:/not found in any sources/})).toBeInTheDocument();
 expect(screen.getByText('Reverse a linked list.')).toBeVisible();
 const post=vi.mocked(careerApi).mock.calls.find(call=>call[0]==='/goals/goal/interview-prep'&&call[2]?.method==='POST')!;
 expect(JSON.parse(post[2]!.body as string)).toEqual({expected_version:4});
});
it('does not generate suggestions while research is still running',async()=>{
 value={...value,finished:false,status:'running',categories:{interview_intelligence:{...result,status:'running',findings:[]}}};
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 await screen.findByText(/Researching…/);
 expect(vi.mocked(careerApi).mock.calls.some(call=>call[0].endsWith('/interview-prep'))).toBe(false);
});
it('refreshes interview research with owner version and idempotency key',async()=>{
 render(<OpportunityIntelligence goalId="goal" version={4} selectionVersion={5}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Refresh research'}));
 await waitFor(()=>expect(vi.mocked(careerApi).mock.calls.some(call=>call[0].endsWith('/opportunity-research')&&call[2]?.method==='POST')).toBe(true));
 const call=vi.mocked(careerApi).mock.calls.find(call=>call[0].endsWith('/opportunity-research')&&call[2]?.method==='POST')!;
 expect(JSON.parse(call[2]!.body as string)).toEqual({expected_version:4,expected_selection_version:5,refresh:true,category:'interview_intelligence'});
 expect((call[2]!.headers as Record<string,string>)['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/);
});
it('shows provider configuration and general-target states honestly',async()=>{
 value={...value,available:false,availability_issues:['brave_llm_context_required'],categories:{company_intelligence:{...result,status:'not_applicable',findings:[],warnings:[]}}};vi.mocked(careerApi).mockResolvedValue(value);
 render(<OpportunityIntelligence section="role" goalId="goal" version={1} selectionVersion={2}/>);
 expect(await screen.findByText('The Brave connection needs LLM Context mode for opportunity research.')).toBeVisible();
 expect(screen.queryByText('The configured model is not connected to the Career service.')).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Refresh research'})).toBeDisabled();
 expect(screen.getByText('No company is specified, so employer-specific research was skipped.')).toBeVisible();
});
it.each(['no_relevant_sources','information_not_found','validation_failed','provider_failed'] as const)('replaces the %s banner with AI-made fills and the legend',async outcome=>{
 value.categories.interview_intelligence={...result,outcome,findings:[],warnings:[],status:outcome.endsWith('failed')?'failed':'completed'};
 suggestions={status:'ready',suggestions:{goal_id:'goal',goal_version:1,research_id:'research',generated_at:'2026-11-11T00:00:00Z',gaps:[{round_number:null,round_name:null,field:'difficulty'}],
  items:[{round_number:null,field:'difficulty',value:'Likely moderate: two technical rounds'},{round_number:null,field:'interview_questions',value:'Why this team?'}]}};
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 expect(await screen.findByText('Likely moderate: two technical rounds')).toBeVisible();
 expect(screen.getByText(/Fields marked with this icon were made by an AI model based on the context it was provided/)).toBeVisible();
 expect(screen.getAllByRole('img',{name:/not found in any sources/}).length).toBeGreaterThanOrEqual(3);
 expect(screen.queryByText(/Relevant sources were found|did not find sources|could not be verified|could not complete the request|Part of this research could not finish/)).not.toBeInTheDocument();
});
