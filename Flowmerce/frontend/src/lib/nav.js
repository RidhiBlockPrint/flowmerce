'use client';
/**
 * Thin helpers over the Next.js App Router (next/navigation) that keep the page code short:
 * `useNavigate()` pushes a route, `useSearchParams()` returns [params, setParams] where setParams
 * rewrites the query string of the current page (optionally replacing the history entry).
 */
import { useRouter, useSearchParams as useNextSearchParams } from 'next/navigation';
import { useCallback } from 'react';

export { useParams, usePathname } from 'next/navigation';

export function useNavigate() {
  const router = useRouter();
  return useCallback((to) => router.push(to), [router]);
}

/**
 * Tabs, filters and pages live in the query string. Changing only the query string goes through the browser's own
 * history API, which Next.js watches (useSearchParams updates at once), instead of router.replace/push: those ask the
 * server for the page again before anything changes on screen, which made every tab or filter click wait one extra
 * round trip (~135 ms on the hosted copy) before the tab even highlighted and its data request could start.
 */
export function useSearchParams() {
  const sp = useNextSearchParams();
  const setSp = useCallback((next, opts = {}) => {
    const q = new URLSearchParams(next).toString();
    // window.location.pathname keeps the base path and trailing slash of the static demo build.
    const url = (q ? `${window.location.pathname}?${q}` : window.location.pathname) + window.location.hash;
    if (opts.replace) window.history.replaceState(null, '', url);
    else window.history.pushState(null, '', url);
  }, []);
  return [sp, setSp];
}
