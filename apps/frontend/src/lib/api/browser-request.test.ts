import { expect, it } from 'vitest';
import { browserRequest } from './browser-request';

it('sends only a public marker and same-origin cookies, without following redirects', () => {
 const init = browserRequest({ credentials: 'include', redirect: 'follow', headers: { Authorization: 'Bearer must-not-leave-the-browser', 'Content-Type': 'application/json' } }, 'public-marker');
 const headers = new Headers(init.headers);
 expect(headers.has('Authorization')).toBe(false);
 expect(headers.get('X-Elo-Browser')).toBe('1');
 expect(headers.get('X-Elo-Session')).toBe('public-marker');
 expect(headers.get('Content-Type')).toBe('application/json');
 expect(init.credentials).toBe('same-origin');
 expect(init.redirect).toBe('error');
});

it('does not reuse a marker for unauthenticated account requests', () => {
 const init = browserRequest({ headers: { 'X-Elo-Session': 'stale' }, body: new FormData() });
 const headers = new Headers(init.headers);
 expect(headers.has('X-Elo-Session')).toBe(false);
 expect(headers.has('Content-Type')).toBe(false);
 expect(headers.get('X-Elo-Browser')).toBe('1');
});
