const base = process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1';
const statuses = ['supported', 'partial', 'uncertain', 'confirmed_shortfall'] as const;
export type SkillMatch = typeof statuses[number] | 'covered';
type Outcome = { ref?: unknown; match_status?: unknown };
type Group = { operator?: unknown; match_status?: unknown; requirement_refs?: unknown };

/**
 * How the saved comparison rates each job skill, keyed by the goal skill's item_id. Read-only: it never starts
 * an analysis. Null means no fresh comparison exists or it could not be read, so callers show skills unmarked.
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
