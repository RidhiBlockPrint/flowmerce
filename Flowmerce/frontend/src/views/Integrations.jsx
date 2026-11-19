'use client';
import { useState } from 'react';
import { api, useApi } from '../lib/api';
import { useApp, useBrandParam } from '../lib/app';
import { fmtDateTime, timeAgo } from '../lib/format';
import { testText } from '../lib/shipping';
import { Button, Card, ErrorState, Kv, LoadingBlock, PageHead, Pill } from '../components/ui';
import { useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
export const STATE = {
    connected: { label: 'Connected', tone: 'ok' }, error: { label: 'Failing', tone: 'crit' }, pending_setup: { label: 'Pending setup', tone: 'warn' },
    not_configured: { label: 'Not configured', tone: 'warn' }, connection_failed: { label: 'Connection failed', tone: 'crit' }, permission_denied: { label: 'Permission denied', tone: 'crit' },
    schema_mismatch: { label: 'Schema mismatch', tone: 'crit' }, not_tested: { label: 'Configured · not tested yet', tone: 'info' },
    demo_simulated: { label: 'Demo — simulated', tone: 'info' }, not_connected: { label: 'Not connected', tone: 'neutral' }, planned: { label: 'Planned — not built', tone: 'outline' },
    syncing: { label: 'Syncing', tone: 'info' }, not_synced: { label: 'Configured · not synced yet', tone: 'info' }, standby: { label: 'Standby', tone: 'neutral' }, paused: { label: 'Paused', tone: 'neutral' },
};
const ICON = { shopify: 'store', shopify_public: 'store', gsc: 'google', ga4: 'analytics', claude: 'sparkle', workflow_webhook: 'link', ai_execution: 'automation' };
export default function Integrations() {
    const q = useApi('/integrations');
    const brand = useBrandParam();
    const { can, brandOf } = useApp();
    const toast = useToast();
    const [busy, setBusy] = useState(null);
    const [results, setResults] = useState({});
    const test = async (i) => {
        const k = i.key + i.brand;
        setBusy('t' + k);
        try {
            const r = await api.post('/integrations/test', { key: i.key, brand: i.brand || undefined });
            setResults((m) => ({ ...m, [k]: { ok: r.ok, simulated: !!r.simulated, text: r.simulated ? r.message : i.key === 'shipping_supabase' ? testText(r.result, r.error) : r.ok ? `OK — ${JSON.stringify(r.result).replace(/[{}"]/g, '').replace(/,/g, ', ').replace(/:/g, ': ')}` : r.error } }));
        }
        catch (e) {
            setResults((m) => ({ ...m, [k]: { ok: false, text: e.message } }));
        }
        finally {
            setBusy(null);
            q.reload();
        }
    };
    const sync = async (i) => {
        const k = i.key + i.brand;
        setBusy('s' + k);
        try {
            await api.post('/analytics/sync', { brand: i.brand, source: i.key === 'shopify_public' ? 'shopify' : i.key });
            toast.ok(q.data?.demo ? 'Simulated sync finished (sample data only, nothing was fetched).' : 'Synced.');
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(null);
            q.reload();
        }
    };
    const items = (q.data?.items ?? []).filter((i) => !brand || !i.brand || i.brand === brand);
    return (<>
      <PageHead title="Integrations" sub={q.data?.demo ? 'Demo: nothing is connected.' : 'Connection status and setup.'}/>
      <ErrorState error={q.error} onRetry={q.reload}/>
      {q.loading && !q.data ? <LoadingBlock rows={6}/> : null}
      {q.data ? (<>
          {q.data.demo ? <div className="callout demo mb-16"><Icon name="info"/><div><b>Demo — nothing is connected.</b> Statuses read &quot;Demo — simulated&quot; or &quot;Not connected&quot;. &quot;Test connection&quot; and &quot;Sync now&quot; only run a labelled simulation in your browser. Live publishing is off.</div></div> : <div className="callout info mb-16"><Icon name="shield"/><div>Shopify Admin API version <span className="mono">{q.data.shopifyApiVersion}</span>. Live publishing on this server: <b>{q.data.livePublishing ? 'enabled' : 'disabled'}</b> (ALLOW_LIVE_PUBLISH).</div></div>}
          <div className="grid cols-2">
            {items.map((i) => {
                const k = i.key + i.brand;
                const st = STATE[i.state] ?? { label: i.state, tone: 'neutral' };
                const paused = i.state === 'paused';
                const syncable = i.brand && ['shopify', 'shopify_public', 'gsc', 'ga4'].includes(i.key) && i.configured && i.state !== 'standby' && !paused;
                const testable = i.testable ?? i.configured;
                return (<section key={k} className="card">
                  <div className="card-head">
                    <Icon name={ICON[i.key] ?? 'plug'}/>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <h2 className="card-title">{i.label}</h2>
                      {i.brand ? <div className="card-sub row"><span className={`brand-dot ${i.brand}`}/>{brandOf(i.brand).name}</div> : <div className="card-sub">All brands</div>}
                    </div>
                    <Pill tone={st.tone} dot>{st.label}</Pill>
                  </div>
                  <div className="card-body col gap-12">
                    <div className="small">{i.provides}</div>
                    <Kv items={[
                        ['Last success', i.status?.last_success_at ? <span title={fmtDateTime(i.status.last_success_at)}>{timeAgo(i.status.last_success_at)}</span> : <span className="faint">never</span>],
                        ['Last attempt', i.status?.last_attempt_at ? timeAgo(i.status.last_attempt_at) : <span className="faint">never</span>],
                        ...(i.status?.details && Object.keys(i.status.details).length && i.state !== 'pending_setup' ? [['Last result', <span className="mono">{Object.entries(i.status.details).map(([a, b]) => `${a}: ${b}`).join(' · ')}</span>]] : []),
                    ]}/>
                    {paused ? <div className="callout info"><Icon name="pause"/><div><b>Paused — outside current integration scope.</b> No requests are sent, nothing is recorded as a failure, and the configuration and stored data are kept. {i.status?.last_error ? 'An older failed attempt stays in this integration\'s history. ' : ''}It can be reactivated later by removing it from PAUSED_INTEGRATIONS on the server.</div></div> : null}
                    {['error', 'connection_failed', 'permission_denied', 'schema_mismatch'].includes(i.state) && i.status?.last_error ? <div className="callout crit"><Icon name="alert"/><div style={{ overflowWrap: 'anywhere' }}>{i.status.last_error}</div></div> : null}
                    {paused ? null : i.state === 'pending_setup' || !i.configured || i.state === 'not_connected' ? <div className="callout warn"><Icon name="key"/><div><b>Setup:</b> {i.setup}</div></div> : <details className="small"><summary className="muted" style={{ cursor: 'pointer' }}>Setup details</summary><p className="mt-8">{i.setup}</p></details>}
                    {results[k] ? <div className={`callout ${results[k].simulated ? 'info' : results[k].ok ? 'ok' : 'crit'}`}><Icon name={results[k].simulated ? 'info' : results[k].ok ? 'checkCircle' : 'alert'}/><div style={{ overflowWrap: 'anywhere' }}>{results[k].text}</div></div> : null}
                  </div>
                  {(can('integrations:manage') && testable && !paused && i.key !== 'workflow_webhook' && i.key !== 'ai_execution') || (can('analytics:sync') && syncable) ? (<div className="card-foot">
                      {can('integrations:manage') && testable && !paused && i.key !== 'workflow_webhook' && i.key !== 'ai_execution' ? <Button size="sm" icon="plug" loading={busy === 't' + k} onClick={() => test(i)}>{q.data?.demo ? 'Test connection (simulated)' : 'Test connection'}</Button> : null}
                      {can('analytics:sync') && syncable ? <Button size="sm" icon="refresh" loading={busy === 's' + k} onClick={() => sync(i)}>{q.data?.demo ? 'Sync now (simulated)' : 'Sync now'}</Button> : null}
                    </div>) : null}
                </section>);
            })}
          </div>
          {q.data.planned?.length ? (<Card title="Planned capabilities" sub="Not built yet. These are not part of the demo workflows above and nothing here works today." className="mt-16">
            <div className="grid cols-3">
              {q.data.planned.map((p) => (<div key={p.key} className="stage" style={{ gap: 6 }}>
                  <div className="row"><Icon name="plug"/><span className="strong" style={{ flex: 1 }}>{p.label}</span><Pill tone="outline">Planned — not built</Pill></div>
                  <div className="muted small">{p.description}</div>
                </div>))}
            </div>
          </Card>) : null}
          <Card title={q.data.demo ? 'Where each metric will come from in a live build' : 'Where each metric comes from'} className="mt-16" flush>
            <div className="table-wrap">
              <table className="t compact">
                <thead><tr><th>Metric</th><th>Source</th><th>Access needed</th><th className="hide-md">If unavailable</th></tr></thead>
                <tbody>
                  {[
                ['Articles, drafts, SEO fields, publish state', 'Shopify Admin GraphQL (articles, blogs)', 'Custom app token: read_content, write_content', 'Public feed (live articles only) · Excel blog records'],
                ['Products & images for links and featured images', 'Shopify Admin (products) or storefront /products.json', 'read_products, or none for public', '—'],
                ['Clicks, impressions, CTR, position, queries', 'Search Console Search Analytics API', 'Service account added to the property', 'Excel import of Search Console exports'],
                ['Sessions, engagement, key events (conversions)', 'GA4 Data API runReport (landingPage)', 'Service account with Viewer on the property', 'Excel import of GA4 Explore exports'],
                ['Keyword volume & difficulty', 'Not available from Google APIs without Ads', '—', 'Excel import from Semrush / Ahrefs / Keyword Planner'],
                ['Topic ideas, first drafts', 'Claude Messages API (this server)', 'ANTHROPIC_API_KEY', 'Write manually'],
                ['Status and results of AI jobs', 'Claude API on this server, or an AI worker that reports to /api/hooks/workflow', 'AI_EXECUTION_MODE, plus ANTHROPIC_API_KEY or AI_WORKER_URL and AI_WORKER_TOKEN', 'Run the stage from Automation'],
                ['Shopify store analytics (sales, sessions)', 'Not used: blog attribution comes from GA4', '—', '—'],
            ].map((r) => <tr key={r[0]}><td className="strong small">{r[0]}</td><td className="small">{r[1]}</td><td className="small">{r[2]}</td><td className="small hide-md muted">{r[3]}</td></tr>)}
                </tbody>
              </table>
            </div>
          </Card>
        </>) : null}
    </>);
}
