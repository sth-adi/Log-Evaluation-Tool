/**
 * Small per-browser conveniences (recent channels, metrics). Browser storage can be unavailable
 * (a private window, blocked site data) and that is a normal condition, not a bug, so a failed
 * read gives the default and a failed write is skipped. Nothing stored here is needed to work.
 */
export function readJson<T>(key: string, fallback: T, valid: (v: unknown) => v is T): T {
  let raw: string | null;
  try {
    raw = localStorage.getItem(key);
  } catch {
    return fallback;
  }
  if (raw === null) return fallback;
  try {
    const v: unknown = JSON.parse(raw);
    return valid(v) ? v : fallback;
  } catch (e) {
    console.warn(`Ignoring unreadable saved "${key}"`, e);
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable: the value just will not be remembered */
  }
}
