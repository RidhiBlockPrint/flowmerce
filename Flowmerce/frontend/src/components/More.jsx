'use client';
/* A "Show more" section: details that are not needed every day stay folded until someone opens them. It remembers
   whether it was open, per section, in this browser. */
import { useEffect, useState } from 'react';
import { Icon } from './Icon';

export function More({ id, label = 'Show more', forceOpen = false, children }) {
    const key = `bo.more.${id}`;
    const [open, setOpen] = useState(false);
    useEffect(() => { try { setOpen(window.localStorage.getItem(key) === '1'); } catch { /* storage blocked: start folded */ } }, [key]);
    useEffect(() => { if (forceOpen) setOpen(true); }, [forceOpen]);
    const toggle = (e) => {
        const next = e.currentTarget.open;
        setOpen(next);
        try { window.localStorage.setItem(key, next ? '1' : '0'); } catch { /* storage blocked: nothing to remember */ }
    };
    return (<details className="more" open={open} onToggle={toggle}>
      <summary><Icon name="chevronRight" size="sm"/>{open ? 'Show less' : label}</summary>
      {open ? <div className="more-body">{children}</div> : null}
    </details>);
}
