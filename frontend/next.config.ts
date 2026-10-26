import type { NextConfig } from 'next';
const config: NextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  distDir: process.env.NEXT_DIST_DIR || '.next',
  allowedDevOrigins: ['127.0.0.1'],
  experimental: {
    workerThreads: true,
    cpus: 4,
  },
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${process.env.API_BASE_URL || 'http://127.0.0.1:8000'}/api/:path*` },
      { source: '/assets/:path*', destination: `${process.env.API_BASE_URL || 'http://127.0.0.1:8000'}/assets/:path*` },
    ];
  },
};
export default config;
