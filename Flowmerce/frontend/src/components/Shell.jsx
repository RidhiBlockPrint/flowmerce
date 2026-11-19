'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useNavigate } from '../lib/nav';
import { Icon } from './Icon';
import { Logo } from './Logo';
import { Button, Menu, BrandTag } from './ui';
import { Dialog, Drawer } from './overlays';
import { api, useApi, qs } from '../lib/api';
import { useApp, presetRange } from '../lib/app';
import { fmtDate, timeAgo } from '../lib/format';
import { DemoBanner } from './DemoBanner';
import { AmbientBackground } from './AmbientBackground';
import { BudgetWarning } from './claude';
import { IS_DEMO } from '../demo';
import { NAV, SETTINGS, moduleOf, parentOf, pathMatches, showsSearch, usesRange } from '../lib/routes.mjs';
export function Shell({ children }) {
    const { me, can, brand } = useApp();
    const [navOpen, setNavOpen] = useState(false);
    const [tasksOpen, setTasksOpen] = useState(false);
    const loc = { pathname: usePathname() ?? '/' };
    useEffect(() => { setNavOpen(false); setTasksOpen(false); }, [loc.pathname]);
    useEffect(() => {
        if (!navOpen)
            return undefined;
        const onKey = (e) => { if (e.key === 'Escape') setNavOpen(false); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [navOpen]);
    // The Publishing count and the task list are small requests that every page shares.
    const counts = useApi(`/publishing${qs({ brand: brand === 'all' ? undefined : brand })}`);
    const tasks = useApi('/tasks');
    const lastPath = useRef(loc.pathname);
    useEffect(() => {
        // Refresh the counts after moving to another page, so the badge and the task list stay current.
        if (lastPath.current === loc.pathname)
            return;
        lastPath.current = loc.pathname;
        counts.reload();
        tasks.reload();
    }, [loc.pathname]); // eslint-disable-line react-hooks/exhaustive-deps
    const inSettings = moduleOf(loc.pathname) === 'settings';
    const pendingPublish = counts.data?.requests.filter((r) => r.status === 'pending' || r.status === 'failed').length ?? 0;
    const failedPublish = counts.data?.requests.some((r) => r.status === 'failed') ?? false;
    return (<>
      <a className="skip-link" href="#main">Skip to content</a>
      {IS_DEMO ? <DemoBanner /> : null}
      <AmbientBackground />
      <div className="shell">
        {navOpen ? <div className="sidebar-scrim" onClick={() => setNavOpen(false)}/> : null}
        <aside id="sidebar" className={`sidebar ${navOpen ? 'open' : ''}`} aria-label="Main navigation" {...(navOpen ? { role: 'dialog', 'aria-modal': true } : {})}>
          <Link href="/" className="logo">
            <Logo size={20} tagline />
          </Link>
          <button type="button" className="btn ghost icon-only sidebar-close" aria-label="Close navigation" onClick={() => setNavOpen(false)}><Icon name="close"/></button>
          {inSettings ? (<SettingsNav can={can}/>) : (<nav aria-label="Modules">
            {NAV.map((e) => (e.kind === 'module'
                ? <ModuleNav key={e.id} entry={e} can={can} count={pendingPublish} alert={failedPublish}/>
                : <NavItem key={e.id} to={e.to} icon={e.icon} end={e.end} module={e.id}>{e.label}</NavItem>))}
          </nav>)}
          <div className="sidebar-foot">
            {inSettings ? null : <NavItem to={SETTINGS.to} icon={SETTINGS.icon} module="settings" active={false}>{SETTINGS.label}</NavItem>}
            {IS_DEMO ? <DemoUserChip /> : <LocalOperatorBadge />}
          </div>
        </aside>
        <div className="main">
          <header className="topbar">
            <Button className="menu-btn" variant="ghost" iconOnly icon="menu" aria-label="Open navigation" aria-controls="sidebar" aria-expanded={navOpen} onClick={() => setNavOpen(true)}/>
            <BrandSwitch />
            {showsSearch(loc.pathname) ? <GlobalSearch /> : null}
            <div className="row" style={{ marginLeft: 'auto' }}>
              {usesRange(loc.pathname) ? <RangePicker /> : null}
              {(<Button variant="ghost" icon="tasks" onClick={() => setTasksOpen(true)} aria-label={`My tasks (${tasks.data?.length ?? 0})`}>
                  <span className="hide-sm">Tasks</span>
                  {tasks.data?.length ? <span className="pill accent" style={{ height: 18, padding: '0 6px' }}>{tasks.data.length}</span> : null}
                </Button>)}
            </div>
          </header>
          <main className="content" id="main" tabIndex={-1}>
            {loc.pathname !== '/' ? <div className="page-back"><BackButton /></div> : null}
            {moduleOf(loc.pathname) === 'seo' && !IS_DEMO ? <ClaudeBudgetBanner pathname={loc.pathname}/> : null}
            {children}
          </main>
        </div>
      </div>
      {tasksOpen ? <TasksDrawer tasks={tasks.data ?? []} loading={tasks.loading} onClose={() => setTasksOpen(false)}/> : null}
    </>);
}
/** On SEO & Blog pages: a warning when today's Claude limit or the month's budget is nearly used. Re-read on each page. */
function ClaudeBudgetBanner({ pathname }) {
    const b = useApi('/ai/budget');
    const { reload } = b;
    useEffect(() => { reload(); }, [pathname, reload]);
    return b.data?.warning ? <div className="mb-12"><BudgetWarning budget={b.data}/></div> : null;
}
/** Goes back one page; when this tab has no earlier page (opened directly), goes to the parent section or Home. */
function BackButton() {
    const router = useRouter();
    const pathname = usePathname() ?? '/';
    const back = () => {
        if (window.history.length > 1)
            router.back();
        else
            router.push(parentOf(pathname));
    };
    return <Button variant="ghost" size="sm" icon="chevronLeft" onClick={back} aria-label="Go back" title="Back to the previous page">Back</Button>;
}
/** A SEO & Blog entry that expands to its pages. It opens by itself when one of its pages is open and closes in other modules. */
function ModuleNav({ entry, can, count, alert }) {
    const pathname = usePathname() ?? '/';
    const here = moduleOf(pathname) === entry.id;
    const [open, setOpen] = useState(here);
    useEffect(() => { setOpen(here); }, [here]);
    const items = entry.items.filter((i) => !i.perm || can(i.perm));
    const listId = `nav-${entry.id}`;
    return (<div className="nav-module">
      <button type="button" className={`nav-item nav-parent ${here ? 'parent-active' : ''}`} aria-expanded={open} aria-controls={listId} onClick={() => setOpen((o) => !o)}>
        <Icon name={entry.icon}/>
        {entry.label}
        {!open && count ? <span className={`count ${alert ? 'alert' : ''}`} aria-label={`${count} publishing items need attention`}>{count}</span> : null}
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size="sm" className="nav-chevron"/>
      </button>
      {open ? (<ul id={listId} className="nav-sub">
          {items.map((i) => (<li key={i.to}><NavItem to={i.to} icon={i.icon} count={i.badge === 'publishing' ? count : 0} alert={alert}>{i.label}</NavItem></li>))}
        </ul>) : null}
    </div>);
}
/** Settings replaces the module list with its own pages and a way back. */
function SettingsNav({ can }) {
    return (<nav aria-label="Settings">
      <Link href="/" className="nav-item nav-back"><Icon name="chevronLeft"/>Back to Flowmerce</Link>
      <div className="nav-label nav-settings-label"><Icon name={SETTINGS.icon} size="sm"/>{SETTINGS.label}</div>
      <ul className="nav-sub flat">
        {SETTINGS.items.filter((i) => !i.perm || can(i.perm)).map((i) => (<li key={i.to}><NavItem to={i.to} icon={i.icon}>{i.label}</NavItem></li>))}
      </ul>
    </nav>);
}
function NavItem({ to, icon, children, count, alert, end, active: forced }) {
    const pathname = usePathname() ?? '/';
    const active = forced ?? pathMatches(pathname, to, end);
    return (<Link href={to} className={`nav-item ${active ? 'active' : ''}`} aria-current={active ? 'page' : undefined}>
      {icon ? <Icon name={icon}/> : null}
      {children}
      {count ? <span className={`count ${alert ? 'alert' : ''}`}>{count}</span> : null}
    </Link>);
}
function BrandSwitch() {
    const { brand, setBrand, me } = useApp();
    const opts = [{ key: 'all', label: 'All' }, ...me.brands.map((b) => ({ key: b.id, label: b.short }))];
    return (<div className="seg" role="group" aria-label="Brand">
      {opts.map((o) => (<button key={o.key} aria-pressed={brand === o.key} onClick={() => setBrand(o.key)}>
          {o.key !== 'all' ? <span className={`brand-dot ${o.key}`}/> : null}
          {o.label}
        </button>))}
    </div>);
}
function RangePicker() {
    const { range, setRange } = useApp();
    const [custom, setCustom] = useState(false);
    const presets = [['7d', 'Last 7 days'], ['28d', 'Last 28 days'], ['3m', 'Last 3 months'], ['6m', 'Last 6 months'], ['12m', 'Last 12 months']];
    const label = range.preset === 'custom' ? `${fmtDate(range.from, { day: 'numeric', month: 'short' })} – ${fmtDate(range.to, { day: 'numeric', month: 'short' })}` : presets.find((p) => p[0] === range.preset)?.[1] ?? 'Range';
    return (<>
      <Menu trigger={(toggle) => (<Button variant="secondary" size="sm" icon="calendar" onClick={toggle} title={`${range.from} to ${range.to} (Search Console data is final ~3 days after the day)`}>
          <span className="hide-sm">{label}</span>
        </Button>)}>
        {(close) => (<>
            {presets.map(([k, l]) => (<button key={k} className="menu-item" onClick={() => { setRange(presetRange(k)); close(); }}>
                {range.preset === k ? <Icon name="check" size="sm"/> : <span style={{ width: 14 }}/>}{l}
              </button>))}
            <div className="menu-sep"/>
            <button className="menu-item" onClick={() => { setCustom(true); close(); }}><Icon name="calendar" size="sm"/>Custom range…</button>
            <div className="muted xs" style={{ padding: '6px 10px', maxWidth: 220 }}>Ranges end 3 days ago, when Search Console data is final.</div>
          </>)}
      </Menu>
      {custom ? <CustomRange onClose={() => setCustom(false)}/> : null}
    </>);
}
function CustomRange({ onClose }) {
    const { range, setRange } = useApp();
    const [from, setFrom] = useState(range.from);
    const [to, setTo] = useState(range.to);
    const bad = !from || !to || from > to;
    return (<Dialog title="Custom date range" onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={bad} onClick={() => { setRange({ from, to, preset: 'custom' }); onClose(); }}>Apply</Button></>}>
      <div className="form-grid">
        <div className="field"><label htmlFor="rf">From</label><input id="rf" type="date" className="input" value={from} max={to} onChange={(e) => setFrom(e.target.value)}/></div>
        <div className="field"><label htmlFor="rt">To</label><input id="rt" type="date" className="input" value={to} min={from} onChange={(e) => setTo(e.target.value)}/></div>
      </div>
      {bad ? <p className="small" style={{ color: 'var(--crit)' }}>The start date must be on or before the end date.</p> : null}
    </Dialog>);
}
function GlobalSearch() {
    const [q, setQ] = useState('');
    const [open, setOpen] = useState(false);
    const [active, setActive] = useState(0);
    const [hits, setHits] = useState([]);
    const nav = useNavigate();
    const box = useRef(null);
    const input = useRef(null);
    useEffect(() => {
        const onKey = (e) => {
            if ((e.key === 'k' && (e.metaKey || e.ctrlKey)) || (e.key === '/' && !e.target.closest('input,textarea,[contenteditable="true"]'))) {
                e.preventDefault();
                input.current?.focus();
            }
        };
        const onDoc = (e) => { if (box.current && !box.current.contains(e.target))
            setOpen(false); };
        document.addEventListener('keydown', onKey);
        document.addEventListener('mousedown', onDoc);
        return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDoc); };
    }, []);
    useEffect(() => {
        if (q.trim().length < 2) {
            setHits([]);
            return;
        }
        const ctl = new AbortController();
        const t = setTimeout(async () => {
            try {
                const [a, t2] = await Promise.all([
                    api.get(`/articles${qs({ q, limit: 6 })}`, ctl.signal),
                    api.get(`/topics${qs({ q })}`, ctl.signal),
                ]);
                setHits([
                    ...a.rows.map((r) => ({ type: 'Article', id: r.id, title: r.title, sub: r.primary_keyword || r.handle, brand: r.brand_id, to: `/articles/${r.id}` })),
                    ...t2.slice(0, 5).map((r) => ({ type: 'Topic', id: r.id, title: r.title, sub: r.primary_keyword, brand: r.brand_id, to: `/topics?focus=${r.id}` })),
                ]);
                setActive(0);
            }
            catch { /* ignore aborted */ }
        }, 180);
        return () => { clearTimeout(t); ctl.abort(); };
    }, [q]);
    const go = (to) => { setOpen(false); setQ(''); nav(to); };
    return (<div className="search hide-sm" ref={box}>
      <div className="input-icon">
        <Icon name="search"/>
        <input ref={input} className="input sm" placeholder="Search articles and topics" value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, hits.length - 1));
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
            }
            if (e.key === 'Enter' && hits[active])
                go(hits[active].to);
            if (e.key === 'Escape') {
                setOpen(false);
                e.target.blur();
            }
        }} aria-label="Search articles and topics" role="combobox" aria-expanded={open && hits.length > 0}/>
        <span className="kbd" style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)' }}>/</span>
      </div>
      {open && q.trim().length >= 2 ? (<div className="search-results" role="listbox">
          {hits.length ? hits.map((h, i) => (<a key={h.type + h.id} className={`search-hit ${i === active ? 'active' : ''}`} href={h.to} onClick={(e) => { e.preventDefault(); go(h.to); }} role="option" aria-selected={i === active}>
              <Icon name={h.type === 'Article' ? 'blogs' : 'topics'}/>
              <span style={{ minWidth: 0, flex: 1 }}>
                <span className="ellipsis strong" style={{ display: 'block' }}>{h.title}</span>
                <span className="ellipsis muted small" style={{ display: 'block' }}>{h.type} · {h.sub}</span>
              </span>
              <span className={`brand-dot ${h.brand}`}/>
            </a>)) : <div className="muted small" style={{ padding: 10 }}>No matches for “{q}”.</div>}
        </div>) : null}
    </div>);
}
/**
 * Local operator mode: there is no account menu, password change or sign-out. This only states the mode and who
 * actions are recorded as; it is not a control.
 */
/** Hosted copy: the signed-in username from the readable fm_hosted cookie the sign-in sets (null on your own computer). */
function useHostedUser() {
    const [user, setUser] = useState(null);
    useEffect(() => {
        const m = document.cookie.match(/(?:^|;\s*)fm_hosted=([^;]*)/);
        setUser(m ? decodeURIComponent(m[1]) : null);
    }, []);
    return user;
}
function LocalOperatorBadge() {
    const { me } = useApp();
    const hostedUser = useHostedUser();
    if (hostedUser) {
        return (<Menu up align="left" trigger={(toggle) => (<button type="button" className="user-chip" onClick={toggle} aria-label={`Signed in as ${hostedUser}. Account menu`}>
          <span className="avatar">{hostedUser.slice(0, 2).toUpperCase()}</span>
          <span style={{ minWidth: 0, flex: 1 }}>
            <span className="strong small" style={{ display: 'block' }}>Signed in as {hostedUser}</span>
            <span className="muted xs" style={{ display: 'block' }}>Online workspace</span>
          </span>
          <Icon name="chevronDown" size="sm"/>
        </button>)}>
          {() => (<a className="menu-item" href="/auth/logout"><Icon name="logout"/>Sign out</a>)}
        </Menu>);
    }
    return (<div className="user-chip" role="status" style={{ cursor: 'default', background: 'none' }} title={`Local operator mode: no sign-in, this computer only. Actions are recorded as ${me.user.name} (${me.user.email}).`}>
      <span className="avatar"><Icon name="shield" size="sm"/></span>
      <span style={{ minWidth: 0, flex: 1 }}>
        <span className="strong small" style={{ display: 'block' }}>Local operator mode</span>
        <span className="muted xs" style={{ display: 'block' }}>This computer only · no sign-in</span>
      </span>
    </div>);
}
/** Demo only: act as a different role to see who can approve what. Changes permissions in this browser, nothing else. */
const DEMO_ROLES = [['admin', 'Admin', 'Everything, including settings'], ['seo_manager', 'SEO Manager', 'Writes, runs automation, requests publishing'], ['reviewer', 'Reviewer / Approver', 'Reviews content and authorizes publishing']];
function DemoUserChip() {
    const { me, refreshMe } = useApp();
    const switchRole = async (role, close) => {
        close();
        await api.post('/demo/role', { role });
        await refreshMe();
    };
    return (<Menu up align="left" trigger={(toggle) => (<button type="button" className="user-chip" onClick={toggle} aria-label={`Viewing the demo as ${me.user.roleLabel}. Change role`}>
        <span className="avatar">{me.user.name.split(' ').map((w) => w[0]).join('').slice(0, 2)}</span>
        <span style={{ minWidth: 0, flex: 1 }}>
          <span className="strong small" style={{ display: 'block' }}>{me.user.name}</span>
          <span className="muted xs" style={{ display: 'block' }}>{me.user.roleLabel} · demo role</span>
        </span>
        <Icon name="chevronDown" size="sm"/>
      </button>)}>
      {(close) => (<>
        <div className="muted xs" style={{ padding: '6px 10px', maxWidth: 240 }}>View the demo as another role. Permissions change in this browser only.</div>
        {DEMO_ROLES.map(([k, l, d]) => (<button key={k} className="menu-item" style={{ alignItems: 'flex-start' }} onClick={() => switchRole(k, close)}>
          {me.user.role === k ? <Icon name="check" size="sm"/> : <span style={{ width: 14 }}/>}
          <span><span className="strong" style={{ display: 'block' }}>{l}</span><span className="muted xs">{d}</span></span>
        </button>))}
      </>)}
    </Menu>);
}
function TasksDrawer({ tasks, loading, onClose }) {
    const nav = useNavigate();
    const { me } = useApp();
    return (<Drawer title={`My tasks · ${tasks.length}`} onClose={onClose}>
      {loading && !tasks.length ? <div style={{ padding: 18 }} className="muted">Loading…</div> : null}
      {!loading && !tasks.length ? (<div className="empty"><Icon name="checkCircle"/><h3>Nothing waiting on you</h3><p>Reviews, publish approvals and returned drafts for your role ({me.user.roleLabel}) will appear here.</p></div>) : null}
      <div className="alert-list">
        {tasks.map((t, i) => (<a key={i} className="alert-item" href={t.link} onClick={(e) => { e.preventDefault(); onClose(); nav(t.link); }}>
            <Icon name={t.kind === 'review' ? 'eye' : t.kind === 'authorize' ? 'shield' : t.kind === 'failed' ? 'alert' : t.kind === 'topic' ? 'topics' : 'edit'}/>
            <span style={{ minWidth: 0, flex: 1 }}>
              <span className="strong small" style={{ display: 'block' }}>{t.action}</span>
              <span className="ellipsis small" style={{ display: 'block' }}>{t.title}</span>
              <span className="muted xs">waiting {timeAgo(t.since).replace(' ago', '')}</span>
            </span>
            <BrandTag id={t.brand} brands={me.brands}/>
          </a>))}
      </div>
    </Drawer>);
}
