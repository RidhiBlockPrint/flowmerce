'use client';
import { useState } from 'react';
import { api } from '../lib/api';
import { useApp } from '../lib/app';
import { fmtZoned } from '../lib/format';
import { ConfirmDialog, Dialog, useToast } from './overlays';
import { Button, Field, Kv } from './ui';
import { Icon } from './Icon';
export const MODE_LABEL = { publish_now: 'Publish now', schedule: 'Schedule', update_live: 'Update live article' };

/** `YYYY-MM-DDTHH:mm` in the viewer's local time, for a datetime-local input. */
const localInput = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
/** Tomorrow at 10:00 local time: the default go-live time of a schedule. */
const tomorrowTen = () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(10, 0, 0, 0); return localInput(d); };

/**
 * Schedule (or publish now) one approved blog, from wherever it is shown. Makes the publish request; a person who may
 * authorize their own request (an admin) can authorize it in the same step by typing PUBLISH. Once authorized, a schedule
 * goes to Shopify HIDDEN with the chosen time as its publish date, and Shopify shows it then. Until then the blog stays
 * in Flowmerce.
 */
export function ScheduleBlogDialog({ article, onClose, onDone }) {
    const { me, can, brandOf } = useApp();
    const toast = useToast();
    const brand = brandOf(article.brand_id);
    const [mode, setMode] = useState('schedule');
    const [when, setWhen] = useState(tomorrowTen);
    const [note, setNote] = useState('');
    const [now, setNow] = useState(me.user.role === 'admin' && can('publish:authorize'));
    const [typed, setTyped] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const at = mode === 'schedule' && when ? new Date(when) : null;
    const ok = (mode === 'publish_now' || (at && at.getTime() > Date.now() + 15 * 60_000)) && (!now || typed.trim() === 'PUBLISH');
    const go = async () => {
        setBusy(true);
        setError('');
        let req = null;
        try {
            req = await api.post(`/articles/${article.id}/publish-request`, { mode, publish_at: at ? at.toISOString() : null, note });
            if (!now) {
                toast.ok(mode === 'schedule' ? `Scheduled for ${fmtZoned(at.toISOString())}. A reviewer authorizes it in Publishing; then it goes to Shopify hidden until that time.` : 'Publish request sent to reviewers.');
                onDone();
                return;
            }
            await api.post(`/publish-requests/${req.id}/authorize`, { confirm: 'PUBLISH', note });
            toast.ok(mode === 'schedule' ? `Scheduled: on Shopify hidden, visible from ${fmtZoned(at.toISOString())}.` : 'Published to the storefront.');
            onDone();
        }
        catch (e) {
            // The request may exist even when authorizing failed (e.g. live publishing is off): say so, and refresh.
            setError(req ? `The publish request was made, but authorizing it failed: ${e.message}` : e.message);
            if (req)
                onDone({ keepOpen: true });
        }
        finally {
            setBusy(false);
        }
    };
    return (<Dialog title={`Schedule “${article.title}”`} sub={`${brand.name} · version ${article.version}`} onClose={onClose}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" icon={mode === 'schedule' ? 'calendar' : 'publish'} loading={busy} disabled={!ok} onClick={go}>
          {now ? (mode === 'schedule' ? 'Schedule & authorize' : 'Publish now') : 'Send for authorization'}</Button></>}>
      <div className="col gap-12">
        <div className="seg" role="radiogroup" aria-label="When">
          {['schedule', 'publish_now'].map((m) => <button key={m} role="radio" aria-checked={mode === m} aria-pressed={mode === m} onClick={() => setMode(m)}>{m === 'schedule' ? 'On a date and time' : 'Now'}</button>)}
        </div>
        {mode === 'schedule' ? (<Field label={`Goes live at (your local time, ${fmtZoned(new Date().toISOString()).split(' ').pop()})`} hint="At least 15 minutes from now.">
            <input type="datetime-local" className="input" value={when} min={localInput(new Date(Date.now() + 15 * 60_000))} onChange={(e) => setWhen(e.target.value)}/>
          </Field>) : null}
        <div className="callout info"><Icon name="info"/><div className="small">
          {mode === 'schedule'
              ? <>Until it is authorized the blog stays in Flowmerce. Once authorized, Flowmerce sends it to Shopify <b>hidden</b>, with Shopify set to show it at {at ? <b>{fmtZoned(at.toISOString())}</b> : 'the chosen time'}.</>
              : <>Once authorized, it goes live on {brand.name} straight away.</>}
        </div></div>
        <Field label="Note for the approver"><input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional"/></Field>
        {me.user.role === 'admin' && can('publish:authorize') ? (<label className="row small" style={{ gap: 8, alignItems: 'flex-start' }}>
            <input type="checkbox" checked={now} onChange={(e) => setNow(e.target.checked)}/>
            <span>Authorize it now as well (you are an admin). Otherwise it waits in Publishing for a reviewer.</span>
          </label>) : <div className="small muted">A reviewer authorizes it in Publishing.</div>}
        {now ? <Field label="Type PUBLISH to authorize"><input className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off"/></Field> : null}
        {!me.livePublishing && now ? <div className="callout warn"><Icon name="lock"/><div className="small">Live publishing is switched off on this server, so authorizing will be refused and nothing is sent to Shopify. The request is still made.</div></div> : null}
        {error ? <div className="callout crit" role="alert"><Icon name="alert"/>{error}</div> : null}
      </div>
    </Dialog>);
}
/** The final gate before anything goes live: shows exactly what will happen, requires the typed
 * phrase, and states up front when the server has live publishing switched off. */
export function AuthorizeDialog({ req, retry, onClose, onDone }) {
    const { me, brandOf } = useApp();
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const [note, setNote] = useState('');
    const [error, setError] = useState('');
    const brand = brandOf(req.brand_id);
    const go = async (typed) => {
        setBusy(true);
        setError('');
        try {
            const res = await api.post(`/publish-requests/${req.id}/${retry ? 'retry' : 'authorize'}`, { confirm: typed, note });
            toast.ok(res?.message ?? (req.mode === 'schedule' ? 'Scheduled on Shopify.' : 'Published to the storefront.'));
            onDone();
        }
        catch (e) {
            setError(e.message);
        }
        finally {
            setBusy(false);
        }
    };
    const what = req.mode === 'schedule' ? `be scheduled to go live on ${brand.name} at ${fmtZoned(req.publish_at)}` : req.mode === 'update_live' ? `replace the live article on ${brand.name}` : `go live on ${brand.name} immediately`;
    return (<ConfirmDialog title={retry ? 'Retry publishing' : 'Authorize publishing'} confirmLabel={retry ? 'Retry publish' : req.mode === 'schedule' ? 'Authorize & schedule' : 'Authorize & publish'} phrase="PUBLISH" busy={busy} onClose={onClose} onConfirm={go}>
      <p style={{ margin: 0 }}>“<b>{req.title}</b>” (version {req.version}) will {what}.</p>
      <Kv items={[
            ['Requested by', req.requested_by_name ?? '—'],
            ['Request note', req.note || <span className="faint">none</span>],
            ['Storefront', <a href={brand.blogUrl} target="_blank" rel="noopener">{brand.blogUrl.replace('https://', '')}</a>],
        ]}/>
      {!me.livePublishing ? (<div className="callout warn"><Icon name="lock"/><div><b>Live publishing is switched off on this server.</b> The server will refuse this until an admin sets ALLOW_LIVE_PUBLISH=true. Nothing will be sent to Shopify.</div></div>) : null}
      {req.stale ? <div className="callout crit"><Icon name="alert"/>The article changed after this request. It will be refused and needs a fresh review.</div> : null}
      {!retry ? (<div className="field"><label htmlFor="auth-note">Note (optional)</label><input id="auth-note" className="input" value={note} onChange={(e) => setNote(e.target.value)}/></div>) : null}
      {error ? <div className="callout crit" role="alert"><Icon name="alert"/>{error}</div> : null}
    </ConfirmDialog>);
}
export function RejectDialog({ req, onClose, onDone }) {
    const [note, setNote] = useState('');
    const [busy, setBusy] = useState(false);
    const toast = useToast();
    const go = async () => {
        setBusy(true);
        try {
            await api.post(`/publish-requests/${req.id}/reject`, { note });
            toast.ok('Request rejected.');
            onDone();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    return (<Dialog title="Reject publish request" onClose={onClose} footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="danger" loading={busy} disabled={!note.trim()} onClick={go}>Reject</Button></>}>
      <div className="field">
        <label htmlFor="rej">Reason — the requester sees this</label>
        <textarea id="rej" data-autofocus className="textarea" value={note} onChange={(e) => setNote(e.target.value)}/>
      </div>
    </Dialog>);
}
