import type { NextConfig } from 'next';
const nextConfig: NextConfig = {
 poweredByHeader: false,
 ...(process.env.NODE_ENV === 'development' ? {allowedDevOrigins: ['localhost', '127.0.0.1']} : {}),
};
export default nextConfig;
