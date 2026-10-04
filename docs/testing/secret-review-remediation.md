# Приватная оценка новых secret-scan сигналов remediation

Codex проверил исходный контекст каждого нового fingerprint. Значения не выводились в журнал/отчёт. Существующая история baseline сохранена; добавлены только точные проверенные fingerprints. Новые сигналы по-прежнему приводят к failed scan, synthetic random-secret control обязан срабатывать. Изменение baseline не свидетельствует о защищённом production secret storage: это отдельная эксплуатационная проверка.

| Файл | Число новых fingerprints | Проверенный контекст |
| --- | --- | --- |
| `.env.example` | 1 | Явный локальный пример DSN; production validator отвергает dev credentials. |
| `backend/app/data/common-passwords-source.json` | 1 | Публичный immutable commit SHA MIT SecLists, не credential. |
| `frontend/e2e/protocol_lifecycle.spec.ts` | 1 | Синтетический пароль созданного owned E2E пользователя. |
| `frontend/e2e/totp.spec.ts` | 1 | Синтетический пароль owned E2E пользователя; не OTP/private key. |
| `frontend/src/utils/security.test.ts` | 1 | Негативный URL с буквальным user/password, ожидается отказ sanitizeReturnTo. |
| `scripts/prepare_e2e_data.py` | 2 | Только явно именованные синтетические E2E fixtures, не рабочие credentials. |
| `scripts/rotate_keys.py` | 1 | Публичный alphabet допустимого kid, не base64 key; настоящий материал генерируется в private output. |
| `tests/integration/test_auth_sessions_pg.py` | 1 | Синтетический пароль из локальной тестовой регистрации. |
| `tests/integration/test_distributed_rate_limiting_pg.py` | 1 | Синтетический пароль в guarded PostgreSQL tests. |
| `tests/integration/test_email_identity_uniqueness_pg.py` | 1 | Явный synthetic password для адресов example.test. |
| `tests/integration/test_oidc_contract_remediation_pg.py` | 3 | Явные synthetic password/client-secret для протокольной регрессии. |
| `tests/integration/test_passkey_pg.py` | 1 | Synthetic password; криптографические ключи создаются библиотекой во время теста. |
| `tests/integration/test_reauthentication_pg.py` | 1 | Synthetic password для проверки bound proof. |
| `tests/integration/test_registration_pg.py` | 2 | Synthetic registration passwords; не реальные данные. |
| `tests/integration/test_security_event_races_pg.py` | 1 | Synthetic credential change для настоящих PG row-lock races. |
| `tests/integration/test_security_revision_pg.py` | 1 | Synthetic password для invalidation regression. |
| `tests/integration/test_totp_key_rotation_pg.py` | 1 | Буквальная повреждённая ciphertext fixture, проверяется отказ/rollback. |
| `tests/test_diagnostic_codes.py` | 1 | Synthetic bootstrap password для request-id корреляции. |
| `tests/test_production_keys.py` | 3 | Неполный malformed PEM, негативный URL user:pass и генерируемый invalid prefix; настоящий ключ генерируется временно. |
| `tests/test_registration.py` | 1 | Synthetic registration password. |
| `tests/test_smtp_tls.py` | 2 | Буквальные synthetic SMTP AUTH credentials у локального TLS стенда; не внешняя учётная запись. |

Историческая необходимость оценки владельцем первоначальных baseline сигналов не объявляется выполненной этой записью. Никакие credentials/ключи из .env, private output или runtime captures не добавлялись в Git.

## Дополнительный публичный doc signal — 2026-10-04T14:35:44.386399+03:00

Codex приватно проверил один новый точный Secret Keyword fingerprint в docs/PRODUCTION_READINESS_AUDIT.md, строка C07: это публичный перечень команд CLI и их результатов, не пароль/ключ/credential. Добавлен только этот exact fingerprint с сохранением всего baseline. В сумме28 source fixture signals и1doc signal; detectors/global exclusions не изменены, random secret self-test обязателен. Историческое owner acceptance остаётся E07.
