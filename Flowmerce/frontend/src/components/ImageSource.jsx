'use client';
/**
 * Where an article's featured image comes from: a link (any https:// image address) or a file from this computer. A
 * file is sent to POST /api/images/upload, which stores it in the brand's Shopify Files and answers with its public URL;
 * that URL becomes the image URL like any pasted link. `onPick(url, alt)` gives the result to the editor.
 */
import { useEffect, useRef, useState } from 'react';
import { api, qs } from '../lib/api';
import { Button } from './ui';
import { Icon } from './Icon';

const ACCEPT = 'image/jpeg,image/png,image/webp,image/gif';
const MAX_MB = 15;
const altFromName = (name) => name.replace(/\.[a-z0-9]+$/i, '').replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim();

export function ImageSource({ brand, url, alt, onPick, disabled }) {
    const [mode, setMode] = useState('link');
    const [link, setLink] = useState(url || '');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [drag, setDrag] = useState(false);
    const input = useRef(null);
    useEffect(() => { setLink(url || ''); }, [url]);
    const linkOk = /^https:\/\/\S+$/i.test(link.trim());
    const useLink = () => { setError(null); onPick(link.trim(), alt); };
    const upload = async (file) => {
        setError(null);
        if (!file) return;
        if (!ACCEPT.split(',').includes(file.type)) { setError('Choose a JPG, PNG, WebP or GIF image.'); return; }
        if (file.size > MAX_MB * 1024 * 1024) { setError(`The image is larger than ${MAX_MB} MB.`); return; }
        setBusy(true);
        try {
            const name = alt || altFromName(file.name);
            const r = await api.post(`/images/upload${qs({ brand, filename: file.name, alt: name })}`, file);
            setLink(r.url);
            onPick(r.url, name);
        } catch (e) {
            setError(e.message || 'The upload did not work.');
        } finally {
            setBusy(false);
        }
    };
    return (<div className="imgsrc">
      <div className="seg sm" role="tablist" aria-label="Image source">
        <button type="button" role="tab" aria-pressed={mode === 'link'} onClick={() => setMode('link')}><Icon name="link" size="sm"/>From a link</button>
        <button type="button" role="tab" aria-pressed={mode === 'file'} onClick={() => setMode('file')}><Icon name="upload" size="sm"/>From your computer</button>
      </div>
      {mode === 'link' ? (<div className="imgsrc-link">
          <input className="input" placeholder="https://… image address" value={link} disabled={disabled} onChange={(e) => setLink(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && linkOk) useLink(); }} aria-label="Image link"/>
          <Button variant="primary" disabled={disabled || !linkOk || link.trim() === url} onClick={useLink}>Use</Button>
        </div>) : (<label className={`imgsrc-drop${drag ? ' drag' : ''}${disabled ? ' off' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); if (!disabled) upload(e.dataTransfer.files?.[0]); }}>
          <input ref={input} type="file" accept={ACCEPT} hidden disabled={disabled || busy} onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ''; }}/>
          <Icon name={busy ? 'loader' : 'upload'} className={busy ? 'spin' : ''}/>
          <span className="strong small">{busy ? 'Uploading to Shopify…' : 'Drop an image here, or click to choose'}</span>
          <span className="muted xs">JPG, PNG, WebP or GIF up to {MAX_MB} MB. Stored in the store&rsquo;s Shopify Files.</span>
        </label>)}
      {error ? <div className="callout warn small" role="alert"><Icon name="alert"/><div>{error}</div></div> : null}
    </div>);
}
