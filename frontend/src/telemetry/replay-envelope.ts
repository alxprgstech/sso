import type { Envelope } from "@sentry/core";

// Final transport gate: the SDK can fall back to an uncompressed event buffer
// when Worker is unavailable. That buffer never passes our worker sanitizer.
export async function recordingWasSanitized(envelope: Envelope): Promise<boolean> {
  try {
    const item = envelope[1].find(item => item[0].type === "replay_recording");
    if (!item || !(item[1] instanceof Uint8Array)) return false;
    const payload = item[1];
    const offset = payload.indexOf(10) + 1;
    if (offset <= 0 || offset > 1024) return false;
    const reader = new Blob([new Uint8Array(payload.slice(offset))]).stream()
      .pipeThrough(new DecompressionStream("deflate")).getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 10 * 1024 * 1024) { await reader.cancel(); return false; }
      chunks.push(value);
    }
    const content = await new Blob(chunks.map(chunk => new Uint8Array(chunk))).text();
    const events: unknown = JSON.parse(content);
    return Array.isArray(events) && events.length > 0 && events.every(event =>
      event && typeof event === "object" && event._sso_sanitized === 1);
  } catch { return false; }
}
