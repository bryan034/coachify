import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {OpportunityIntelligence} from './opportunity-intelligence';
import {careerApi,type OpportunityView,type IntelligenceResult} from '@/lib/api/career';
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));
const result: IntelligenceResult={status:'completed',findings:[{finding_id:'f0000000000000001',field:'compensation',value:'SGD 1500 per month',confidence:'low',evidence_type:'candidate_reported',source_ids:['s1'],quotes:['Interns report SGD 1500 per month'],scope:'exact',conflict_group:'salary',last_verified_at:'2026-10-26T00:00:00Z'}],missing_fields:['benefits'],warnings:['Conflicting reports are preserved separately.'],error_code:null,researched_at:'2026-10-26T00:00:00Z',expires_at:null,searches:1,model_calls:1,latency_ms:100,estimated_cost_usd:null};
let value:OpportunityView;
beforeEach(()=>{vi.resetAllMocks();value={available:true,status:'partial',finished:true,job_id:'job',career_target_id:'goal',categories:{interview_intelligence:{...result,findings:[],missing_fields:[],status:'failed'},internship_insights:result,company_intelligence:{...result,status:'completed',findings:[],missing_fields:['tech_stack']}},research_id:'research',sources:[{source_id:'s1',url:'https://example.test/intern',title:'Intern report',platform:'other',evidence:'Interns report SGD 1500 per month',published_date:null,reported_date:null,role_match:'related',reliability:'anecdotal',report_group:null}],error_code:null};vi.mocked(careerApi).mockResolvedValue(value);});
const finding=(id:string,field:string,text:string,extra={})=>({...result.findings[0],finding_id:id,field,value:text,conflict_group:null,...extra});
const interview=(findings:ReturnType<typeof finding>[])=>({...result,status:'completed' as const,findings,missing_fields:[],warnings:[]});

it('keeps role research visible when interviews fail, with claims, labels and citations',async()=>{
 render(<OpportunityIntelligence section="role" goalId="goal" version={1} selectionVersion={2}/>);
 const card=(await screen.findByRole('heading',{name:'Salary'})).closest('article')!;
 expect(within(card).getByText('SGD 1500 per month')).toBeVisible();
 expect(within(card).getByText('low confidence')).toBeVisible();
 expect(within(card).getByText('Conflicting reports')).toBeVisible();
 expect(within(card).getByRole('link',{name:'Intern report ↗'})).toHaveAttribute('href','https://example.test/intern');
 expect(screen.getByRole('note')).toHaveTextContent('may be inaccurate or out of date');
 expect(screen.getByText('Fields elo couldn’t find are hidden.')).toBeVisible();
 expect(screen.queryByRole('heading',{name:'Benefits'})).not.toBeInTheDocument();
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
 expect(screen.getByText('Sources describe 2 rounds. Open a round to see what to expect and how to prepare.')).toBeVisible();
 const first=screen.getByRole('button',{name:/Online assessment/});
 expect(first).toHaveAttribute('aria-expanded','true');
 expect(screen.getByText('Reverse a linked list.')).toBeVisible();
 expect(screen.getByText('No reported preparation advice for this round.')).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:/Technical interview/}));
 expect(screen.getByText('Revise OOP basics.')).toBeVisible();
 expect(screen.queryByText('Reverse a linked list.')).not.toBeInTheDocument();
 expect(screen.getAllByText('Three stages are reported.')).toHaveLength(1);
});
it('shows a single round when that is all the sources describe, and says when rounds are unknown',async()=>{
 value.categories.interview_intelligence=interview([finding('f0000000000000011','round_format','A single coding test.',{round_number:1,round_name:'Coding test'})]);
 const {unmount}=render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 expect(await screen.findByText(/Sources describe one round/)).toBeVisible();
 unmount();
 value.categories.interview_intelligence=interview([finding('f0000000000000010','recruitment_stages','Three stages are reported.')]);
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 expect(await screen.findByText('Sources don’t break this process down by round yet. Refresh research to look again.')).toBeVisible();
});
it('refreshes interview research with owner version and idempotency key',async()=>{
 render(<OpportunityIntelligence goalId="goal" version={4} selectionVersion={5}/>);
 fireEvent.click(await screen.findByRole('button',{name:'Refresh research'}));
 await waitFor(()=>expect(vi.mocked(careerApi).mock.calls.some(call=>call[2]?.method==='POST')).toBe(true));
 const call=vi.mocked(careerApi).mock.calls.find(call=>call[2]?.method==='POST')!;
 expect(JSON.parse(call[2]!.body as string)).toEqual({expected_version:4,expected_selection_version:5,refresh:true,category:'interview_intelligence'});
 expect((call[2]!.headers as Record<string,string>)['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/);
});
it('shows provider configuration and general-target states honestly',async()=>{
 value={...value,available:false,availability_issues:['brave_llm_context_required'],categories:{company_intelligence:{...result,status:'not_applicable',findings:[],warnings:[]}}};vi.mocked(careerApi).mockResolvedValue(value);
 render(<OpportunityIntelligence section="role" goalId="goal" version={1} selectionVersion={2}/>);
 expect(await screen.findByText('The Brave connection needs LLM Context mode for opportunity research.')).toBeVisible();
 expect(screen.queryByText('Gemini is not connected to the Career service.')).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Refresh research'})).toBeDisabled();
 expect(screen.getByText('No company is specified, so employer-specific research was skipped.')).toBeVisible();
});
it.each([
 ['no_relevant_sources','The searches did not find sources relevant to this category.'],
 ['information_not_found','Relevant sources were found, but they did not provide supported information for this category.'],
 ['validation_failed','Proposed findings could not be verified. Available findings are preserved; refresh this section to retry.'],
 ['provider_failed','A research provider could not complete the request. Available findings are preserved; refresh this section to retry.'],
] as const)('explains the %s outcome without a generic no-results message',async(outcome,message)=>{
 value.categories.interview_intelligence={...result,outcome,findings:[],warnings:[],status:outcome.endsWith('failed')?'failed':'completed'};
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 await screen.findByText(message);
 expect(screen.queryByText(/Part of this research could not finish/)).not.toBeInTheDocument();
});
