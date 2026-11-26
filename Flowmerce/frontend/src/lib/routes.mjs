/**
 * The Flowmerce navigation: one list that the sidebar renders and the tests check against the real pages.
 * Employees pick a business module first, then its functions. Each module owns its own pages:
 *   - every module entry expands to its everyday pages (`items`) and a collapsed "Advanced" group (`advanced`): pages and
 *     tabs that are set up once or opened now and then (owner decision 2026-11-20: declutter every module);
 *   - Shipping, Conversion (CRO), Ads and Creative Strategist are one page each with tabs: their entries point at a tab (`tab`), and the module
 *     entry itself (`to`) opens the page.
 * New business modules are added here as one top-level entry. Integrations are never top-level: they live in SETTINGS.
 * SEO & Blog lists its pages in the order a blog is built (owner request 2026-11-24): Overview, Blog pipeline (topic → draft →
 * schedule on one page), Content calendar, Publishing, then all Articles.
 *
 * The sidebar is the only way between a module's pages and tabs (owner request 2026-11-24): pages do not repeat it as a
 * tab strip. A page with tabs lists each tab here (`tab`); its first listed tab is the page's default (no ?tab=).
 * `blurb` is the module's one-line description under its name in the sidebar; its colour is set in globals.css
 * (.nav-module[data-mod]).
 *
 * `perm` hides an item from roles that cannot use it. `badge: 'publishing'` shows the number of publish requests that
 * need attention next to the item.
 */
export const NAV = [
    { id: 'home', kind: 'link', label: 'Home', to: '/', icon: 'home', end: true, blurb: 'Today across every module' },
    { id: 'seo', kind: 'module', label: 'SEO & Blog', icon: 'blogs', to: '/blog', blurb: 'Blogs and publishing', items: [
        { to: '/blog', label: 'Overview', icon: 'overview' },
        { to: '/pipeline', label: 'Blog pipeline', icon: 'edit' },
        { to: '/calendar', label: 'Content calendar', icon: 'calendar' },
        { to: '/publishing', label: 'Publishing', icon: 'publish', badge: 'publishing' },
        { to: '/articles', label: 'Articles', icon: 'blogs' },
    ], advanced: [
        { to: '/topics', tab: 'topics', label: 'Topics', icon: 'topics' },
        { to: '/topics', tab: 'keywords', label: 'Keywords', icon: 'target' },
        { to: '/analytics', tab: 'gsc', label: 'Search Console', icon: 'google' },
        { to: '/analytics', tab: 'ga4', label: 'GA4 traffic', icon: 'analytics' },
        { to: '/analytics', tab: 'articles', label: 'Traffic by article', icon: 'trend' },
        { to: '/automation', label: 'Automation', icon: 'automation' },
    ] },
    { id: 'shipping', kind: 'module', label: 'Shipping', to: '/shipping', icon: 'truck', blurb: 'Parcels on their way', items: [
        { to: '/shipping', tab: 'overview', label: 'Overview', icon: 'overview' },
        { to: '/shipping', tab: 'shipments', label: 'Shipments', icon: 'truck' },
        { to: '/shipping', tab: 'checks', label: 'Hand checks', icon: 'alert' },
    ], advanced: [
        { to: '/shipping', tab: 'analytics', label: 'Analytics', icon: 'analytics' },
    ] },
    { id: 'cro', kind: 'module', label: 'Conversion (CRO)', to: '/cro', icon: 'target', blurb: 'Visitors into orders', items: [
        { to: '/cro', tab: 'overview', label: 'Overview', icon: 'overview' },
        { to: '/cro', tab: 'conversion', label: 'Conversion', icon: 'target' },
        { to: '/cro', tab: 'landing', label: 'Landing pages', icon: 'link' },
        { to: '/cro', tab: 'checkout', label: 'Cart & checkout', icon: 'store' },
        { to: '/cro', tab: 'products', label: 'Products', icon: 'library' },
        { to: '/cro', tab: 'sales', label: 'Sales', icon: 'trend' },
    ], advanced: [
        { to: '/cro', tab: 'site', label: 'Site health', icon: 'monitor' },
        { to: '/cro', tab: 'recommendations', label: 'Recommendations', icon: 'sparkle' },
        { to: '/cro', tab: 'experiments', label: 'Experiments', icon: 'flag' },
        { to: '/cro', tab: 'alarms', label: 'Alarms', icon: 'clock' },
        { to: '/cro', tab: 'changes', label: 'Change log', icon: 'history' },
    ] },
    // Meta and Google Ads in one module (owner decision 2026-11-24); a tab for one platform only shows that platform.
    { id: 'ads', kind: 'module', label: 'Ads', to: '/ads', icon: 'trend', blurb: 'Meta and Google Ads', items: [
        { to: '/ads', tab: 'overview', label: 'Overview', icon: 'overview' },
        { to: '/ads', tab: 'campaigns', label: 'Campaigns', icon: 'list' },
        { to: '/ads', tab: 'creatives', label: 'Creatives', icon: 'image' },
        { to: '/ads', tab: 'funnel', label: 'Funnel', icon: 'filter' },
        { to: '/ads', tab: 'actions', label: 'Actions', icon: 'tasks' },
    ], advanced: [
        { to: '/ads', tab: 'search', label: 'Search terms', icon: 'search' },
        { to: '/ads', tab: 'gap', label: 'ABO to CBO gap', icon: 'link' },
        { to: '/ads', tab: 'rules', label: 'Rules', icon: 'settings' },
    ] },
    { id: 'creative', kind: 'module', label: 'Creative Strategist', to: '/creative', icon: 'sparkle', blurb: 'AI creative, from the ad figures', items: [
        { to: '/creative', tab: 'overview', label: 'Insights', icon: 'analytics' },
        { to: '/creative', tab: 'concepts', label: 'Concepts', icon: 'star' },
        { to: '/creative', tab: 'pack', label: 'AI pack', icon: 'sparkle' },
    ] },
];

/** A page's default tab: the first of its tabs listed in the menu (shown when the address has no ?tab=). */
export function defaultTab(to) {
    for (const e of NAV)
        for (const i of e.kind === 'module' ? [...e.items, ...(e.advanced ?? [])] : [])
            if (i.to === to && i.tab)
                return i.tab;
    return 'overview';
}

/** Where a menu item goes: its page, plus `?tab=` for a tab other than the page's first one. */
export const hrefOf = (item) => (item.tab && item.tab !== defaultTab(item.to) ? `${item.to}?tab=${item.tab}` : item.to);

/** Whether a menu item is the page (and tab) on screen. `tab` is the address's ?tab= value (none = the first tab). */
export function itemActive(item, pathname, tab, end = false) {
    if (!pathMatches(pathname, item.to, end))
        return false;
    return item.tab ? (tab || defaultTab(item.to)) === item.tab : true;
}

/** The menu's name for a page's tab, so a page can say where you are now that it has no tab strip of its own. */
export function tabLabel(to, tab) {
    const want = tab || defaultTab(to);
    for (const e of NAV)
        for (const i of e.kind === 'module' ? [...e.items, ...(e.advanced ?? [])] : [])
            if (i.to === to && i.tab === want)
                return i.label;
    return '';
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
export const NO_SEARCH_PATHS = ['/settings', '/shipping', '/cro', '/ads', '/creative'];

export const pathMatches = (pathname, to, end = false) => (end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`));
/** Which business module a page belongs to: 'home', 'seo', 'shipping', 'cro', 'ads', 'creative', 'settings', or null for an unknown page. */
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
