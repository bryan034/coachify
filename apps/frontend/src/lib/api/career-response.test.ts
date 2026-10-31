import {afterEach,expect,it,vi} from 'vitest';
import sample from '../../../tests/fixtures/career-workspace.json';
import {careerApi,CareerApiError,refreshWorkspace,type CareerWorkspace} from './career';
import {careerOperation} from './career-operation';
import {validCareerResponse} from './career-response';

afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
const workspace=()=>structuredClone(sample);

it('accepts the backend-validated canonical workspace and preserves unknown values',async()=>{
 const value=workspace();
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(value))));
 const result=await careerApi<CareerWorkspace>('/workspace','synthetic');
 expect(result).toEqual(value);
 expect(result.current.goal?.company).toBeNull();
 expect(result.current.goal?.skills[0].required_proficiency).toBeNull();
});

it.each(['skills','skill-priority','skill-origin','conditions','dates','goal','selection','phase','coverage','null'])('rejects malformed %s before rendering',async(defect)=>{
 const value=workspace();
 if(defect==='skills')Object.assign(value.current.goal,{skills:{name:'PRIVATE malformed'}});
 if(defect==='skill-priority')Object.assign(value.current.goal.skills[0],{priority:'PRIVATE malformed'});
 if(defect==='skill-origin')Object.assign(value.current.goal.skills[0],{origin:'PRIVATE malformed'});
 if(defect==='conditions')Object.assign(value.current.goal,{non_skill_requirements:[{description:'PRIVATE malformed'}]});
 if(defect==='dates')Object.assign(value.current.goal,{job_dates:[{kind:'PRIVATE malformed'}]});
 if(defect==='goal')Object.assign(value.current,{goal:{current:{goal:value.current.goal}}});
 if(defect==='selection')Object.assign(value.current,{selection_version:'1'});
 if(defect==='phase')Object.assign(value,{phase:'PRIVATE malformed'});
 if(defect==='coverage')Object.assign(value,{coverage:{}});
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(defect==='null'?null:value))));
 const error=await careerApi('/workspace','synthetic').catch(error=>error);
 expect(error).toBeInstanceOf(CareerApiError);if(!(error instanceof CareerApiError))throw new Error('Expected a CareerApiError');expect(error.code).toBe('invalid_response');
 expect(error.message).not.toContain('PRIVATE');
});

it('validates dates and AND/OR requirements without flattening their groups',()=>{
 const value=workspace();
 const requirements=[{requirement_id:'education',category:'qualification',description:'Degree or equivalent experience',
  priority:'required',evidence:'Degree or equivalent experience',group_id:'alternative-1',group_operator:'any',
  minimum_months:null,maximum_months:null,completion_status:'unspecified'}];
 const dates=[{kind:'application_deadline',text:'31 December 2026',evidence:'Apply by 31 December 2026.',date:'2026-12-31'}];
 Object.assign(value.current.goal,{non_skill_requirements:requirements,job_dates:dates});
 expect(validCareerResponse('/workspace',value)).toBe(true);
 expect(value.current.goal.non_skill_requirements).toEqual(requirements);
 expect(value.current.goal.job_dates).toEqual(dates);
});

it('rejects non-JSON successes and handles null error bodies safely',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response('<html>Gateway</html>'))
  .mockResolvedValueOnce(new Response('null',{status:503})));
 await expect(careerApi('/workspace','synthetic')).rejects.toMatchObject({code:'invalid_response'});
 await expect(careerApi('/workspace','synthetic')).rejects.toBeInstanceOf(CareerApiError);
});

it('validates a completed operation against its originating endpoint without replaying writes',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({operation_id:'a'.repeat(32),status:'running',result:null,retry_after:null})))
  .mockResolvedValueOnce(new Response(JSON.stringify({operation_id:'a'.repeat(32),status:'succeeded',result:{reply:{text:'PRIVATE malformed'}}})));
 vi.stubGlobal('fetch',fetch);vi.useFakeTimers();
 const failure=expect(careerOperation('/workspace/summary','synthetic',{method:'POST'},()=>{})).rejects.toMatchObject({code:'invalid_response'});
 await vi.runAllTimersAsync();await failure;
 expect(fetch).toHaveBeenCalledTimes(2);
 expect(fetch.mock.calls[0][1].method).toBe('POST');expect(fetch.mock.calls[1][1].method).toBeUndefined();
});

it('does not repeatedly reload an unchanged empty workspace',async()=>{
 const previous={...workspace(),session_id:null,revision:0,kind:null,phase:'empty',current:{goal:null,selection_version:0,dependent_results_need_review:false}} as CareerWorkspace;
 const progress={session_id:null,revision:0,goal_id:null,selection_version:0,phase:'empty',research_id:null,activities:[],result_version:null,error:null,retry_after:null};
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(progress)));vi.stubGlobal('fetch',fetch);
 expect((await refreshWorkspace(previous,'synthetic',new AbortController().signal)).current.goal).toBeNull();
 expect(fetch).toHaveBeenCalledTimes(1);
});

it('validates compact research polling and lazy evidence separately from reports',()=>{
 const path='/goals/goal/opportunity-research';
 expect(validCareerResponse(path+'/progress',{status:'partial',finished:true,result_version:'v1',categories:{interview_intelligence:{status:'failed',error_code:'unavailable'}}})).toBe(true);
 expect(validCareerResponse(path+'/progress',{finished:'true',result_version:'v1',categories:{}})).toBe(false);
 expect(validCareerResponse(path+'/findings/f1/evidence',{finding_id:'f1',quotes:['Synthetic quote'],sources:[]})).toBe(true);
 expect(validCareerResponse(path+'/findings/f1/evidence',{finding_id:'f1',quotes:{text:'PRIVATE malformed'},sources:[]})).toBe(false);
});
