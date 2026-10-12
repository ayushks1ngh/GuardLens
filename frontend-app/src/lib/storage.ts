/** localStorage that never throws (private windows, blocked storage). */
export function readPref(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
export function writePref(key: string, value: string): void {
  try { window.localStorage.setItem(key, value); } catch { /* preference just won't persist */ }
}
