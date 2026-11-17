import {afterEach,expect,it,vi} from 'vitest';
import {roadmapApi} from './roadmap';
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});
it('turns a stalled workspace read into a retryable error',async()=>{
 vi.useFakeTimers();
 vi.stubGlobal('fetch',vi.fn((_url,init)=>new Promise((_resolve,reject)=>init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))));
 const result=roadmapApi('/workspace?time_zone=Asia%2FSingapore','synthetic');
 const check=expect(result).rejects.toMatchObject({code:'workspace_timeout',status:504,message:expect.stringContaining('Retry loading')});
 await vi.advanceTimersByTimeAsync(20000);await check;
});
it('keeps caller cancellation distinct from a loading timeout',async()=>{
 vi.stubGlobal('fetch',vi.fn((_url,init)=>new Promise((_resolve,reject)=>init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))));
 const controller=new AbortController();const result=roadmapApi('/workspace','synthetic',undefined,controller.signal);
 const check=expect(result).rejects.toMatchObject({name:'AbortError'});controller.abort();await check;
});
