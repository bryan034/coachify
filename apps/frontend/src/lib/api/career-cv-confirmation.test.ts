import {afterEach,expect,it,vi} from 'vitest';
import {confirmCvGoal,getCvGoalConfirmation} from './career-cv-confirmation';
const id='111111111111111111111111';
const value={goal_id:id,goal_version:2,selection_version:3,confirmed:false,context:null,reason:null};
const respond=(body:unknown)=>vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}})));
afterEach(()=>vi.unstubAllGlobals());
it('uses authenticated no-store requests and exact confirmation revisions',async()=>{
 respond(value);const signal=new AbortController().signal;await getCvGoalConfirmation('token',signal);
 expect(fetch).toHaveBeenCalledWith('/api/v1/career/goals/current/cv-confirmation',expect.objectContaining({cache:'no-store',headers:{Authorization:'Bearer token'},signal}));
 const body={expected_goal_id:id,expected_goal_version:2,expected_selection_version:3,mutation_id:'request'};respond(value);await confirmCvGoal(body,'token',signal);
 expect(fetch).toHaveBeenLastCalledWith('/api/v1/career/goals/current/cv-confirmation',expect.objectContaining({method:'POST',body:JSON.stringify(body)}));
});
it.each([{...value,confirmed:true},{...value,goal_version:null},{...value,confirmed:true,context:{id,version:1,selection_version:3,confirmed:true}},{...value,selection_version:-1}])('rejects malformed confirmation state instead of showing a saved confirmation',async body=>{
 respond(body);await expect(getCvGoalConfirmation('token',new AbortController().signal)).rejects.toThrow('incomplete confirmation');
});
