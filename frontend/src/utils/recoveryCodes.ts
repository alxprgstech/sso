/**
 * Экспорт текущего набора резервных кодов в TXT.
 * Коды не сохраняются в браузерном хранилище и не покидают вкладку:
 * файл формируется в памяти по действию пользователя.
 */

const INSTRUCTION = [
  "ИНСТРУКЦИЯ",
  "",
  "1. Эти коды используются для подтверждения",
  "   входа, если обычный второй фактор недоступен.",
  "",
  "2. Каждый код можно использовать только один раз.",
  "",
  "3. Для входа также может потребоваться пароль.",
  "",
  "4. При создании нового набора предыдущие",
  "   резервные коды становятся недействительными.",
  "",
  "5. Храните файл в защищённом месте,",
  "   желательно в зашифрованном хранилище.",
  "",
  "6. Никому не сообщайте резервные коды.",
].join("\n");

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Локальные дата и время в формате ДД.ММ.ГГГГ ЧЧ:ММ. */
export function formatRecoveryCodesDate(date: Date): string {
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Имя файла по локальной дате: alxprgs-sso-recovery-codes-YYYY-MM-DD.txt. */
export function recoveryCodesFileName(date: Date): string {
  return `alxprgs-sso-recovery-codes-${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}.txt`;
}

/**
 * Содержимое TXT с UTF-8 BOM для совместимости с Windows.
 * Полный набор кодов выводится без изменений и в исходном порядке.
 */
export function buildRecoveryCodesTxt(
  email: string,
  codes: string[],
  createdAt: Date = new Date(),
): string {
  return [
    "\uFEFFALXPRGS SSO — Резервные коды восстановления",
    "",
    `Учётная запись: ${email}`,
    `Дата создания: ${formatRecoveryCodesDate(createdAt)}`,
    "",
    "ВНИМАНИЕ: этот TXT-файл не зашифрован.",
    "",
    "РЕЗЕРВНЫЕ КОДЫ",
    "",
    ...codes,
    "",
    INSTRUCTION,
    "",
  ].join("\n");
}

/** Скачивание всех кодов текущего набора через Blob и object URL. */
export function downloadRecoveryCodesTxt(
  email: string,
  codes: string[],
  createdAt: Date = new Date(),
): string {
  const fileName = recoveryCodesFileName(createdAt);
  const blob = new Blob([buildRecoveryCodesTxt(email, codes, createdAt)], {
    type: "text/plain;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
  return fileName;
}
