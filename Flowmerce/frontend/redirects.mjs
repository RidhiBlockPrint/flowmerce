/**
 * Old addresses and where they go now. Used by next.config.mjs (so bookmarks and links keep working) and checked by
 * frontend/tests/routes.test.mjs against the pages that exist. Pages were merged, not removed:
 *   Blogs → Articles, SEO Overview → Home, per-brand Workspace → Articles (that brand),
 *   Data & reports, Integrations and Audit log → Settings, Write it yourself → Blog pipeline (2026-11-24).
 * Query strings (filters, tabs) are carried over by Next.js.
 */
export const REDIRECTS = [
    { source: '/blogs', destination: '/articles' },
    { source: '/blogs/:id', destination: '/articles/:id' },
    { source: '/seo', destination: '/' },
    { source: '/workspace', destination: '/articles' },
    { source: '/workspace/:brand', destination: '/articles?brand=:brand' },
    { source: '/data', destination: '/settings/data' },
    { source: '/integrations', destination: '/settings/integrations' },
    { source: '/audit', destination: '/settings/audit' },
    { source: '/settings', destination: '/settings/integrations' },
    { source: '/write', destination: '/pipeline' },
    // /login is handled by src/middleware.js: the sign-in page on the hosted copy, Home on your own computer.
];
