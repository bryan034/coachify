import {afterEach,expect,it,vi} from 'vitest';
import {careerApi,importCareer} from './career';
import {cvApi} from './cv';
import {roadmapApi} from './roadmap';
import {PREMIUM_REQUIRED_EVENT} from './premium';
import {errorText} from '@/lib/errors';
afterEach(()=>vi.unstubAllGlobals());
function respond(value:unknown,status:number){vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}})));}
function listen(){const heard=vi.fn();window.addEventListener(PREMIUM_REQUIRED_EVENT,heard);return {heard,stop:()=>window.removeEventListener(PREMIUM_REQUIRED_EVENT,heard)};}
const premium={detail:'This is part of elo Premium.',code:'premium_required'};
const calls:[string,()=>Promise<unknown>][]=[
 ['career',()=>careerApi('/explorations','token',{method:'POST',body:'{}'})],
 ['career',()=>importCareer('url',JSON.stringify({url:'https://example.test/job'}),'token',new AbortController().signal)],
 ['cv',()=>cvApi.upload(new FormData(),'token',new AbortController().signal)],
 ['roadmap',()=>roadmapApi('/planner/weeks/generate','token',{week_start:'2030-01-21'})],
 ['roadmap_outline',()=>roadmapApi('/planner/outlines/generate','token',{auto_accept:true})],
];
it.each(calls)('announces a %s premium limit and still rejects with its status and code',async(feature,call)=>{
 respond(premium,402);const {heard,stop}=listen();
 const failure=await call().catch(error=>error);
 expect(failure).toMatchObject({status:402,code:'premium_required'});
 expect(errorText(failure,'Generic failure')).toBe('');
 expect(heard).toHaveBeenCalledTimes(1);expect(heard.mock.calls[0][0].detail).toEqual({feature});stop();
});
it.each(calls)('does not announce premium for other %s failures',async(_feature,call)=>{
 const {heard,stop}=listen();
 respond({detail:'Payment details are not used here.'},402);await call().catch(()=>null);
 respond({detail:'Conflict',code:'premium_required'},409);await call().catch(()=>null);
 expect(heard).not.toHaveBeenCalled();stop();
});
