# ADR-0023 — привязка Gmail action и локальное усиление безопасности

Статус: принято владельцем, Spec Freeze v1, 07.10.2026.

Google bearer подтверждает источник сервиса, а не доступ к конкретному письму. Сохраняем Gmail action с отдельным случайным 32-byte секретом; только SHA-256 хранится в pending registration. Старые action URLs без секрета отвергаются, code/link остаются доступными. Общая блокировка pending атомарно погашает все способы подтверждения. Альтернативы: удалить shortcut (владелец отклонил), использовать UUID как секрет (не обеспечивает mailbox ownership).

Passkey IDs нормализуются в canonical base64url с уникальным индексом, без runtime full scan; миграция при коллизии прерывается без удаления credentials. Session viewing получает отдельный пяти минутный read grant после password/configured MFA; mutations сохраняют одноразовые action/body proofs. Не изменяем OIDC auth_time для просмотра сессий.

Version locks остаются источником версий, hashed companions удостоверяют artifacts. SDK secure transport default; local HTTP только explicit loopback profile, TLS verification обязательна всегда. Security notifications используют PostgreSQL transactional outbox с bounded retry/retention; delivery не участвует в авторизации действия.

Production/CD/live providers, L3 DPoP/mTLS и managed storage/vault остаются за пределами локальной реализации. Исторический аудит не переписывается как успешная приёмка исправленной ревизии.

Уточнение 18.10.2026 по повторной проверке: same-origin Referer fallback применяется к cookie API и mutations. OIDC front-channel GET `/oauth/authorize` и GET `/oauth/logout` допускают Referer-only навигацию от RP, поскольку её предметом является протокольный запрос с проверками client/redirect/PKCE либо signed logout hint/confirmation. Явный чужой Origin по-прежнему отвергается. Альтернатива — общий запрет Referer RP — нарушает SSO; расширение общего allowlist до всех RP необоснованно распространяет доверие на API и отклонено.

Windows private-directory DACL полностью ограничивается текущим владельцем до записи key material: одного удаления inheritance недостаточно из-за explicit ACE. Генератор удаляет сторонние ACE через штатный icacls; генератор и backup validator читают ACL через .NET без зависимости от PSModulePath. Применение Set-Acl в проверенном окружении требовало SeSecurityPrivilege; повышение привилегий отвергнуто. Regression проверяет explicit Everyone ACE и отказ backup при широких правах.
