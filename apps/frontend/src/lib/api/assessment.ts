import type { Assessment } from '@/features/roadmap/types';
const base = process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1';
const statuses = ['supported', 'partial', 'uncertain', 'confirmed_shortfall'] as const;
export type SkillMatch = typeof statuses[number] | 'covered';
type Outcome = { ref?: unknown; match_status?: unknown };
type Group = { operator?: unknown; match_status?: unknown; requirement_refs?: unknown };

/**
 * How the saved comparison rates each job skill, keyed by the goal skill's item_id. The read never starts a comparison. Null means no fresh comparison exists or it could not be read, so callers show skills unmarked.
 */
export async function currentSkillMatches(token: string, signal: AbortSignal): Promise<Record<string, SkillMatch> | null> {
 try {
  const response = await fetch(`${base}/assessments/current`, { cache: 'no-store', signal, headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) return null;
  const value = await response.json();
  if (value?.stale !== false || !Array.isArray(value.result?.job_skill_gaps)) return null;
  const covered = new Set<unknown>((Array.isArray(value.result.groups) ? value.result.groups as Group[] : [])
   .filter(group => group.operator === 'any' && group.match_status === 'supported' && Array.isArray(group.requirement_refs))
   .flatMap(group => group.requirement_refs as unknown[]));
  const matches: Record<string, SkillMatch> = {};
  for (const outcome of value.result.job_skill_gaps as Outcome[]) {
   if (typeof outcome.ref !== 'string' || !outcome.ref.startsWith('job:') || !statuses.includes(outcome.match_status as typeof statuses[number])) continue;
   matches[outcome.ref.slice(4)] = outcome.match_status !== 'supported' && covered.has(outcome.ref) ? 'covered' : outcome.match_status as SkillMatch;
  }
  return matches;
 } catch { return null; }
}

/** Owner-scoped commands retain UUID and expected revision on ambiguous transport failures. */
export async function assessmentApi<T>(path: string, token: string, body?: unknown, signal?: AbortSignal): Promise<T> {
 const response = await fetch(`${base}/assessments${path}`, {method: body === undefined ? 'GET' : 'POST', cache: 'no-store', signal,
 headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
 const value = await response.json();
 if (!response.ok) {
  if (response.status === 401) window.dispatchEvent(new CustomEvent('elo:expired', {detail: token}));
  throw Object.assign(new Error('Your comparison could not be completed. Reload and try again.'), {code: value.code, status: response.status});
 }
 return value as T;
}
/** The full comparison outcome for each goal skill, keyed like skillMatches. */
export function skillOutcomes(result: Assessment): Record<string, Assessment['job_skill_gaps'][number]> {
 return Object.fromEntries(result.job_skill_gaps.map(item => [item.ref.slice(4), item]));
}
export function skillMatches(result: Assessment): Record<string, SkillMatch> {
 const covered = new Set((result.groups ?? []).filter(group => group.operator === 'any' && group.match_status === 'supported').flatMap(group => group.requirement_refs));
 return Object.fromEntries(result.job_skill_gaps.map(item => [item.ref.slice(4), item.match_status !== 'supported' && covered.has(item.ref) ? 'covered' : item.match_status]));
}
