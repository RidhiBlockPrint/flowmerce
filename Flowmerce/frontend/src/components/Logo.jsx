/**
 * Flowmerce logo ("Concept B, Thread F"): an F drawn as a thread with six coloured stops, and the
 * wordmark "flow" + bold "merce". Colours come from CSS variables so one component serves both themes:
 * light is the default; dark applies inside any element with `data-theme="dark"` or class `on-dark`
 * (the sign-in art panel uses it today), or when the `onDark` prop is set. See `.flow-logo` in globals.css.
 * Static copies for outside the app are in `frontend/public/brand/`.
 */

const THREAD = { fill: 'none', strokeWidth: 11, strokeLinecap: 'round', strokeLinejoin: 'round' };

/** The F mark only. */
export function LogoMark({ className = '', onDark = false, title }) {
  const cls = `flow-logo-mark ${onDark ? 'on-dark' : ''} ${className}`.trim();
  return (
    <svg className={cls} viewBox="0 0 100 150" role={title ? 'img' : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
      {title ? <title>{title}</title> : null}
      <path d="M14 134 V50 C14 28 28 14 50 14 H80" style={{ ...THREAD, stroke: 'var(--fl-thread)' }} strokeDasharray="130 8 22 60" />
      <path d="M14 79 L62 69" style={{ ...THREAD, stroke: 'var(--fl-thread)' }} strokeDasharray="38 40" />
      <circle cx="48" cy="14" r="8" style={{ fill: 'var(--fl-purple)' }} />
      <circle cx="86" cy="14" r="8" style={{ fill: 'var(--fl-coral)' }} />
      <circle cx="14" cy="45" r="7" style={{ fill: 'var(--fl-blue)' }} />
      <circle cx="14" cy="79" r="8" style={{ fill: 'var(--fl-orange)' }} />
      <circle cx="70" cy="67" r="8" style={{ fill: 'var(--fl-cyan)' }} />
      <circle cx="14" cy="138" r="8" style={{ fill: 'var(--fl-green)' }} />
    </svg>
  );
}

/**
 * Full lockup: mark + wordmark, optional tagline. Size it with font-size on the element or the
 * `size` prop (px); the mark scales with the wordmark.
 */
export function Logo({ tagline = false, onDark = false, size, className = '', style }) {
  const cls = `flow-logo ${onDark ? 'on-dark' : ''} ${className}`.trim();
  return (
    <span className={cls} style={size ? { fontSize: size, ...style } : style}>
      <LogoMark />
      <span className="flow-logo-text">
        <span className="flow-logo-word" aria-label="flowmerce">
          <span className="flow-logo-flow" aria-hidden>flow</span>
          <span className="flow-logo-merce" aria-hidden>merce</span>
        </span>
        {tagline ? <span className="flow-logo-tag">{typeof tagline === 'string' ? tagline : 'Ecommerce in a Flow'}</span> : null}
      </span>
    </span>
  );
}
