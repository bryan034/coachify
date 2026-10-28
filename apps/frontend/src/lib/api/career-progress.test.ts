import {afterEach,expect,it,vi} from 'vitest';
import {careerApi,CareerApiError,refreshWorkspace,type CareerWorkspace} from './career';
const previous:CareerWorkspace={session_id:'session',revision:1,kind:'jd',phase:'researching',current:{goal:{_id:'goal',version:1,role:'Analyst',field:'Data',target_type:'specific_job',company:null,location:null,seniority_level:null,job_url:null,skills:[],interests:[],preferences:[],readiness:'pending',exploration_draft_id:null,exploration_draft_version:null},selection_version:1,dependent_results_need_review:false},research_id:null,research_version:null,coverage:[],error:null,retry_after:null,expires_at:null,exploration_id:null};
const progress={session_id:'session',goal_id:'goal',revision:1,selection_version:1,phase:'researching',research_id:null,activities:['checking_sources'],result_version:'v1',error:null,error_code:null,retry_after:null,limit_scope:null,provider:null};
afterEach(()=>vi.unstubAllGlobals());
it('polls progress without reloading unchanged goal content',async()=>{
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(progress)));vi.stubGlobal('fetch',fetch);
 const result=await refreshWorkspace(previous,'synthetic',new AbortController().signal);
 expect(fetch).toHaveBeenCalledTimes(1);expect(fetch.mock.calls[0][0]).toContain('/workspace/progress');
 expect(result.current.goal).toBe(previous.current.goal);expect(result.activities).toEqual(['checking_sources']);
});
it.each([{revision:2},{goal_id:'replacement'},{session_id:'replacement'},{research_id:'published'},{selection_version:2}])('reloads content when a referenced result changes: %o',async(change)=>{
 const full={...previous,phase:'ready'};
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({...progress,...change}))).mockResolvedValueOnce(new Response(JSON.stringify(full)));vi.stubGlobal('fetch',fetch);
 expect(await refreshWorkspace(previous,'synthetic',new AbortController().signal)).toEqual(full);
 expect(fetch).toHaveBeenCalledTimes(2);expect(fetch.mock.calls[1][0]).toMatch(/\/workspace$/);
});

it('preserves a failed operation ID on the client error without displaying diagnostics',async()=>{
 const operationId='a'.repeat(32);
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'The citations could not be verified.',code:'invalid_output',operation_id:operationId,diagnostic:{violations:[{field:'reply',issue:'missing_finding_citation'}]}}),{status:503})));
 const error=await careerApi('/workspace/operations/'+operationId,'synthetic').catch(error=>error);
 expect(error).toBeInstanceOf(CareerApiError);
 if(!(error instanceof CareerApiError))throw new Error('Expected a CareerApiError');
 expect(error.operationId).toBe(operationId);expect(error.code).toBe('invalid_output');
 expect(error.message).toBe('The citations could not be verified.');
 expect(error.message).not.toContain('missing_finding_citation');
});
