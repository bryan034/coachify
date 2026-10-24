import { ApiError } from './profile';
export type CareerPreview = { kind: 'url' | 'document'; text: string; source_name: string; source_url?: string | null; notices: string[] };
export async function importCareer(path: 'url' | 'document', body: string | FormData, token: string, signal: AbortSignal): Promise<CareerPreview> {
 const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1'}/career/imports/${path}`, {
  method: 'POST', body, signal, cache: 'no-store',
  headers: { Authorization: `Bearer ${token}`, ...(typeof body === 'string' ? { 'Content-Type': 'application/json' } : {}) },
 });
 const result = await response.json().catch(() => ({}));
 if (!response.ok) {
  if (response.status === 401) window.dispatchEvent(new CustomEvent('coachify:expired', { detail: token }));
  throw new ApiError(typeof result.detail === 'string' ? result.detail : response.status === 413 ? 'Choose a file up to 10 MiB.' : 'The preview service is unavailable. Retry or paste the description.', response.status);
 }
 if (!result.text || typeof result.text !== 'string' || Array.from(result.text).length > 20_000 || !['url','document'].includes(result.kind) || !Array.isArray(result.notices))
  throw new Error('The source returned an invalid preview. Retry or paste the description.');
 return result;
}
