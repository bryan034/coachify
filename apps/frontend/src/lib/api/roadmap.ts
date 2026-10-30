const base = process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1';
export class RoadmapError extends Error { constructor(message: string, public status: number, public code: string) { super(message); } }
export async function roadmapApi<T>(path: string, token: string, body?: unknown, signal?: AbortSignal): Promise<T> {
 const response = await fetch(`${base}/roadmaps${path}`, { method: body === undefined ? 'GET' : 'POST', cache: 'no-store', signal,
  headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
 const value = await response.json().catch(() => ({}));
 if (!response.ok) {
  if (response.status === 401) window.dispatchEvent(new CustomEvent('elo:expired', { detail: token }));
  throw new RoadmapError(typeof value.detail === 'string' ? value.detail : 'Your plan could not be loaded or saved. Retry to recover your saved work.', response.status, value.code || 'request_failed');
 }
 if (!Number.isInteger(value.version) || (!['/messages','/progress'].includes(path) && (!Array.isArray(value.messages) || typeof value.context?.ready !== 'boolean'))) throw new RoadmapError('The saved workspace could not be confirmed. Reload to recover it.', 502, 'invalid_response');
 return value as T;
}
