/**
 * Модуль безопасности фронтенда (G8-SEC, FINAL-04).
 */

/**
 * Валидация и санитизация return_to / redirect_uri (G8-SEC, FINAL-04).
 * Защищает от Open Redirect атак:
 * - Запрещает внешние домены (https://evil.com)
 * - Запрещает protocol-relative URL (//evil.com)
 * - Запрещает обратные слеши (/\evil.com, \evil.com, %5c)
 * - Запрещает псевдопротоколы (javascript:, data:, vbscript:)
 * - Разрешает только:
 *   1) Относительные пути на текущем домене, начинающиеся с '/', кроме '//' и '/\\'
 *   2) Абсолютные URL с точным текущим origin (scheme, host и port).
 */
export function sanitizeReturnTo(returnTo: string | null | undefined): string | null {
  if (!returnTo || typeof returnTo !== "string" || returnTo.length > 4096) {
    return null;
  }

  // Запрет управляющих символов и переносов строк
  if (/[\r\n\t]/.test(returnTo)) {
    return null;
  }

  const trimmed = returnTo.trim();
  if (!trimmed) {
    return null;
  }

  // Запрет схем javascript:, data:, vbscript:
  const lower = trimmed.toLowerCase();
  if (
    lower.startsWith("javascript:") ||
    lower.startsWith("data:") ||
    lower.startsWith("vbscript:")
  ) {
    return null;
  }

  // Запрет protocol-relative (//) и обратных слэшей (\ или /\)
  if (
    trimmed.startsWith("//") ||
    trimmed.startsWith("/\\") ||
    trimmed.startsWith("\\") ||
    trimmed.includes("\\")
  ) {
    return null;
  }

  try {
    // 1. Относительный путь (начинается с '/')
    if (trimmed.startsWith("/")) {
      const parsed = new URL(trimmed, window.location.origin);
      if (parsed.origin !== window.location.origin) {
        return null;
      }
      return trimmed;
    }

    // 2. Абсолютный URL
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }

    if (parsed.origin === window.location.origin && !parsed.username && !parsed.password) {
      return parsed.toString();
    }

    return null;
  } catch {
    return null;
  }
}
