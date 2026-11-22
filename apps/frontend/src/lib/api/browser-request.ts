/** Browser storage holds a public session marker; only the gateway reads the HttpOnly credential. */
export function browserRequest(init: RequestInit = {}, marker?: string): RequestInit {
 const headers = new Headers(init.headers);
 headers.delete('Authorization');
 headers.set('X-Elo-Browser', '1');
 if (marker) headers.set('X-Elo-Session', marker);
 else headers.delete('X-Elo-Session');
 return { ...init, headers: Object.fromEntries(headers.entries()), credentials: 'same-origin', redirect: 'error' };
}
