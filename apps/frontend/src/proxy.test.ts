import { afterEach, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy } from './proxy';

afterEach(() => vi.unstubAllEnvs());

it('uses a fresh server nonce, overwrites untrusted headers, and prevents page caching', () => {
 vi.stubEnv('NODE_ENV', 'production');
 const request = new NextRequest('http://localhost/login', { headers: { 'x-nonce': 'attacker', 'Content-Security-Policy': "script-src 'unsafe-inline'" } });
 const response = proxy(request), other = proxy(request);
 const nonce = response.headers.get('x-middleware-request-x-nonce');
 const policy = response.headers.get('Content-Security-Policy');
 expect(nonce).toBeTruthy();
 expect(nonce).not.toBe('attacker');
 expect(nonce).not.toBe(other.headers.get('x-middleware-request-x-nonce'));
 expect(policy).toContain(`'nonce-${nonce}'`);
 expect(policy).toContain("script-src-attr 'none'");
 expect(policy).toContain("frame-ancestors 'none'");
 expect(policy?.split('; ').find(rule => rule.startsWith('script-src '))).not.toMatch(/unsafe-inline|unsafe-eval/);
 expect(policy).toBe(response.headers.get('x-middleware-request-content-security-policy'));
 expect(response.headers.get('Cache-Control')).toBe('private, no-store');
});

it('allows development debugging without weakening the production policy', () => {
 vi.stubEnv('NODE_ENV', 'development');
 expect(proxy(new NextRequest('http://localhost/')).headers.get('Content-Security-Policy')).toContain("'unsafe-eval'");
});
