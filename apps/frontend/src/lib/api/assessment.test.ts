import {afterEach,expect,it,vi} from 'vitest';
import {currentSkillMatches,skillChat,skillChatHistory} from './assessment';
const signal=new AbortController().signal;
const serve=(body:unknown,status=200)=>vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(body),{status})));
afterEach(()=>vi.unstubAllGlobals());
const outcome=(id:string,match_status:string)=>({ref:`job:${id}`,match_status});
it('maps a fresh comparison to goal skill ids without starting anything',async()=>{
 serve({stale:false,result:{groups:[],job_skill_gaps:[outcome('sql','supported'),outcome('aws','confirmed_shortfall'),{ref:'condition:visa',match_status:'uncertain'}]}});
 expect(await currentSkillMatches('token',signal)).toEqual({sql:'supported',aws:'confirmed_shortfall'});
 const [url,init]=vi.mocked(fetch).mock.calls[0];
 expect(url).toContain('/assessments/current');expect(init?.method).toBeUndefined();
});
it('marks an unheld alternative as covered when its group is satisfied',async()=>{
 serve({stale:false,result:{groups:[{operator:'any',match_status:'supported',requirement_refs:['job:sql','job:nosql']}],job_skill_gaps:[outcome('sql','supported'),outcome('nosql','uncertain')]}});
 expect(await currentSkillMatches('token',signal)).toEqual({sql:'supported',nosql:'covered'});
});
it.each([
 ['a stale comparison',{stale:true,result:{groups:[],job_skill_gaps:[outcome('sql','supported')]}},200],
 ['no comparison yet',{stale:false,result:null},200],
 ['a failed request',{detail:'Unavailable'},503],
])('shows nothing for %s',async(_name,body,status)=>{
 serve(body,status);expect(await currentSkillMatches('token',signal)).toBeNull();
});
it('ignores unknown statuses and network failures',async()=>{
 serve({stale:false,result:{job_skill_gaps:[outcome('sql','mastered')]}});expect(await currentSkillMatches('token',signal)).toEqual({});
 vi.stubGlobal('fetch',vi.fn(async()=>{throw new Error('offline');}));expect(await currentSkillMatches('token',signal)).toBeNull();
});
it('keeps the service reason when a request fails',async()=>{
 serve({detail:'Model usage could not be reserved. Retry when the service is available.',code:'model_budget_unavailable'},503);
 await expect(skillChat('token',{name:'SQL',canonical_skill_id:null,message:'I have used this before'}))
  .rejects.toMatchObject({message:'Model usage could not be reserved. Retry when the service is available.',code:'model_budget_unavailable',status:503});
 serve({},500);
 await expect(skillChat('token',{name:'SQL',canonical_skill_id:null,message:'Why?'})).rejects.toThrow('Your comparison could not be completed. Reload and try again.');
});
it('reads one skill\'s saved conversation by its name and registry identity',async()=>{
 serve({turns:[]});
 await skillChatHistory('token',{name:'SQL & NoSQL',canonical_skill_id:'database.sql'});
 await skillChatHistory('token',{name:'Excel',canonical_skill_id:null});
 const [[first,init],[second]]=vi.mocked(fetch).mock.calls;
 expect(first).toBe('/api/v1/assessments/skills/chat?name=SQL+%26+NoSQL&canonical_skill_id=database.sql');
 expect(second).toBe('/api/v1/assessments/skills/chat?name=Excel');expect(init?.method).toBe('GET');
});
