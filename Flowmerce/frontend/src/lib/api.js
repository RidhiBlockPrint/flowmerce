'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { IS_DEMO, demoDownload, demoRequest } from '../demo';
export class ApiError extends Error {
    status;
    code;
    details;
    constructor(status, message, code = 'error', details) {
        super(message);
        this.status = status;
        this.code = code;
        this.details = details;
    }
}
async function request(method, path, body, init = {}) {
    // Demo / preview: answer from the browser. Nothing is sent over the network.
    if (IS_DEMO) {
        try {
            return await demoRequest(method, path, body, init.signal);
        }
        catch (e) {
            if (e.name === 'AbortError' || e instanceof ApiError)
                throw e;
            throw new ApiError(e.status ?? 500, e.message, e.code, e.details);
        }
    }
    const headers = { 'X-Requested-With': 'blog-ops', Accept: 'application/json' };
    let payload;
    if (body instanceof ArrayBuffer || body instanceof Blob) {
        headers['Content-Type'] = 'application/octet-stream';
        payload = body;
    }
    else if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
        payload = JSON.stringify(body);
    }
    let res;
    try {
        res = await fetch('/api' + path, { method, headers: { ...headers, ...init.headers }, body: payload, credentials: 'same-origin', signal: init.signal });
    }
    catch (e) {
        if (e.name === 'AbortError')
            throw e;
        throw new ApiError(0, 'Cannot reach the server. Check your connection and that the API is running.', 'network');
    }
    const text = await res.text();
    const json = text ? (() => { try {
        return JSON.parse(text);
    }
    catch {
        return null;
    } })() : null;
    if (res.status === 401 && json?.code === 'signed_out')
        toSignIn();
    if (!res.ok)
        throw new ApiError(res.status, json?.error || `Request failed (${res.status})`, json?.code, json?.details);
    return json;
}
/** Hosted copy: the sign-in session ended (expired, or the password changed). Go to the sign-in page and come back. */
function toSignIn() {
    if (typeof window === 'undefined' || window.location.pathname === '/login')
        return;
    const here = window.location.pathname + window.location.search;
    window.location.assign(here === '/' ? '/login' : `/login?next=${encodeURIComponent(here)}`);
}
/**
 * Answers already shown in this tab, by path, so going back to a tab, filter or page shows its last answer at once
 * while useApi asks the server again in the background (stale-while-revalidate). Any change (POST/PATCH/DELETE)
 * empties it, and `generation` stops a read that started before a change from saving its older answer afterwards.
 */
const CACHE_MAX = 60;
const cache = new Map();
let generation = 0;
function cacheGet(path) {
    return cache.has(path) ? cache.get(path) : undefined;
}
function cacheSet(path, data) {
    cache.delete(path);
    cache.set(path, data);
    while (cache.size > CACHE_MAX)
        cache.delete(cache.keys().next().value);
}
function forgetAll() {
    generation += 1;
    cache.clear();
}
async function change(method, path, body, init) {
    forgetAll();
    try {
        return await request(method, path, body, init);
    }
    finally {
        forgetAll();
    }
}
export const api = {
    get: (path, signal) => request('GET', path, undefined, { signal }),
    post: (path, body, headers) => change('POST', path, body ?? {}, { headers }),
    patch: (path, body) => change('PATCH', path, body),
    put: (path, body) => change('PUT', path, body),
    del: (path) => change('DELETE', path),
};
export function qs(params) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params))
        if (v !== undefined && v !== null && v !== '' && v !== false)
            p.set(k, String(v));
    const s = p.toString();
    return s ? `?${s}` : '';
}
/**
 * Fetch on mount and whenever `path` changes. A null path skips the request.
 * A path already answered in this tab shows that answer straight away (no skeleton) and is refreshed in the
 * background; `loading` stays true until the fresh answer arrives. `reload()` always asks the server.
 * `{ remember: false }` neither shows nor keeps a remembered answer: for data that must never be shown out of date
 * (the article editor).
 */
export function useApi(path, { remember = true } = {}) {
    const recall = (p) => (remember && p ? cacheGet(p) : undefined);
    const [data, setData] = useState(() => recall(path) ?? null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(!!path);
    const [tick, setTick] = useState(0);
    const first = useRef(recall(path) === undefined);
    const pathRef = useRef(path);
    pathRef.current = path;
    const rememberRef = useRef(remember);
    rememberRef.current = remember;
    useEffect(() => {
        if (!path) {
            setLoading(false);
            return;
        }
        const hit = rememberRef.current ? cacheGet(path) : undefined;
        if (hit !== undefined) {
            setData(hit);
            first.current = false;
        }
        const ctl = new AbortController();
        const gen = generation;
        setLoading(true);
        setError(null);
        api.get(path, ctl.signal)
            .then((d) => {
            if (gen === generation && rememberRef.current)
                cacheSet(path, d);
            setData(d);
            first.current = false;
        })
            .catch((e) => { if (e.name !== 'AbortError')
            setError(e instanceof ApiError ? e : new ApiError(0, String(e))); })
            .finally(() => { if (!ctl.signal.aborted)
            setLoading(false); });
        return () => ctl.abort();
    }, [path, tick]);
    const reload = useCallback(() => setTick((t) => t + 1), []);
    // A page that edits its data in place (setData) keeps the saved answer in step, so coming back shows the edit.
    const setBoth = useCallback((v) => setData((prev) => {
        const next = typeof v === 'function' ? v(prev) : v;
        if (pathRef.current && rememberRef.current)
            cacheSet(pathRef.current, next);
        return next;
    }), []);
    return { data, error, loading, reload, setData: setBoth, initialLoading: loading && first.current };
}
export async function download(path) {
    if (IS_DEMO) {
        try {
            const { filename, blob } = await demoDownload(path);
            return saveBlob(blob, filename);
        }
        catch (e) {
            throw new ApiError(e.status ?? 500, e.message, e.code);
        }
    }
    const res = await fetch('/api' + path, { credentials: 'same-origin', headers: { 'X-Requested-With': 'blog-ops' } });
    if (!res.ok) {
        const j = await res.json().catch(() => null);
        if (res.status === 401 && j?.code === 'signed_out')
            toSignIn();
        throw new ApiError(res.status, j?.error || 'Download failed');
    }
    const cd = res.headers.get('Content-Disposition') || '';
    const name = (cd.match(/filename="([^"]+)"/) || [])[1] || 'download.xlsx';
    return saveBlob(await res.blob(), name);
}
function saveBlob(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
}
