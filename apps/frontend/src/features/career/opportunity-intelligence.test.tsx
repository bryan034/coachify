import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {beforeEach,expect,it,vi} from 'vitest';
import {OpportunityIntelligence} from './opportunity-intelligence';
import {careerApi,type OpportunityView,type IntelligenceResult} from '@/lib/api/career';
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic-token'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));
const result: IntelligenceResult={status:'completed',findings:[{finding_id:'f0000000000000001',field:'compensation',value:'SGD 1500 per month',confidence:'low',evidence_type:'candidate_reported',source_ids:['s1'],quotes:['Interns report SGD 1500 per month'],scope:'exact',conflict_group:'salary',last_verified_at:'2026-10-26T00:00:00Z'}],missing_fields:['benefits'],warnings:['Conflicting reports are preserved separately.'],error_code:null,researched_at:'2026-10-26T00:00:00Z',expires_at:null,searches:1,model_calls:1,latency_ms:100,estimated_cost_usd:null};
let value:OpportunityView;
beforeEach(()=>{vi.resetAllMocks();value={available:true,status:'partial',finished:true,job_id:'job',career_target_id:'goal',categories:{interview_intelligence:{...result,findings:[],missing_fields:[],status:'failed'},internship_insights:result,company_intelligence:{...result,status:'completed',findings:[],missing_fields:['tech_stack']}},research:null,sources:[{source_id:'s1',url:'https://example.test/intern',title:'Intern report',platform:'other',evidence:'Interns report SGD 1500 per month',published_date:null,reported_date:null,role_match:'related',reliability:'anecdotal',report_group:null}],error_code:null};vi.mocked(careerApi).mockResolvedValue(value);});
it('keeps successful categories visible when interviews fail, with claims, dates and citations',async()=>{
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 await screen.findByText('This category could not finish. Other results are preserved; refresh this section to retry.');
 const details=screen.getByText('Internship Insights').closest('details')!;fireEvent.click(within(details).getByText('Internship Insights'));
 expect(within(details).getByText('SGD 1500 per month')).toBeVisible();expect(within(details).getByText('low confidence')).toBeVisible();
 fireEvent.click(within(details).getByText('Evidence and sources'));
 expect(within(details).getByRole('link',{name:'Intern report ↗'})).toHaveAttribute('href','https://example.test/intern');
 expect(within(details).getByText(/Published: Unknown/)).toBeVisible();
 expect(within(details).getByText('Conflicting reports')).toBeVisible();
});
it('refreshes only the requested category with owner version and idempotency key',async()=>{
 render(<OpportunityIntelligence goalId="goal" version={4} selectionVersion={5}/>);
 await screen.findByText('Internship Insights');const details=screen.getByText('Company Intelligence').closest('details')!;fireEvent.click(within(details).getByText('Company Intelligence'));
 fireEvent.click(within(details).getByRole('button',{name:'Refresh this section'}));
 await waitFor(()=>expect(vi.mocked(careerApi).mock.calls.some(call=>call[2]?.method==='POST')).toBe(true));
 const call=vi.mocked(careerApi).mock.calls.find(call=>call[2]?.method==='POST')!;
 expect(JSON.parse(call[2]!.body as string)).toEqual({expected_version:4,expected_selection_version:5,refresh:true,category:'company_intelligence'});
 expect((call[2]!.headers as Record<string,string>)['Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/);
});
it('shows provider configuration and general-target states honestly',async()=>{
 value={...value,available:false,availability_issues:['brave_llm_context_required'],categories:{company_intelligence:{...result,status:'not_applicable',findings:[],warnings:[]}}};vi.mocked(careerApi).mockResolvedValue(value);
 render(<OpportunityIntelligence goalId="goal" version={1} selectionVersion={2}/>);
 expect(await screen.findByText('The Brave connection needs LLM Context mode for opportunity research.')).toBeVisible();
 expect(screen.queryByText('Gemini is not connected to the Career service.')).not.toBeInTheDocument();
 expect(screen.getByRole('button',{name:'Refresh research'})).toBeDisabled();
 const details=screen.getByText('Company Intelligence').closest('details')!;fireEvent.click(within(details).getByText('Company Intelligence'));
 expect(within(details).getByText('No company is specified for employer-specific research.')).toBeVisible();
});
