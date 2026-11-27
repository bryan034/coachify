import { browserRequest } from './browser-request';
import type { Account } from '@/features/profile/profile-provider';
const base = '/api/v1';
const DISABLED = 'not enabled (APP_ENV must be development)';
/** Data-owning services that expose the development-only `POST <prefix>/dev/reset` (hidden outside APP_ENV=development). */
export const resetPrefixes = ['career', 'cv', 'assessments', 'roadmaps', 'jobs', 'profile'] as const;
export type ResetPrefix = typeof resetPrefixes[number];
export type ResetResult = { failed: { prefix: string; message: string }[] };
export type AccountType = NonNullable<Account['account_type']>;
/** Deletes the signed-in account's data in the given services (all by default: goal, CVs, assessments, roadmaps, applications and manual skills). The account, session and onboarding stay. */
export async function resetWorkspace(token: string, prefixes: readonly ResetPrefix[] = resetPrefixes): Promise<ResetResult> {
  const settled = await Promise.all(prefixes.map(async (prefix): Promise<{ prefix: string; message: string } | null> => {
    try {
      const response = await fetch(`${base}/${prefix}/dev/reset`, browserRequest({ method: 'POST', cache: 'no-store' }, token));
      return response.ok ? null : { prefix, message: response.status === 404 ? `reset is ${DISABLED}` : `HTTP ${response.status}` };
    } catch { return { prefix, message: 'unreachable' }; }
  }));
  return { failed: settled.filter((item): item is { prefix: string; message: string } => item !== null) };
}
export async function switchAccountType(token: string, accountType: AccountType): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${base}/profile/dev/account-type`, browserRequest({
      method: 'PUT', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_type: accountType }),
    }, token));
  } catch { throw new Error('Could not switch plan: Profile is unreachable.'); }
  if (!response.ok) throw new Error(response.status === 404 ? `Plan switching is ${DISABLED}.` : `Could not switch plan (HTTP ${response.status}).`);
}
