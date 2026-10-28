import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {beforeEach,expect,test,vi} from 'vitest';
import {CareerTools,InterviewResearch} from './career-tools';
import {careerApi,type CurrentGoal,type ResearchView} from '@/lib/api/career';
const push=vi.fn();
vi.mock('next/navigation',()=>({useRouter:()=>({push})}));
vi.mock('@/features/profile/profile-provider',()=>({useProfile:()=>({token:'synthetic'})}));
vi.mock('@/lib/api/career',()=>({careerApi:vi.fn()}));
const current:CurrentGoal={selection_version:1,dependent_results_need_review:false,goal:{_id:'000000000000000000000071',version:1,target_type:'career_exploration',role:'Data Analyst',field:'Data',company:null,location:null,seniority_level:null,job_url:null,skills:[],interests:[],preferences:[],readiness:'pending',exploration_draft_id:null,exploration_draft_version:null}};
const research:ResearchView={status:'succeeded',reused:true,stale:true,historical:false,general:true,context:{role:'Data Analyst',field:'Data',company:null,location:null,seniority_level:null},note:'Research is guidance, not a guaranteed question.',history:['000000000000000000000081'],research:{_id:'000000000000000000000081',version:2,last_researched_at:'2026-01-01T00:00:00Z',research_status:'succeeded',skills:[{skill_id:null,name:'SQL',category:'Technical',interview_stage:null,assessment_type:null,difficulty:'unknown',question_patterns:['Explain joins'],independent_report_count:0,source_ids:['s1']}],sources:[{source_id:'s1',platform:'reddit',url:'https://example.test/report',title:'Reported interview',evidence:'Interview included SQL',published_date:null,reported_date:null,role_match:'related',reliability:'anecdotal',report_group:null}]}};
beforeEach(()=>{vi.resetAllMocks();window.history.replaceState(null,'','/career-goal');});

test('exposes sourced topics, uncertainty and historical evidence without starting research',async()=>{
 vi.mocked(careerApi).mockResolvedValue(research);
 render(<InterviewResearch current={current} token="synthetic"/>);
 expect(await screen.findByRole('heading',{name:'SQL'})).toBeVisible();
 expect(screen.getByRole('status')).toHaveTextContent('Reused saved research');
 expect(screen.getByRole('status')).toHaveTextContent('Stale');
 expect(screen.getByText(/Stage: Unknown/)).toBeVisible();
 expect(screen.getByText(/independence not verified/)).toBeVisible();
 fireEvent.click(screen.getByText(/Individual\/anecdotal report/));
 expect(screen.getByRole('link',{name:'Reported interview'})).toHaveAttribute('href','https://example.test/report');
 expect(screen.getByText(/Location, seniority or role context may differ/)).toBeVisible();
 expect(careerApi).toHaveBeenCalledTimes(1);
 expect(vi.mocked(careerApi).mock.calls[0][2]?.method).toBeUndefined();
});

test('generation uses exact goal versions and opens the shared saved review',async()=>{
 vi.mocked(careerApi).mockResolvedValue({current:{goal:{_id:'000000000000000000000082'}}});
 render(<CareerTools current={current}/>);
 fireEvent.click(screen.getByRole('button',{name:'Generate role skills'}));
 await waitFor(()=>expect(push).toHaveBeenCalledWith('/career-goal/chat?source=jd&review=000000000000000000000082'));
 const call=vi.mocked(careerApi).mock.calls[0];
 expect(call[0]).toBe('/goals/000000000000000000000071/guidance');
 expect(JSON.parse(call[2]?.body as string)).toEqual({expected_version:1,expected_selection_version:1});
 expect(call[2]?.headers).toHaveProperty('Idempotency-Key');
});

test('a failed research refresh preserves saved topics and sends no user source links',async()=>{
 vi.mocked(careerApi).mockImplementation(async(_path,_token,options)=>{
  if(options?.method==='POST')throw new Error('Public source unavailable');
  return research as never;
 });
 render(<InterviewResearch current={current} token="synthetic"/>);
 await screen.findByRole('heading',{name:'SQL'});
 fireEvent.click(screen.getByRole('button',{name:'Refresh research'}));
 expect(await screen.findByRole('alert')).toHaveTextContent('Previous successful research is retained');
 expect(screen.getByRole('heading',{name:'SQL'})).toBeVisible();
 const post=vi.mocked(careerApi).mock.calls.find(call=>call[2]?.method==='POST');
 expect(JSON.parse(post![2]!.body as string)).not.toHaveProperty('source_urls');
 expect(screen.queryByRole('textbox')).toBeNull();
});

test('valid no-findings is different from missing research',async()=>{
 vi.mocked(careerApi).mockResolvedValue({...research,status:'no_findings',research:{...research.research!,skills:[],research_status:'no_findings'}});
 render(<InterviewResearch current={current} token="synthetic"/>);
 expect(await screen.findByText(/No supported interview topics were found/)).toBeVisible();
 expect(screen.getByText(/does not mean there are no interview expectations/)).toBeVisible();
});

test('a direct historical link reads its exact version and never requests research',async()=>{
 window.history.replaceState(null,'','/career-goal?goal=000000000000000000000070&research=000000000000000000000081');
 vi.mocked(careerApi).mockResolvedValue({...research,historical:true});
 render(<InterviewResearch current={current} token="synthetic"/>);
 await screen.findByRole('heading',{name:'SQL'});
 expect(vi.mocked(careerApi).mock.calls[0][0]).toBe('/goals/000000000000000000000070/interview-research?research_id=000000000000000000000081');
 expect(screen.queryByRole('button',{name:'Refresh research'})).toBeNull();
});
