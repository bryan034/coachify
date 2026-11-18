const base = process.env.NEXT_PUBLIC_API_BASE_URL || '/api/v1';
/** Data-owning services that expose the development-only `POST <prefix>/dev/reset` (hidden outside APP_ENV=development). */
export const resetPrefixes = ['career', 'cv', 'assessments', 'roadmaps', 'jobs', 'profile'] as const;
export type ResetResult = { failed: { prefix: string; message: string }[] };
/** Deletes the signed-in account's goal, CVs, assessments, roadmaps, applications and manual skills. The account, session and onboarding stay. */
export async function resetWorkspace(token: string): Promise<ResetResult> {
  const settled = await Promise.all(resetPrefixes.map(async (prefix): Promise<{ prefix: string; message: string } | null> => {
    try {
      const response = await fetch(`${base}/${prefix}/dev/reset`, { method: 'POST', cache: 'no-store', headers: { Authorization: `Bearer ${token}` } });
      return response.ok ? null : { prefix, message: response.status === 404 ? 'reset is not enabled (APP_ENV must be development)' : `HTTP ${response.status}` };
    } catch { return { prefix, message: 'unreachable' }; }
  }));
  return { failed: settled.filter((item): item is { prefix: string; message: string } => item !== null) };
}
