'use client';
/* Every page appears all at once (owner request, 2026-11-21). The shell wraps each page in a LoadGate: the page is
 * rendered straight away so its requests start, but kept hidden behind one placeholder until everything it asked for
 * on opening has answered (bookkeeping in lib/loadGate.js, fed by useApi). Then the whole page shows together and its
 * entrance animations, paused while hidden, play.
 *
 * Opening another page or another tab (?tab=) starts a new wait without remounting anything, so a page keeps its
 * state (an article being edited keeps its unsaved text). Only requests with nothing to show count: answers
 * remembered in this tab show at once, a filter change on an open page never brings the placeholder back, and a page
 * or tab that needs no new data shows without the placeholder ever being painted. After 10 seconds a page shows
 * whatever is still loading. */
import { useLayoutEffect, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { LoadGateContext } from '../lib/api';
import { createLoadTracker } from '../lib/loadGate';
import { Skeleton } from './ui';

function newGate(key, setGate) {
    const tracker = createLoadTracker({ onReveal: () => setGate((g) => (g.tracker === tracker ? { ...g, shown: true } : g)) });
    return { key, tracker, shown: false };
}

export function LoadGate({ children }) {
    const key = `${usePathname() ?? '/'}|${useSearchParams()?.get('tab') ?? ''}`;
    const [gate, setGate] = useState(() => newGate(key, (u) => setGate(u)));
    if (gate.key !== key) setGate(newGate(key, setGate));     // a new page or tab: wait again (no remount)
    // Runs after the page's own layout effects, so its first requests are already counted.
    useLayoutEffect(() => {
        gate.tracker.start();
        return () => gate.tracker.stop();
    }, [gate.tracker]);
    return (<LoadGateContext.Provider value={gate.tracker}>
      <div className={`load-gate${gate.shown ? ' shown' : ''}`}>
        {gate.shown ? null : <PagePlaceholder/>}
        <div className="load-gate-page" aria-hidden={gate.shown ? undefined : true}>{children}</div>
      </div>
    </LoadGateContext.Provider>);
}

/** One placeholder for any page: a title, a row of figures and two blocks. Also the Suspense fallback in the shell. */
export function PagePlaceholder() {
    return (<div className="load-gate-placeholder" aria-busy="true" aria-label="Loading this page">
      <Skeleton h={30} w="36%" r={8}/>
      <Skeleton h={14} w="52%"/>
      <div className="load-gate-row"><Skeleton h={96} r={14}/><Skeleton h={96} r={14}/><Skeleton h={96} r={14}/><Skeleton h={96} r={14}/></div>
      <Skeleton h={260} r={16}/>
      <Skeleton h={180} r={16}/>
    </div>);
}
