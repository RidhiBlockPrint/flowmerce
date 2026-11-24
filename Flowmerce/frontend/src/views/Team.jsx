'use client';
import { useState } from 'react';
import { api, useApi } from '../lib/api';
import { useApp } from '../lib/app';
import { timeAgo } from '../lib/format';
import { generatePassword } from '../lib/passwords.mjs';
import { Button, Card, ErrorState, LoadingBlock, PageHead, Pill } from '../components/ui';
import { ConfirmDialog, Dialog, useToast } from '../components/overlays';
import { Icon } from '../components/Icon';

/**
 * Settings → Team (online workspace only): who can sign in, and what each person's role allows.
 * An administrator adds a person, gets a generated password to pass on, and can change their role, reset their
 * password or deactivate them. The API enforces all of it (users:manage); this page only asks.
 */
const ROLE_NOTES = {
    admin: 'Everything, including this Team page, integrations and brand settings.',
    seo_manager: 'Writes and edits articles, runs automation and requests publishing. Cannot approve their own publish request.',
    reviewer: 'Reviews articles and approves publishing. Cannot write or edit articles.',
};

export default function Team() {
    const { me, can } = useApp();
    if (me.localOperator)
        return (<>
          <PageHead title="Team" sub="Who can sign in to the online workspace."/>
          <div className="callout info" role="note">
            <Icon name="info"/>
            <div>On this computer Flowmerce opens without signing in, so there is no team to manage here. Add and remove people in the online workspace.</div>
          </div>
        </>);
    if (!can('users:manage'))
        return <ErrorState error={new Error('Only administrators can manage the team.')}/>;
    return <TeamList />;
}

function TeamList() {
    const { me, refreshMe } = useApp();
    const q = useApi('/users', { remember: false });
    const toast = useToast();
    const [dialog, setDialog] = useState(null);   // { kind: 'add' | 'edit' | 'reset' | 'deactivate', user? }
    const [busy, setBusy] = useState(false);
    const close = () => setDialog(null);
    const roleLabel = (key) => q.data?.roles.find((r) => r.key === key)?.label ?? key;

    const setActive = async (user, active) => {
        setBusy(true);
        try {
            await api.patch(`/users/${user.id}`, { active });
            toast.ok(active ? `${user.name} can sign in again.` : `${user.name} is deactivated and signed out.`);
            close();
            q.reload();
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };

    return (<>
      <PageHead title="Team" sub="Who can sign in to the online workspace, and what each person can do."
        actions={<Button variant="primary" icon="plus" onClick={() => setDialog({ kind: 'add' })}>Add person</Button>}/>
      <ErrorState error={q.error} onRetry={q.reload}/>
      {!q.data ? <LoadingBlock /> : (<div className="col gap-16">
        <div className="card flush">
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Person</th><th>Role</th><th className="hide-sm">Last sign-in</th><th>Status</th><th aria-label="Actions"/></tr></thead>
              <tbody>
                {q.data.users.map((u) => (<tr key={u.id}>
                    <td className="title-cell">
                      <span className="ttl">{u.name}{u.id === me.user.id ? <span className="faint"> (you)</span> : null}</span>
                      <span className="sub">{u.email}</span>
                    </td>
                    <td><span className="pill outline">{roleLabel(u.role)}</span></td>
                    <td className="hide-sm small">{u.last_login_at ? timeAgo(u.last_login_at) : <span className="faint">never</span>}</td>
                    <td>{u.active ? <Pill tone="ok" dot>Active</Pill> : <Pill dot>Deactivated</Pill>}</td>
                    <td>
                      {/* Plain buttons, not a drop-down: a menu would be cut off by the table's scroll area. */}
                      <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap', gap: 4 }}>
                        <Button variant="ghost" size="sm" icon="edit" aria-label={`Edit ${u.name}`} onClick={() => setDialog({ kind: 'edit', user: u })}>Edit</Button>
                        <Button variant="ghost" size="sm" icon="key" aria-label={`Reset password for ${u.name}`} onClick={() => setDialog({ kind: 'reset', user: u })}>Reset password</Button>
                        {u.active
                          ? <Button variant="ghost" size="sm" icon="lock" disabled={u.id === me.user.id} title={u.id === me.user.id ? 'You cannot deactivate yourself.' : undefined}
                              aria-label={`Deactivate ${u.name}`} onClick={() => setDialog({ kind: 'deactivate', user: u })}>Deactivate</Button>
                          : <Button variant="ghost" size="sm" icon="checkCircle" loading={busy} aria-label={`Reactivate ${u.name}`} onClick={() => setActive(u, true)}>Reactivate</Button>}
                      </div>
                    </td>
                  </tr>))}
              </tbody>
            </table>
          </div>
        </div>
        <Card title="What each role can do" sub="Everyone who signs in can open every section, including Shipping and Conversion (CRO). Roles decide who can change SEO content, approve publishing and manage settings.">
          <dl className="kv">
            {q.data.roles.map((r) => (<div key={r.key} style={{ display: 'contents' }}><dt>{r.label}</dt><dd>{ROLE_NOTES[r.key] ?? ''}</dd></div>))}
          </dl>
        </Card>
      </div>)}

      {dialog?.kind === 'add' ? <AddPerson roles={q.data?.roles ?? []} onClose={close} onDone={q.reload}/> : null}
      {dialog?.kind === 'edit' ? <EditPerson user={dialog.user} roles={q.data?.roles ?? []} self={dialog.user.id === me.user.id} onClose={close}
        onDone={() => { q.reload(); if (dialog.user.id === me.user.id) void refreshMe(); }}/> : null}
      {dialog?.kind === 'reset' ? <ResetPassword user={dialog.user} self={dialog.user.id === me.user.id} onClose={close}/> : null}
      {dialog?.kind === 'deactivate' ? (<ConfirmDialog title={`Deactivate ${dialog.user.name}?`} confirmLabel="Deactivate" danger busy={busy}
        onClose={close} onConfirm={() => setActive(dialog.user, false)}>
          <p style={{ margin: 0 }}>{dialog.user.name} is signed out straight away and cannot sign in again until you reactivate them. Their past work and audit history stay as they are.</p>
        </ConfirmDialog>) : null}
    </>);
}

/** The sign-in details to pass on. The password is shown here once and cannot be looked up later. */
function Handover({ email, password }) {
    const toast = useToast();
    const address = typeof window === 'undefined' ? '' : `${window.location.origin}/login`;
    const text = `Flowmerce sign-in\n${address}\nEmail: ${email}\nPassword: ${password}`;
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(text);
            toast.ok('Sign-in details copied.');
        }
        catch {
            toast.error(new Error('Could not copy. Select the details and copy them by hand.'));
        }
    };
    return (<div className="col gap-12">
      <div className="callout warn" role="note">
        <Icon name="key"/>
        <div><b>Pass these on now.</b> The password is shown only this once. If it is lost, reset it from the Team page.</div>
      </div>
      <dl className="kv">
        <div style={{ display: 'contents' }}><dt>Sign-in page</dt><dd className="mono small">{address}</dd></div>
        <div style={{ display: 'contents' }}><dt>Email</dt><dd className="mono small">{email}</dd></div>
        <div style={{ display: 'contents' }}><dt>Password</dt><dd className="mono strong" data-testid="handover-password">{password}</dd></div>
      </dl>
      <div><Button icon="copy" onClick={copy}>Copy sign-in details</Button></div>
      <p className="muted small" style={{ margin: 0 }}>They can choose their own password after signing in: account menu (bottom left) → Change password.</p>
    </div>);
}

function AddPerson({ roles, onClose, onDone }) {
    const toast = useToast();
    const [f, setF] = useState({ name: '', email: '', role: 'seo_manager' });
    const [busy, setBusy] = useState(false);
    const [made, setMade] = useState(null);
    const set = (k) => (e) => setF((v) => ({ ...v, [k]: e.target.value }));
    const ready = f.name.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim());
    const save = async (e) => {
        e?.preventDefault();
        if (!ready || busy)
            return;
        setBusy(true);
        const password = generatePassword();
        try {
            await api.post('/users', { name: f.name.trim(), email: f.email.trim().toLowerCase(), role: f.role, password });
            setMade({ email: f.email.trim().toLowerCase(), password });
            onDone();
        }
        catch (err) {
            toast.error(err);
        }
        finally {
            setBusy(false);
        }
    };
    if (made)
        return (<Dialog title={`${f.name.trim()} can now sign in`} onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
          <Handover email={made.email} password={made.password}/>
        </Dialog>);
    return (<Dialog title="Add a person" sub="They get their own sign-in. You pass the password on yourself." onClose={onClose} footer={<>
        <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="primary" onClick={save} disabled={!ready} loading={busy}>Add person</Button>
      </>}>
      <form className="col gap-12" onSubmit={save}>
        <div className="field"><label htmlFor="tm-name">Name</label><input id="tm-name" data-autofocus className="input" value={f.name} onChange={set('name')} maxLength={120} autoComplete="off"/></div>
        <div className="field"><label htmlFor="tm-email">Email</label><input id="tm-email" className="input" type="email" value={f.email} onChange={set('email')} maxLength={200} autoComplete="off" autoCapitalize="none" spellCheck={false}/>
          <div className="hint">This is what they type to sign in. No email is sent to it.</div></div>
        <RoleField id="tm-role" roles={roles} value={f.role} onChange={set('role')}/>
        <button type="submit" hidden/>
      </form>
    </Dialog>);
}

function RoleField({ id, roles, value, onChange, disabled, hint }) {
    return (<div className="field"><label htmlFor={id}>Role</label>
      <select id={id} className="select" value={value} onChange={onChange} disabled={disabled}>{roles.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}</select>
      <div className="hint">{hint ?? ROLE_NOTES[value] ?? ''}</div>
    </div>);
}

function EditPerson({ user, roles, self, onClose, onDone }) {
    const toast = useToast();
    const [f, setF] = useState({ name: user.name, email: user.email, role: user.role });
    const [busy, setBusy] = useState(false);
    const set = (k) => (e) => setF((v) => ({ ...v, [k]: e.target.value }));
    const ready = f.name.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email.trim());
    const changed = f.name.trim() !== user.name || f.email.trim().toLowerCase() !== user.email.toLowerCase() || f.role !== user.role;
    const signsOut = !self && (f.role !== user.role || f.email.trim().toLowerCase() !== user.email.toLowerCase());
    const save = async (e) => {
        e?.preventDefault();
        if (!ready || !changed || busy)
            return;
        setBusy(true);
        try {
            await api.patch(`/users/${user.id}`, { name: f.name.trim(), email: f.email.trim().toLowerCase(), role: f.role });
            toast.ok('Saved.');
            onDone();
            onClose();
        }
        catch (err) {
            toast.error(err);
        }
        finally {
            setBusy(false);
        }
    };
    return (<Dialog title={`Edit ${user.name}`} onClose={onClose} footer={<>
        <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="primary" onClick={save} disabled={!ready || !changed} loading={busy}>Save</Button>
      </>}>
      <form className="col gap-12" onSubmit={save}>
        <div className="field"><label htmlFor="te-name">Name</label><input id="te-name" data-autofocus className="input" value={f.name} onChange={set('name')} maxLength={120} autoComplete="off"/></div>
        <div className="field"><label htmlFor="te-email">Email</label><input id="te-email" className="input" type="email" value={f.email} onChange={set('email')} maxLength={200} autoComplete="off" autoCapitalize="none" spellCheck={false}/></div>
        <RoleField id="te-role" roles={roles} value={f.role} onChange={set('role')} disabled={self} hint={self ? 'You cannot change your own role. Ask another admin.' : undefined}/>
        {signsOut ? <div className="callout info" role="note"><Icon name="info"/><div>{user.name} will be signed out and signs in again with the new details.</div></div> : null}
        <button type="submit" hidden/>
      </form>
    </Dialog>);
}

function ResetPassword({ user, self, onClose }) {
    const toast = useToast();
    const [busy, setBusy] = useState(false);
    const [made, setMade] = useState(null);
    const reset = async () => {
        setBusy(true);
        const password = generatePassword();
        try {
            await api.patch(`/users/${user.id}`, { password });
            setMade(password);
        }
        catch (e) {
            toast.error(e);
        }
        finally {
            setBusy(false);
        }
    };
    if (made)
        return (<Dialog title={`New password for ${user.name}`} onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
          <Handover email={user.email} password={made}/>
        </Dialog>);
    return (<ConfirmDialog title={`Reset ${user.name}'s password?`} confirmLabel="Reset password" busy={busy} onClose={onClose} onConfirm={reset}>
      <p style={{ margin: 0 }}>{self
        ? 'You get a new generated password and your other devices are signed out. To choose your own password instead, use Change password in the account menu.'
        : `${user.name}'s current password stops working and they are signed out everywhere. You get a new generated password to pass on.`}</p>
    </ConfirmDialog>);
}
