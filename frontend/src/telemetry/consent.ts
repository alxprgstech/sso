export const PRIVACY_KEY = "alxprgs.privacy.v1";
export const PRIVACY_CHANGE = "alxprgs-privacy-change";
const VERSION = "2026-10-03";
const LIFETIME = 180 * 24 * 60 * 60 * 1000;
export interface PrivacyChoice { version: string; diagnostics: boolean; replay: boolean; expiresAt: number; }
let memoryChoice: PrivacyChoice | null = null;
if (typeof window !== "undefined") window.addEventListener("storage", event => {
  if (event.key === PRIVACY_KEY || event.key === null) memoryChoice = null;
});

function validExpiry(value: unknown, now: number): value is number {
  if (typeof value !== "number") return false;
  if (!Number.isFinite(value)) return false;
  return value > now && value <= now + LIFETIME;
}

function choiceFields(value: unknown): PrivacyChoice | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Partial<PrivacyChoice>;
  if (item.version !== VERSION) return null;
  if (typeof item.diagnostics !== "boolean") return null;
  if (typeof item.replay !== "boolean") return null;
  return item as PrivacyChoice;
}

function parseChoice(value: unknown): PrivacyChoice | null {
  const item = choiceFields(value);
  if (!item) return null;
  if (!validExpiry(item.expiresAt, Date.now())) return null;
  if (item.replay && !item.diagnostics) return null;
  return item;
}

function readStoredChoice(): PrivacyChoice | null {
  try {
    const raw = window.localStorage.getItem(PRIVACY_KEY);
    return raw ? parseChoice(JSON.parse(raw)) : null;
  } catch { return null; }
}

export function readPrivacyChoice(): PrivacyChoice | null {
  if (memoryChoice && memoryChoice.expiresAt > Date.now()) return memoryChoice;
  memoryChoice = null;
  return readStoredChoice();
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
