import { REDIRECTS } from './redirects.mjs';

// The frontend only talks to the Python API through /api/*; it holds no credentials of its own.
const API_ORIGIN = process.env.FLOWMERCE_API_ORIGIN || 'http://127.0.0.1:8787';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Refresh now / Sync MCF sheet now read Shopify, Supabase and Google before answering (about 20-35 s). Next's
  // default 30 s limit for /api/* turned a finished refresh into "Request failed (500)"; wait up to 3 minutes.
  experimental: { proxyTimeout: 180_000 },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${API_ORIGIN}/api/:path*` }];
  },
  async headers() {
    return [{
      source: '/:path*',
      headers: [
        { key: 'X-Content-Type-Options', value: 'nosniff' },
        { key: 'Referrer-Policy', value: 'same-origin' },
        { key: 'X-Frame-Options', value: 'DENY' },
        { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
      ],
    }];
  },
  async redirects() {
    // Pages that were merged keep working through their old addresses (see redirects.mjs).
    // Local operator mode has no sign-in, so /login goes to Home. The hosted image is built with FLOWMERCE_HOSTED=1
    // and leaves this out: there src/middleware.js shows the sign-in page.
    const login = process.env.FLOWMERCE_HOSTED === '1' ? [] : [{ source: '/login', destination: '/' }];
    return [...REDIRECTS, ...login].map((r) => ({ ...r, permanent: false }));
  },
};

// GitHub Pages demo (FLOWMERCE_STATIC_EXPORT=1, set only by the CI deploy job): plain static files served under
// /<repo>, demo data only. Rewrites, redirects and headers need a server, so they are left out of that build.
const staticExport = process.env.FLOWMERCE_STATIC_EXPORT === '1';
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';

export default staticExport
  ? {
      reactStrictMode: true,
      output: 'export',
      basePath,
      trailingSlash: true,
      images: { unoptimized: true },
    }
  : nextConfig;
