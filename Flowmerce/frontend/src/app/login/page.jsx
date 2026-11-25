'use client';
/**
 * Sign-in page for the hosted copy. Each person signs in with their own email and password. The form posts to
 * /auth/login, which src/middleware.js handles (the API checks the password, the middleware sets the session
 * cookie), so it works even before JavaScript loads. On your own computer
 * (no FLOWMERCE_LOGIN_PASSWORD) the middleware sends /login straight to Home, and the demo build does the same.
 */
import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Logo } from '../../components/Logo';
import { Icon } from '../../components/Icon';
import { IS_DEMO } from '../../demo';

/** A repeating block-print motif drawn in SVG for the sign-in panel. */
function Pattern() {
  return (
    <svg className="pattern" aria-hidden>
      <defs>
        <pattern id="bp" width="64" height="64" patternUnits="userSpaceOnUse">
          <g fill="none" stroke="#EFB34C" strokeWidth="1.4">
            <circle cx="32" cy="32" r="5" />
            <path d="M32 14c4 4 4 9 0 12-4-3-4-8 0-12zM32 50c4-4 4-9 0-12-4 3-4 8 0 12zM14 32c4-4 9-4 12 0-3 4-8 4-12 0zM50 32c-4-4-9-4-12 0 3 4 8 4 12 0z" />
          </g>
          <g fill="#B8432F"><circle cx="0" cy="0" r="2" /><circle cx="64" cy="0" r="2" /><circle cx="0" cy="64" r="2" /><circle cx="64" cy="64" r="2" /></g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#bp)" />
    </svg>
  );
}

const MESSAGES = {
  invalid: ['crit', 'alert', 'That email and password do not match. Check them and try again.'],
  locked: ['crit', 'lock', 'Too many attempts. Sign-in is paused for 15 minutes; try again after that.'],
  no_access: ['crit', 'lock', 'Your password is right, but this account has not been given access to Flowmerce. Ask the owner to add you.'],
  unavailable: ['crit', 'alert', 'Sign-in is not answering right now. Wait a minute and try again.'],
  expired: ['info', 'lock', 'Your session has ended. Sign in again to continue.'],
  signed_out: ['info', 'checkCircle', 'You have been signed out.'],
};

function SignInForm() {
  const params = useSearchParams();
  const router = useRouter();
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (IS_DEMO) router.replace('/'); }, [router]);

  const code = params.get('error') || (params.get('signed_out') ? 'signed_out' : '');
  const message = MESSAGES[code];
  const next = params.get('next') || '/';

  return (
    <form className="login-card col gap-16" method="post" action="/auth/login" onSubmit={() => setBusy(true)}>
      <div className="login-mobile-logo"><Logo size={24} tagline /></div>
      <div>
        <h1 className="page-title">Welcome back</h1>
        <p className="page-sub">Sign in to your Flowmerce workspace.</p>
      </div>

      {message ? (
        <div className={`callout ${message[0]}`} role={message[0] === 'crit' ? 'alert' : 'status'}>
          <Icon name={message[1]} />{message[2]}
        </div>
      ) : null}

      <input type="hidden" name="next" value={next} />
      <div className="field">
        <label htmlFor="username">Email</label>
        <input id="username" name="username" className="input login-input" autoComplete="username" autoCapitalize="none"
          inputMode="email" spellCheck={false} required autoFocus />
      </div>
      <div className="field">
        <label htmlFor="password">Password</label>
        <div className="login-password">
          <input id="password" name="password" className="input login-input" type={show ? 'text' : 'password'}
            autoComplete="current-password" required />
          <button type="button" className="login-reveal" onClick={() => setShow((s) => !s)}
            aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show}>
            <Icon name="eye" size="sm" />
          </button>
        </div>
      </div>
      <label className="login-remember">
        <input type="checkbox" name="remember" defaultChecked />
        <span>Keep me signed in for 30 days</span>
      </label>
      <button type="submit" className="btn primary login-submit" disabled={busy} aria-busy={busy || undefined}>
        {busy ? <Icon name="loader" className="spin" /> : <Icon name="lock" />}
        {busy ? 'Signing in…' : 'Sign in'}
      </button>
      <p className="login-foot">
        <Icon name="shield" size="sm" />
        Private workspace. Your connection is encrypted, and repeated wrong passwords pause sign-in.
      </p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="login">
      <div className="login-art on-dark">
        <Pattern />
        <Logo size={30} tagline onDark />
        <div>
          <p className="serif login-headline">Every order, article and shipment, in one flow.</p>
          <div className="row-wrap gap-12" style={{ opacity: 0.85 }}>
            <span className="row"><span className="brand-dot" style={{ background: '#EFB34C' }} />Ridhi Block Print</span>
            <span className="row"><span className="brand-dot" style={{ background: '#F1D3C1' }} />Cotton Print Club</span>
          </div>
        </div>
        <p className="small" style={{ opacity: 0.6, margin: 0 }}>SEO &amp; content · Shipping · Automation</p>
      </div>
      <div className="login-form">
        <Suspense fallback={null}><SignInForm /></Suspense>
      </div>
    </div>
  );
}
