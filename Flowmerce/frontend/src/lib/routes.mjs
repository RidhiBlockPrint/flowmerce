/**
 * The Flowmerce navigation: one list that the sidebar renders and the tests check against the real pages.
 * Employees pick a business module first, then its functions. Each module owns its own pages:
 *   - a `link` entry is a module with one entry point (Home, Shipping; Shipping keeps its own inner navigation);
 *   - a `module` entry expands to its pages (SEO & Blog owns the whole blogging lifecycle, Automation included).
 * New business modules are added here as one top-level entry. Integrations are never top-level: they live in SETTINGS.
 *
 * `perm` hides an item from roles that cannot use it. `badge: 'publishing'` shows the number of publish requests that
 * need attention next to the item.
 */
export const NAV = [
    { id: 'home', kind: 'link', label: 'Home', to: '/', icon: 'home', end: true },
    { id: 'seo', kind: 'module', label: 'SEO & Blog', icon: 'blogs', items: [
        { to: '/articles', label: 'Articles', icon: 'blogs' },
        { to: '/topics', label: 'Topics & keywords', icon: 'topics' },
        { to: '/publishing', label: 'Publishing', icon: 'publish', badge: 'publishing' },
        { to: '/analytics', label: 'SEO & traffic', icon: 'analytics' },
        { to: '/automation', label: 'Automation', icon: 'automation' },
    ] },
    { id: 'shipping', kind: 'link', label: 'Shipping', to: '/shipping', icon: 'truck' },
];

/** Settings is a gear at the bottom of the sidebar and opens its own set of pages. */
export const SETTINGS = {
    id: 'settings', label: 'Settings', to: '/settings/integrations', icon: 'settings', root: '/settings',
    items: [
        { to: '/settings/integrations', label: 'Integrations', icon: 'plug' },
        { to: '/settings/brands', label: 'Brands', icon: 'store' },
        { to: '/settings/data', label: 'Data management', icon: 'sheet' },
        { to: '/settings/audit', label: 'Audit log', icon: 'audit', perm: 'audit:view' },
    ],
};

/** Every page that has a menu entry (top-level links, module pages and Settings pages). */
export const NAV_ITEMS = [
    ...NAV.flatMap((e) => (e.kind === 'module' ? e.items : [e])),
    ...SETTINGS.items,
];

/** Pages where the date-range control means something (they read figures for a period). */
export const RANGE_PATHS = ['/analytics', '/articles/'];

/** Pages that do not search articles and topics, so the global search box is not shown there. */
export const NO_SEARCH_PATHS = ['/settings', '/shipping'];

export const pathMatches = (pathname, to, end = false) => (end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`));
/** Which business module a page belongs to: 'home', 'seo', 'shipping', 'settings', or null for an unknown page. */
export function moduleOf(pathname) {
    if (pathMatches(pathname, SETTINGS.root))
        return 'settings';
    for (const e of NAV) {
        if (e.kind === 'module' ? e.items.some((i) => pathMatches(pathname, i.to)) : pathMatches(pathname, e.to, e.end))
            return e.id;
    }
    return null;
}
export const usesRange = (pathname) => RANGE_PATHS.some((p) => (p.endsWith('/') ? pathname.startsWith(p) : pathMatches(pathname, p)));
export const showsSearch = (pathname) => !NO_SEARCH_PATHS.some((p) => pathMatches(pathname, p));

/** Where Back goes when this tab has no earlier page (it was opened directly). */
export function parentOf(pathname) {
    if (pathname.startsWith('/articles/'))
        return '/articles';
    return '/';
}
