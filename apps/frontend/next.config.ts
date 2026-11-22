import type { NextConfig } from 'next';
const nextConfig: NextConfig = {
 poweredByHeader: false,
 productionBrowserSourceMaps: false,
 async headers() {
  return [{source: '/:path*', headers: [
   {key: 'X-Content-Type-Options', value: 'nosniff'},
   {key: 'X-Frame-Options', value: 'DENY'},
   {key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin'},
   {key: 'Cross-Origin-Opener-Policy', value: 'same-origin-allow-popups'},
   {key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()'},
  ]}];
 },
 ...(process.env.NODE_ENV === 'development' ? {allowedDevOrigins: ['localhost', '127.0.0.1']} : {}),
};
export default nextConfig;
