/**
 * Passwords an administrator hands to a team member (Settings → Team). Generated in the browser, shown once,
 * and sent to the API only to be stored as a hash.
 *
 * 16 characters from 32 look-alike-free symbols (no l, o, 0 or 1) in four groups: about 80 bits, easy to read out.
 */
const ALPHABET = 'abcdefghijkmnpqrstuvwxyz23456789';
export const MIN_PASSWORD_LENGTH = 12;

/** `random` fills a Uint8Array with random bytes (crypto.getRandomValues by default); tests pass their own. */
export function generatePassword(random = (bytes) => crypto.getRandomValues(bytes)) {
  const bytes = random(new Uint8Array(16));
  // 32 symbols divide 256 exactly, so every symbol is equally likely.
  const chars = Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]);
  return [0, 4, 8, 12].map((i) => chars.slice(i, i + 4).join('')).join('-');
}

/** Why a typed password cannot be used, or '' when it can (the API applies the same rule). */
export function passwordProblem(value) {
  if (typeof value !== 'string' || value.length < MIN_PASSWORD_LENGTH) return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (value.length > 200) return 'Use 200 characters or fewer.';
  return '';
}
