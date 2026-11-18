'use client';
import { useState } from 'react';
import { Button } from './ui';
import { Icon } from './Icon';
import { Dialog } from './overlays';
import { useToast } from './overlays';
import { resetDemo } from '../demo';

/** What the preview really does today, against what is only planned. Shown from the banner so nobody mistakes the demo for the product. */
const WORKS = [
  ['SEO & Blog', 'Create, edit, review, approve and schedule articles; topic and keyword decisions; publishing approvals; SEO and traffic reports.'],
  ['Automation', 'Run, pause and retry pipeline stages; AI job history, results and controls (simulated worker).'],
  ['Shipping', 'Shipment search, filters, tracking timelines, delay and exception checks, analytics, exports.'],
  ['Settings', 'Brands, integration status screens, data import and export previews, audit log.'],
];
const PLANNED = [
  ['Live Shopify, Google Search Console and GA4 data', 'Needs the connected accounts and the unified PostgreSQL database.'],
  ['Real publishing to the storefront blog', 'Approvals work here, but nothing is sent to Shopify.'],
  ['Real Claude content generation', 'The AI worker bridge exists in the backend; the preview uses a simulated worker.'],
  ['Carrier tracking feeds and customer notifications', 'Shipping shows synthetic shipments; no carrier is contacted.'],
  ['Sign-in, roles and per-person audit trail', 'Roles can be switched in the preview to show who can approve what.'],
];

export function DemoBanner() {
  const [open, setOpen] = useState(false);
  return (<>
    <div className="banner-demo" role="status">
      <span className="demo-tag">DEMO / PREVIEW</span>
      <span className="demo-text">Synthetic sample data in this browser only. Nothing is connected: no Shopify, Google, Supabase or carrier requests, no real publishing or email.</span>
      <button type="button" className="demo-link" onClick={() => setOpen(true)}>What works today?</button>
    </div>
    {open ? <AboutDialog onClose={() => setOpen(false)} /> : null}
  </>);
}

function AboutDialog({ onClose }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const reset = () => {
    resetDemo();
    toast.ok('Demo reset to the original sample data.');
    onClose();
    window.setTimeout(() => window.location.reload(), 250);
  };
  return (<Dialog wide title="About this preview" sub="A clickable demonstration of Flowmerce for the management team" onClose={onClose}
    footer={<>
      {confirming
        ? <><span className="muted small" style={{ marginRight: 'auto' }}>Discard every change made in this browser?</span><Button variant="ghost" onClick={() => setConfirming(false)}>Keep my changes</Button><Button variant="danger" icon="refresh" onClick={reset}>Reset demo</Button></>
        : <><Button variant="ghost" icon="refresh" onClick={() => setConfirming(true)} style={{ marginRight: 'auto' }}>Reset demo data</Button><Button variant="primary" onClick={onClose}>Close</Button></>}
    </>}>
    <div className="col gap-16">
      <div className="callout demo"><Icon name="info" /><div>All articles, topics, shipments, figures and people here are made up. Changes you make (approving, scheduling, flagging) are kept only in this browser and can be reset.</div></div>
      <section>
        <h3 className="section-title" style={{ marginTop: 0 }}>Working in this demonstration</h3>
        <ul className="about-list">{WORKS.map(([t, d]) => <li key={t}><Icon name="checkCircle" /><span><b>{t}</b> {d}</span></li>)}</ul>
      </section>
      <section>
        <h3 className="section-title" style={{ marginTop: 0 }}>Planned, not built yet</h3>
        <ul className="about-list planned">{PLANNED.map(([t, d]) => <li key={t}><Icon name="clock" /><span><b>{t}</b> {d}</span></li>)}</ul>
      </section>
    </div>
  </Dialog>);
}
