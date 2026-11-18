/**
 * Pure helpers for "the article changed on the server while this tab has unsaved edits".
 * No React and no browser APIs, so they run under `node --test` (see frontend/tests/conflict.test.mjs).
 *
 * Terms: `base` is the saved version the user started from, `latest` is the newer saved version (a Shopify sync or
 * another person), `draft` is what is in the editor now. Nothing here ever drops text: every function returns the
 * user's own value alongside the latest one.
 */

/** Fields the user changed relative to the version they started from. */
export function editedFields(draft, base, fields) {
    if (!draft || !base)
        return [];
    return fields.filter((k) => (draft[k] ?? '') !== (base[k] ?? ''));
}

/** Per-field comparison of the user's edits against the latest saved version. `clash` means both sides changed the field. */
export function compareWithLatest({ draft, base, latest, fields }) {
    return editedFields(draft, base, fields).map((k) => ({
        field: k,
        mine: draft[k] ?? '',
        latest: latest[k] ?? '',
        started: base[k] ?? '',
        // Latest differs from what the user started from: the server changed this very field too.
        clash: (latest[k] ?? '') !== (base[k] ?? ''),
        // Latest already equals the user's text: nothing to resolve.
        same: (latest[k] ?? '') === (draft[k] ?? ''),
    }));
}

/**
 * Put the user's edits on top of the latest version, field by field:
 *   - a field the user did not touch takes the latest value (so the server's change is not reverted);
 *   - a field the user edited keeps the user's value, and is reported in `clashes` when the server changed it too.
 * The latest text of a clashing field stays available in the article's version history.
 */
export function rebase({ draft, base, latest, fields }) {
    const merged = {};
    const kept = [];
    const taken = [];
    const clashes = [];
    for (const k of fields) {
        const edited = (draft[k] ?? '') !== (base[k] ?? '');
        if (edited) {
            merged[k] = draft[k] ?? '';
            kept.push(k);
            if ((latest[k] ?? '') !== (base[k] ?? '') && (latest[k] ?? '') !== (draft[k] ?? ''))
                clashes.push(k);
        }
        else {
            merged[k] = latest[k] ?? '';
            if ((latest[k] ?? '') !== (base[k] ?? ''))
                taken.push(k);
        }
    }
    return { merged, kept, taken, clashes };
}

/** A copy of the user's edits that can be pasted anywhere: nothing is lost even if the tab is closed. */
export function exportEdits({ draft, base, fields, title, version }) {
    const changed = editedFields(draft, base, fields);
    return JSON.stringify({
        article: title ?? '',
        editedAgainstVersion: version ?? null,
        fields: Object.fromEntries(changed.map((k) => [k, draft[k]])),
    }, null, 2);
}

/** Short plain-text preview of a field value for a comparison table (HTML tags removed). */
export function preview(value, max = 180) {
    const text = String(value ?? '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
    if (!text)
        return '(empty)';
    return text.length > max ? `${text.slice(0, max)}…` : text;
}
