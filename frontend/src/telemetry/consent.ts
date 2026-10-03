export const PRIVACY_KEY = "alxprgs.privacy.v1";
export const PRIVACY_CHANGE = "alxprgs-privacy-change";
const VERSION = "2026-10-03";
const LIFETIME = 180 * 24 * 60 * 60 * 1000;
export interface PrivacyChoice { version: string; diagnostics: boolean; replay: boolean; expiresAt: number; }
let memoryChoice: PrivacyChoice | null = null;
if (typeof window !== "undefined") window.addEventListener("storage", event => {
  if (event.key === PRIVACY_KEY || event.key === null) memoryChoice = null;
});

export function readPrivacyChoice(): PrivacyChoice | null {
  if (memoryChoice) {
    if (memoryChoice.expiresAt > Date.now()) return memoryChoice;
    memoryChoice = null;
  }
  try {
    const raw = window.localStorage.getItem(PRIVACY_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return null;
    const item = value as PrivacyChoice;
    if (item.version !== VERSION || typeof item.diagnostics !== "boolean" || typeof item.replay !== "boolean" ||
        typeof item.expiresAt !== "number" || !Number.isFinite(item.expiresAt) || item.expiresAt <= Date.now() ||
        item.expiresAt > Date.now() + LIFETIME || (item.replay && !item.diagnostics)) return null;
    return item;
  } catch { return null; }
}

export function savePrivacyChoice(diagnostics: boolean, replay: boolean): boolean {
  const choice = { version: VERSION, diagnostics, replay: diagnostics && replay, expiresAt: Date.now() + LIFETIME };
  memoryChoice = null;
  let persisted = true;
  try { window.localStorage.setItem(PRIVACY_KEY, JSON.stringify(choice)); }
  catch { persisted = false; memoryChoice = choice; }
  window.dispatchEvent(new Event(PRIVACY_CHANGE));
  return persisted;
}

export function permitsDiagnostics(): boolean { return readPrivacyChoice()?.diagnostics === true; }
export function permitsReplay(): boolean { return permitsDiagnostics() && readPrivacyChoice()?.replay === true; }
