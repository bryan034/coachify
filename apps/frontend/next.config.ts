import type { NextConfig } from 'next';

const isDev = process.env.NODE_ENV === 'development';
const csp = [
 "default-src 'self'",
 `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ''} https://accounts.google.com/gsi/client`,
 "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
 "img-src 'self' data: blob:",
 "font-src 'self'",
 "connect-src 'self' https://accounts.google.com/gsi/",
 "frame-src https://accounts.google.com/gsi/",
 "object-src 'none'",
 "base-uri 'self'",
 "form-action 'self'",
 "frame-ancestors 'none'",
].join('; ');

const nextConfig: NextConfig = {
 poweredByHeader: false,
 ...(isDev ? { allowedDevOrigins: ['localhost', '127.0.0.1'] } : {}),
 async headers() {
  return [
   {
    source: '/:path*',
    headers: [
     { key: 'Content-Security-Policy', value: csp },
     { key: 'X-Content-Type-Options', value: 'nosniff' },
     { key: 'X-Frame-Options', value: 'DENY' },
     { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
     { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
    ],
   },
  ];
 },
};
export default nextConfig;
