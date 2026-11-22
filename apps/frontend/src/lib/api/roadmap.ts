import { browserRequest } from './browser-request';
const base = '/api/v1';
export class RoadmapError extends Error { constructor(message: string, public status: number, public code: string) { super(message); } }
export async function roadmapApi<T>(path: string, token: string, body?: unknown, signal?: AbortSignal, init?: RequestInit): Promise<T> {
 const workspaceRead=body===undefined && path.split('?')[0]==='/workspace';
 const controller=workspaceRead ? new AbortController() : null;
 let timedOut=false;
 const abort=()=>controller?.abort();
 if(signal?.aborted) abort();
 signal?.addEventListener('abort',abort,{once:true});
 const timer=controller ? setTimeout(()=>{timedOut=true;controller.abort();},20000) : null;
 try {
 const response = await fetch(`${base}/roadmaps${path}`, browserRequest({ method: body === undefined ? 'GET' : 'POST', cache: 'no-store', signal: controller?.signal || signal,
  headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }), ...init }, token));
 const value = await response.json().catch(() => ({}));
 if (!response.ok) {
  if (response.status === 401) window.dispatchEvent(new CustomEvent('elo:expired', { detail: token }));
  throw new RoadmapError(typeof value.detail === 'string' ? value.detail : 'Your plan could not be loaded or saved. Retry to recover your saved work.', response.status, value.code || 'request_failed');
 }
 if (path !== '/planner/runway' && path !== '/learning' && path !== '/planner/evidence-proposals' && (!Number.isInteger(value.version) || (!['/messages','/progress','/planner/generate','/planner/outlines/generate','/planner/weeks/generate','/planner/months/generate','/planner/roll-forward','/dashboard-source','/planner/sessions/free-times','/planner/sessions/backlog-plan'].includes(path) && (!Array.isArray(value.messages) || typeof value.context?.ready !== 'boolean')))) throw new RoadmapError('The saved workspace could not be confirmed. Reload to recover it.', 502, 'invalid_response');
 return value as T;
 } catch(error) {
  if(timedOut) throw new RoadmapError('Loading your roadmap took too long. Retry loading; your saved work is unchanged.',504,'workspace_timeout');
  throw error;
 } finally {
  if(timer!==null) clearTimeout(timer);
  signal?.removeEventListener('abort',abort);
 }
}
