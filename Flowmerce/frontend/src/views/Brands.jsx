'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api, useApi } from '../lib/api';
import { useApp } from '../lib/app';
import { Button, Card, ErrorState, Field, Kv, LoadingBlock, PageHead, Pill } from '../components/ui';
import { useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
import { STATE } from './Integrations';
import { IS_DEMO } from '../demo';

const CONNECTIONS = [
    { key: 'shopify', label: 'Shopify Admin API', what: 'drafts, SEO fields, publishing' },
    { key: 'shopify_public', label: 'Shopify public feed', what: 'live articles and products, read-only' },
    { key: 'gsc', label: 'Search Console', what: 'search clicks and queries' },
    { key: 'ga4', label: 'GA4', what: 'sessions on blog pages' },
];

/** Settings > Brands: each brand's store details, how it connects, and the guidance Claude follows when it writes for it. */
export default function Brands() {
    const { me } = useApp();
    const integrations = useApi('/integrations');
    return (<>
      <PageHead title="Brands" sub="Store details, connections and voice."/>
      <ErrorState error={integrations.error} onRetry={integrations.reload}/>
      <div className="col" style={{ gap: 24 }}>
        {me.brands.map((b) => (<BrandBlock key={b.id} brand={b} items={integrations.data?.items.filter((i) => i.brand === b.id)} loading={integrations.loading && !integrations.data} failed={!!integrations.error && !integrations.data}/>))}
      </div>
    </>);
}

function BrandBlock({ brand: b, items, loading, failed }) {
    return (<section className="col" style={{ gap: 12 }} aria-label={b.name}>
      <h2 className="row" style={{ fontSize: 20, margin: 0 }}><span className={`brand-dot ${b.id}`}/>{b.name}</h2>
      <div className="grid cols-2">
        <Card title="Store">
          <Kv items={[
            ['Storefront', <a href={b.storefrontUrl} target="_blank" rel="noopener">{b.storefrontUrl.replace('https://', '')} <Icon name="external" size="sm"/></a>],
            ['Shopify store', <span className="mono">{b.shopDomain}</span>],
            ['Blog', <a href={b.blogUrl} target="_blank" rel="noopener">/blogs/{b.blogHandle} <Icon name="external" size="sm"/></a>],
            ['Search Console property', <span className="mono">{b.gscProperty || '—'}</span>],
        ]}/>
        </Card>
        <Card title="Connections" sub={IS_DEMO ? 'Demo build: simulated, nothing is connected. Manage them under Integrations.' : 'Manage them under Integrations.'} actions={<Link className="btn ghost xs" href="/settings/integrations">Integrations</Link>}>
          {loading ? <LoadingBlock rows={3}/> : failed ? <div className="muted small">Connection status could not be loaded.</div> : (<div className="col gap-8">
              {CONNECTIONS.map((c) => {
                const i = items?.find((x) => x.key === c.key);
                const st = i ? (STATE[i.state] ?? { label: i.state, tone: 'neutral' }) : null;
                return (<div key={c.key} className="row" style={{ alignItems: 'flex-start' }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="small strong">{c.label}</div>
                    <div className="muted xs">{i?.paused ? i.pausedReason : c.what}</div>
                  </div>
                  {st ? <Pill tone={st.tone}>{st.label}</Pill> : <Pill tone="neutral">Unknown</Pill>}
                </div>);
            })}
            </div>)}
        </Card>
      </div>
      <BrandSettings id={b.id}/>
    </section>);
}

function BrandSettings({ id }) {
    const { brandOf, can, refreshMe } = useApp();
    const s = brandOf(id).settings;
    const knowledge = brandOf(id).knowledge;
    const [f, setF] = useState(s);
    const [busy, setBusy] = useState(false);
    const toast = useToast();
    useEffect(() => setF(s), [s]);
    const ro = !can('integrations:manage');
    const dirty = JSON.stringify(f) !== JSON.stringify(s);
    const save = async () => {
        setBusy(true);
        try {
            await api.patch(`/brands/${id}`, f);
            toast.ok('Brand settings saved.');
            refreshMe();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    return (<Card title="Voice and automation" sub={ro ? 'Only admins can change these.' : 'Used by Claude for topic research and drafts.'} actions={!ro ? <Button variant="primary" size="sm" disabled={!dirty} loading={busy} onClick={save}>Save settings</Button> : null}>
      <div className="form-grid">
        <Field label="Brand voice" full><textarea className="textarea" rows={2} value={f.voice} readOnly={ro} onChange={(e) => setF({ ...f, voice: e.target.value })}/></Field>
        <Field label="Audience"><textarea className="textarea" rows={2} value={f.audience} readOnly={ro} onChange={(e) => setF({ ...f, audience: e.target.value })}/></Field>
        <Field label="Never write"><textarea className="textarea" rows={2} value={f.avoid} readOnly={ro} onChange={(e) => setF({ ...f, avoid: e.target.value })}/></Field>
        <Field label="Research focus" full><input className="input" value={f.researchFocus} readOnly={ro} onChange={(e) => setF({ ...f, researchFocus: e.target.value })}/></Field>
        <Field label="Standing instructions for Claude" full hint="Sent with every Claude request for this brand (topics, drafts, revisions, automatic blogs), after its brand documents. They win where they conflict, but Claude still never invents facts.">
          <textarea className="textarea" rows={4} value={f.claudeInstructions ?? ''} readOnly={ro} placeholder="e.g. Always link the tablecloth size finder. Never mention delivery times."
            onChange={(e) => setF({ ...f, claudeInstructions: e.target.value })}/>
        </Field>
        {knowledge?.length ? <div className="field full small muted">Brand documents Claude reads: {knowledge.map((k) => k.name).join(', ')}</div> : null}
        <Field label="Default author"><input className="input" value={f.defaultAuthor} readOnly={ro} onChange={(e) => setF({ ...f, defaultAuthor: e.target.value })}/></Field>
        <div className="row gap-12">
          <Field label="Topics per research run"><input className="input" type="number" min={1} max={15} value={f.topicsPerRun} readOnly={ro} onChange={(e) => setF({ ...f, topicsPerRun: Number(e.target.value) })}/></Field>
          <Field label="Drafts per generation run"><input className="input" type="number" min={1} max={5} value={f.draftsPerRun} readOnly={ro} onChange={(e) => setF({ ...f, draftsPerRun: Number(e.target.value) })}/></Field>
        </div>
      </div>
    </Card>);
}
