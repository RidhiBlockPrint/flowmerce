/**
 * The Flowmerce navigation: one list that the sidebar renders and the tests check against the real pages.
 * Employees pick a business module first, then its functions. Each module owns its own pages:
 *   - every module entry expands to its everyday pages (`items`) and a collapsed "Advanced" group (`advanced`): pages and
 *     tabs that are set up once or opened now and then (owner decision 2026-11-20: declutter every module);
 *   - Shipping and Conversion (CRO) are one page each with tabs: their entries point at a tab (`tab`), and the module
 *     entry itself (`to`) opens the page.
 * New business modules are added here as one top-level entry. Integrations are never top-level: they live in SETTINGS.
 *
 * `perm` hides an item from roles that cannot use it. `badge: 'publishing'` shows the number of publish requests that
 * need attention next to the item.
 */
export const NAV = [
    { id: 'home', kind: 'link', label: 'Home', to: '/', icon: 'home', end: true },
    { id: 'seo', kind: 'module', label: 'SEO & Blog', icon: 'blogs', to: '/blog', items: [
        { to: '/blog', label: 'Overview', icon: 'overview' },
        { to: '/articles', label: 'Articles', icon: 'blogs' },
        { to: '/calendar', label: 'Content calendar', icon: 'calendar' },
        { to: '/publishing', label: 'Publishing', icon: 'publish', badge: 'publishing' },
    ], advanced: [
        { to: '/write', label: 'Write it yourself', icon: 'edit' },
        { to: '/topics', label: 'Topics & keywords', icon: 'topics' },
        { to: '/analytics', label: 'SEO & traffic', icon: 'analytics' },
        { to: '/automation', label: 'Automation', icon: 'automation' },
    ] },
    { id: 'shipping', kind: 'module', label: 'Shipping', to: '/shipping', icon: 'truck', items: [
        { to: '/shipping', tab: 'overview', label: 'Overview', icon: 'overview' },
        { to: '/shipping', tab: 'shipments', label: 'Shipments', icon: 'truck' },
        { to: '/shipping', tab: 'unfulfilled', label: 'Unfulfilled', icon: 'inbox' },
        { to: '/shipping', tab: 'checks', label: 'Checks and exceptions', icon: 'alert' },
    ], advanced: [
        { to: '/shipping', tab: 'analytics', label: 'Analytics', icon: 'analytics' },
    ] },
    { id: 'cro', kind: 'module', label: 'Conversion (CRO)', to: '/cro', icon: 'target', items: [
        { to: '/cro', tab: 'overview', label: 'Overview', icon: 'overview' },
        { to: '/cro', tab: 'conversion', label: 'Conversion', icon: 'target' },
        { to: '/cro', tab: 'checkout', label: 'Cart & checkout', icon: 'store' },
        { to: '/cro', tab: 'products', label: 'Products', icon: 'library' },
        { to: '/cro', tab: 'sales', label: 'Sales', icon: 'trend' },
        { to: '/cro', tab: 'recommendations', label: 'Recommendations', icon: 'sparkle' },
    ], advanced: [
        { to: '/cro', tab: 'alarms', label: 'Alarms', icon: 'clock' },
        { to: '/cro', tab: 'changes', label: 'Change log', icon: 'history' },
    ] },
];

/** Where a menu item goes: its page, plus `?tab=` for a tab other than the page's first one. */
export const hrefOf = (item) => (item.tab && item.tab !== 'overview' ? `${item.to}?tab=${item.tab}` : item.to);

/** Whether a menu item is the page (and tab) on screen. `tab` is the address's ?tab= value (none = the first tab). */
export function itemActive(item, pathname, tab, end = false) {
    if (!pathMatches(pathname, item.to, end))
        return false;
    return item.tab ? (tab || 'overview') === item.tab : true;
}

/** A module's pages, everyday ones first, then its Advanced group. */
export const moduleItems = (e) => (e.kind === 'module' ? [...e.items, ...(e.advanced ?? [])] : [e]);

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
    ...NAV.flatMap(moduleItems),
    ...SETTINGS.items,
];

/** Pages where the date-range control means something (they read figures for a period). */
export const RANGE_PATHS = ['/analytics', '/articles/'];

/** Pages that do not search articles and topics, so the global search box is not shown there. */
export const NO_SEARCH_PATHS = ['/settings', '/shipping', '/cro'];

export const pathMatches = (pathname, to, end = false) => (end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`));
/** Which business module a page belongs to: 'home', 'seo', 'shipping', 'cro', 'settings', or null for an unknown page. */
export function moduleOf(pathname) {
    if (pathMatches(pathname, SETTINGS.root))
        return 'settings';
    for (const e of NAV) {
        if (e.kind === 'module' ? moduleItems(e).some((i) => pathMatches(pathname, i.to)) : pathMatches(pathname, e.to, e.end))
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
