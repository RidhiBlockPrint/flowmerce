'use client';
import { Fragment, useEffect, useState } from 'react';
import { api, qs, download } from '../lib/api';
import { useApp, useBrandParam } from '../lib/app';
import { fmtDateTime } from '../lib/format';
import { Button, Empty, ErrorState, LoadingBlock, PageHead, BrandTag, Paged } from '../components/ui';
import { useToast } from '../components/overlays';
import { Icon } from '../components/Icon';
const GROUPS = [['', 'All actions'], ['article', 'Content edits & reviews'], ['publish', 'Publishing'], ['shopify', 'Shopify drafts'], ['data', 'Imports & exports'], ['integration', 'Integration failures & tests'], ['workflow', 'Automation'], ['auth', 'Sign-ins'], ['user', 'Users']];
export default function Audit() {
    const brand = useBrandParam();
    const { me, range } = useApp();
    const toast = useToast();
    const [action, setAction] = useState('');
    const [user, setUser] = useState('');
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [more, setMore] = useState(true);
    const [open, setOpen] = useState(null);
    const load = async (before) => {
        setLoading(true);
        setError(null);
        try {
            const r = await api.get(`/audit${qs({ brand, action, user, before })}`);
            setRows((prev) => (before ? [...prev, ...r] : r));
            setMore(r.length === 100);
        }
        catch (e) {
            setError(e);
        }
        finally {
            setLoading(false);
        }
    };
    useEffect(() => { const t = setTimeout(() => void load(), 200); return () => clearTimeout(t); }, [brand, action, user]); // eslint-disable-line react-hooks/exhaustive-deps
    return (<>
      <PageHead title="Audit log" sub="Every edit, approval and publish, in order." actions={<Button icon="download" onClick={() => download(`/data/export/audit${qs({ brand, from: range.from, to: range.to })}`).catch(toast.error)}>Export range</Button>}/>
      <div className="toolbar">
        <select className="select sm" style={{ width: 'auto' }} value={action} onChange={(e) => setAction(e.target.value)} aria-label="Action">{GROUPS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <div className="input-icon" style={{ width: 220 }}><Icon name="search"/><input className="input sm" placeholder="Filter by user email" value={user} onChange={(e) => setUser(e.target.value)}/></div>
      </div>
      <ErrorState error={error} onRetry={() => load()}/>
      {error && rows.length ? <div className="muted small mb-8">The list below is from the last successful load and may be out of date.</div> : null}
      <div className="card flush">
        {loading && !rows.length ? <div className="card-body"><LoadingBlock rows={5}/></div> : null}
        <Paged rows={rows} resetKey={`${brand}|${action}|${user}`}>{(pageRows) => (<>
<div className="table-wrap">
          <table className="t compact">
            <thead><tr><th>Time</th><th>Who</th><th>Action</th>{!brand ? <th className="hide-sm">Brand</th> : null}<th>Summary</th><th /></tr></thead>
            <tbody>
              {pageRows.map((r) => (<Fragment key={r.id}>
                  <tr className="clickable" onClick={() => setOpen(open === r.id ? null : r.id)}>
                    <td className="nowrap small">{fmtDateTime(r.ts)}</td>
                    <td className="small">{r.user_email ?? 'system'}</td>
                    <td><span className={`pill ${r.action.includes('fail') ? 'crit' : r.action.startsWith('publish') ? 'accent' : 'neutral'}`}>{r.action}</span></td>
                    {!brand ? <td className="hide-sm">{r.brand_id ? <BrandTag id={r.brand_id} brands={me.brands}/> : null}</td> : null}
                    <td className="small" style={{ maxWidth: 480, overflowWrap: 'anywhere' }}>{r.summary || <span className="faint">{r.entity_type} {r.entity_id}</span>}</td>
                    <td><Icon name={open === r.id ? 'chevronDown' : 'chevronRight'} size="sm"/></td>
                  </tr>
                  {open === r.id ? (<tr><td colSpan={6} style={{ background: 'var(--surface-2)' }}>
                      <div className="code-block">{JSON.stringify({ entity: `${r.entity_type} ${r.entity_id}`.trim(), ip: r.ip, ...r.details }, null, 2)}</div>
                    </td></tr>) : null}
                </Fragment>))}
            </tbody>
          </table>
        </div>
</>)}</Paged>
        {!loading && !error && !rows.length ? <Empty icon="audit" title="No entries match">Nothing has been recorded for these filters. Try another action type or user.</Empty> : null}
        {more && rows.length ? <div className="card-foot"><Button size="sm" loading={loading} onClick={() => load(rows[rows.length - 1].id)}>Load older entries</Button></div> : null}
      </div>
    </>);
}
