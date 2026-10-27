import {careerApi} from './career';

export type CareerOperation={activities?:string[];operation_id:string;status:'running'|'repairing'|'waiting_quota'|'succeeded';limit_scope?:'user'|'provider'|null;provider?:string|null;retry_after:number|null;result:unknown;validation_feedback?:{reason:string;fields:string[];violations:{field:string;issue:string}[]}|null};

function pause(milliseconds:number,signal?:AbortSignal|null){
 return new Promise<void>((resolve,reject)=>{
  if(signal?.aborted){reject(new DOMException('Aborted','AbortError'));return;}
  const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
  const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},milliseconds);
  signal?.addEventListener('abort',abort,{once:true});
 });
}

/** Poll an owner-scoped job; only the server resumes the paused LLM call. */
export async function careerOperation<T>(path:string,token:string,options:RequestInit,onProgress:(job:CareerOperation)=>void):Promise<T>{
 const headers=new Headers(options.headers);
 headers.set('Prefer','respond-async');
 if(!headers.has('Idempotency-Key'))headers.set('Idempotency-Key',crypto.randomUUID());
 let value=await careerApi<T|CareerOperation>(path,token,{...options,headers:Object.fromEntries(headers)});
 // Older consumers/servers can still use the synchronous response shape.
 if(!value||typeof value!=='object'||!('operation_id' in value))return value as T;
 let job=value as CareerOperation;
 while(job.status!=='succeeded'){
  onProgress(job);
  await pause(job.status==='waiting_quota'?Math.min(60,Math.max(1,job.retry_after||1))*1000:1000,options.signal);
  job=await careerApi<CareerOperation>(`/workspace/operations/${job.operation_id}`,token,{signal:options.signal});
 }
 return job.result as T;
}
