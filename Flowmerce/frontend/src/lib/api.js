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
export const api = {
    get: (path, signal) => request('GET', path, undefined, { signal }),
    post: (path, body, headers) => request('POST', path, body ?? {}, { headers }),
    patch: (path, body) => request('PATCH', path, body),
};
export function qs(params) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params))
        if (v !== undefined && v !== null && v !== '' && v !== false)
            p.set(k, String(v));
    const s = p.toString();
    return s ? `?${s}` : '';
}
/** Fetch on mount and whenever `path` changes. A null path skips the request. */
export function useApi(path) {
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(!!path);
    const [tick, setTick] = useState(0);
    const first = useRef(true);
    useEffect(() => {
        if (!path) {
            setLoading(false);
            return;
        }
        const ctl = new AbortController();
        setLoading(true);
        setError(null);
        api.get(path, ctl.signal)
            .then((d) => { setData(d); first.current = false; })
            .catch((e) => { if (e.name !== 'AbortError')
            setError(e instanceof ApiError ? e : new ApiError(0, String(e))); })
            .finally(() => { if (!ctl.signal.aborted)
            setLoading(false); });
        return () => ctl.abort();
    }, [path, tick]);
    const reload = useCallback(() => setTick((t) => t + 1), []);
    return { data, error, loading, reload, setData, initialLoading: loading && first.current };
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
