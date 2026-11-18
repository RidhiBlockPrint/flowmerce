/**
 * Publication times with an explicit timezone. Pure functions (no React) so they run under `node --test`.
 * Timestamps arrive from the API as UTC ISO strings (for example 2026-11-16T14:30:00Z). They are converted to the viewer's
 * timezone and always shown with its name, never as a bare "20:00".
 */

// Zones whose short name is only a numeric offset in the default English locale.
const ZONE_ABBREVIATION = { 'Asia/Kolkata': 'IST', 'Asia/Calcutta': 'IST' };

/** The viewer's IANA timezone, or "UTC" when the browser does not say. */
export function viewerZone() {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    }
    catch {
        return 'UTC';
    }
}

function zoneName(date, timeZone) {
    if (ZONE_ABBREVIATION[timeZone])
        return ZONE_ABBREVIATION[timeZone];
    if (timeZone === 'UTC' || timeZone === 'Etc/UTC')
        return 'UTC';
    const part = new Intl.DateTimeFormat('en-US', { timeZone, timeZoneName: 'short' }).formatToParts(date).find((p) => p.type === 'timeZoneName');
    return (part?.value ?? timeZone).replace('GMT', 'UTC');
}

/** "16 November 2026, 8:00 PM IST". Returns "—" for a missing or invalid value. */
export function fmtZoned(iso, timeZone = viewerZone()) {
    if (!iso)
        return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime()))
        return '—';
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
        timeZone, day: 'numeric', month: 'long', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
    }).formatToParts(date).map((p) => [p.type, p.value]));
    return `${parts.day} ${parts.month} ${parts.year}, ${parts.hour}:${parts.minute} ${String(parts.dayPeriod).toUpperCase()} ${zoneName(date, timeZone)}`;
}

/** The same instant in UTC, so the source value stays checkable: "16 November 2026, 2:30 PM UTC". */
export function fmtUtc(iso) {
    return fmtZoned(iso, 'UTC');
}
