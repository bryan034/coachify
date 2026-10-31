import {ApiError} from './profile';

function interrupted(cause:unknown){
 // Model/validation failures are terminal operation results, not lost reads.
 return cause instanceof TypeError||cause instanceof ApiError&&
  !('code' in cause&&cause.code)&&[408,500,502,503,504].includes(cause.status);
}

function pause(milliseconds:number,signal?:AbortSignal|null){
 return new Promise<void>((resolve,reject)=>{
  if(signal?.aborted){reject(new DOMException('Aborted','AbortError'));return;}
  const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
  const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},milliseconds);
  signal?.addEventListener('abort',abort,{once:true});
 });
}

/** Retry interrupted status reads only; never replay writes or terminal AI errors. */
export async function retryCareerRead<T>(read:()=>Promise<T>,signal?:AbortSignal|null,onRetry?:()=>void):Promise<T>{
 for(let attempt=0;;attempt++){
  signal?.throwIfAborted();
  try{return await read();}
  catch(cause){
   if(signal?.aborted||attempt>=4||!interrupted(cause))throw cause;
   onRetry?.();
   await pause(Math.min(2000*2**attempt,10000),signal);
  }
 }
}
