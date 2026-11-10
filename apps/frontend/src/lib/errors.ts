/** User-facing wording for failures. Technical detail stays in the console and Network tab. */

/** True when a request stopped because the page navigated away or unmounted. Never show these. */
export function isAbortError(cause: unknown): boolean {
 if (typeof DOMException !== 'undefined' && cause instanceof DOMException && cause.name === 'AbortError') return true;
 if (cause instanceof Error) return cause.name === 'AbortError' || /signal is aborted|operation was aborted|aborted without reason|the user aborted a request/i.test(cause.message);
 return false;
}

const NETWORK = /failed to fetch|networkerror|network request failed|load failed|fetch failed/i;

/** Backend codes whose detail describes a model or validation step rather than something the user can act on. */
const FRIENDLY_CODES: Record<string, string> = {
 assessment_output: 'We couldn’t compare your skills this time. Try again.',
 assessment_failed: 'We couldn’t compare your skills this time. Try again.',
 model_output: 'elo couldn’t finish this step. Try again.',
 model_provider: 'elo’s assistant is unavailable right now. Try again in a moment.',
 model_quota: 'elo is busy right now. Try again in a moment.',
 model_context: 'This is too long for elo to handle in one go. Shorten it and try again.',
 operation_failed: 'elo couldn’t finish this step. Try again.',
 result_capacity: 'elo couldn’t finish this step. Try again.',
 storage: 'Your work is saved, but elo couldn’t load it just now. Try again.',
 upstream: 'Part of elo isn’t responding right now. Try again in a moment.',
};

/** Phrases that are internal validation or plumbing messages and must not reach the page. */
const TECHNICAL = [/source-scoped/i, /schema/i, /validation failed/i, /traceback/i, /unexpected token/i, /json/i, /interpretation is unavailable/i, /^\s*\d{3}\b/];

export function friendlyCode(code: string | null | undefined): string | null {
 return code ? FRIENDLY_CODES[code] ?? null : null;
}

/**
 * The message to show for a failure, or null when nothing should be shown (an aborted request).
 * Logs the original so developers can still see it.
 */
export function friendlyError(cause: unknown, fallback: string, code?: string | null): string | null {
 if (isAbortError(cause)) return null;
 const raw = cause instanceof Error ? cause.message : typeof cause === 'string' ? cause : '';
 const status = cause && typeof cause === 'object' && 'code' in cause && typeof (cause as { code: unknown }).code === 'string' ? (cause as { code: string }).code : null;
 const mapped = friendlyCode(code ?? status);
 if (raw || mapped) console.warn('[elo]', code ?? status ?? '', raw || cause);
 if (mapped) return mapped;
 if (!raw) return fallback;
 if (NETWORK.test(raw)) return 'We couldn’t reach elo. Check your connection and try again.';
 if (TECHNICAL.some(pattern => pattern.test(raw))) return fallback;
 return raw;
}

/** A failed operation's `{ detail, code }` as one line for the page. */
export function friendlyOperationError(error: { detail?: string | null; code?: string | null } | null | undefined, fallback: string): string {
 if (!error) return fallback;
 return friendlyError(error.detail ? new Error(error.detail) : null, fallback, error.code) ?? fallback;
}

/** Same as `friendlyError`, but an empty string for aborted requests so it can feed error state directly. */
export const errorText = (cause: unknown, fallback: string): string => friendlyError(cause, fallback) ?? '';
