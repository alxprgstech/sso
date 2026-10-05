import React from "react";
import { useParams } from "react-router";
import { SectionNavigation } from "../components/SectionNavigation";
import { DataTable, Pagination } from "../components/ui/DataTable";
import { ActionMenu } from "../components/ui/ActionMenu";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  CopyButton,
  Input,
  PasswordInput,
  Radio,
  Select,
  Skeleton,
  Textarea,
} from "../components/ui/controls";
import { AccessibleDialog } from "../components/AccessibleDialog";
import type { AdminClient, AdminUser, AuditEventItem } from "../types/api";
import { useAdminController } from "../features/admin/useAdminController";
export const AdminPage: React.FC = () => {
  const { section } = useParams();
  const {
    openUserModal,
    openClientModal,
    closeUserModal,
    closeClientModal,
    mutationBusy,
    pageError,
    capabilities,
    activeTab,
    usersOffset,
    setUsersOffset,
    users,
    search,
    setSearch,
    usersLoading,
    showCreateUserModal,
    newUsername,
    setNewUsername,
    newEmail,
    setNewEmail,
    newPassword,
    setNewPassword,
    newIsAdmin,
    setNewIsAdmin,
    clients,
    clientsLoading,
    showCreateClientModal,
    newClientName,
    setNewClientName,
    newClientType,
    setNewClientType,
    newClientScopes,
    setNewClientScopes,
    newRedirectUris,
    setNewRedirectUris,
    secretModal,
    setSecretModal,
    auditEvents,
    auditFilter,
    setAuditFilter,
    auditLoading,
    auditOffset,
    setAuditOffset,
    selectedAudit,
    setSelectedAudit,
    auditExporting,
    auditError,
    systemStatus,
    systemLoading,
    selectedMode,
    setSelectedMode,
    adminPassword,
    setAdminPassword,
    modeUpdateMsg,
    modeUpdating,
    loadUsers,
    loadAudit,
    loadSystemStatus,
    handleAuditExport,
    handleCreateUser,
    handleToggleBlock,
    handleRevokeUserSessions,
    handleCreateClient,
    handleRotateSecret,
    handleDeleteClient,
    handleUpdateRegistrationMode,
  } = useAdminController(section);
  return (
    <SectionNavigation mode="admin">
      <div className="admin-page space-y-6">
        {pageError && <Alert>{pageError}</Alert>}
        <header className="mb-6">
          <h1>Административная панель</h1>
          <p className="mt-2 text-secondary">
            Управление инфраструктурой идентификации
          </p>
        </header>
        {activeTab === "overview" && (
          <section className="space-y-6">
            <h2>Обзор системы</h2>
            {systemLoading ? (
              <Skeleton />
            ) : (
              systemStatus && (
                <dl className="grid gap-4 sm:grid-cols-3">
                  <div className="rounded-lg bg-raised p-5">
                    <dt className="text-secondary text-xs">Пользователи</dt>
                    <dd className="text-3xl font-semibold mt-2">
                      {systemStatus.total_users}
                    </dd>
                  </div>
                  <div className="rounded-lg bg-raised p-5">
                    <dt className="text-secondary text-xs">
                      Активные администраторы
                    </dt>
                    <dd className="text-3xl font-semibold mt-2">
                      {systemStatus.total_active_admins}
                    </dd>
                  </div>
                  <div className="rounded-lg bg-raised p-5">
                    <dt className="text-secondary text-xs">
                      Самостоятельная регистрация
                    </dt>
                    <dd className="mt-2">
                      <Badge
                        tone={
                          systemStatus.registration_mode === "open"
                            ? "success"
                            : "neutral"
                        }
                      >
                        {systemStatus.registration_mode === "open"
                          ? "Открыта"
                          : "Закрыта"}
                      </Badge>
                    </dd>
                  </div>
                </dl>
              )
            )}
            <div>
              <h3>Возможности безопасности</h3>
              <div className="flex flex-wrap gap-3 mt-3">
                {[
                  ["Ключи доступа", capabilities?.passkey_enabled],
                  ["Двухфакторная аутентификация", capabilities?.totp_enabled],
                  ["Коды восстановления", capabilities?.recovery_codes_enabled],
                ].map(([name, enabled]) => (
                  <Badge
                    key={String(name)}
                    tone={enabled ? "success" : "neutral"}
                  >
                    {String(name)}: {enabled ? "доступно" : "выключено"}
                  </Badge>
                ))}
              </div>
            </div>
            <div>
              <h3 className="mb-4">Последние события безопасности</h3>
              <DataTable
                caption="Последние события"
                columns={[
                  {
                    id: "type",
                    label: "Событие",
                    render: (event: AuditEventItem) => (
                      <span className="font-mono text-xs">
                        {event.event_type}
                      </span>
                    ),
                  },
                  {
                    id: "time",
                    label: "Время",
                    render: (event: AuditEventItem) =>
                      new Date(event.created_at).toLocaleString("ru-RU"),
                  },
                ]}
                rows={auditEvents.slice(0, 8)}
                rowKey={(event) => event.id}
                loading={auditLoading}
                error={auditError}
                empty="Событий пока нет"
              />
            </div>
            <p className="text-xs text-secondary">
              Сборка{" "}
              {typeof __BUILD_IDENTITY__ === "undefined"
                ? "тестовый стенд"
                : __BUILD_IDENTITY__.version}
            </p>
          </section>
        )}
        {activeTab === "sessions" && (
          <section className="space-y-4">
            <h2>Сессии пользователей</h2>
            <p className="text-secondary">
              Выберите пользователя, чтобы завершить все его сессии. Список
              устройств доступен владельцу в личном кабинете.
            </p>
            <DataTable
              caption="Управление сессиями пользователей"
              columns={[
                {
                  id: "user",
                  label: "Пользователь",
                  render: (u: AdminUser) => u.username,
                  sortValue: (u) => u.username,
                },
                {
                  id: "email",
                  label: "Email",
                  render: (u: AdminUser) => u.email,
                },
                {
                  id: "actions",
                  label: "Действия",
                  render: (u: AdminUser) => (
                    <Button
                      variant="danger"
                      onClick={() => void handleRevokeUserSessions(u.id)}
                    >
                      Отозвать сессии
                    </Button>
                  ),
                },
              ]}
              rows={users}
              error={pageError || undefined}
              rowKey={(u) => u.id}
              loading={usersLoading}
            />
            <Pagination
              offset={usersOffset}
              size={50}
              count={users.length}
              loading={usersLoading}
              onChange={setUsersOffset}
            />
          </section>
        )}
        {![
          "overview",
          "users",
          "clients",
          "sessions",
          "audit",
          "system",
        ].includes(activeTab) && (
          <section>
            <h2>Раздел не найден</h2>
            <p>Выберите раздел в навигации.</p>
          </section>
        )}
        {/* ========================================================================= */}
        {/* 1. ВКЛАДКА ПОЛЬЗОВАТЕЛИ */}
        {/* ========================================================================= */}
        {activeTab === "users" && (
          <div className="section-panel space-y-4">
            <div className="flex flex-wrap gap-3 justify-between items-center">
              <div className="w-72">
                <Input
                  type="text"
                  value={search}
                  onChange={(e) => {
                    setUsersOffset(0);
                    setSearch(e.target.value);
                  }}
                  onKeyDown={(e) => e.key === "Enter" && loadUsers()}
                  aria-label="Поиск пользователей"
                  placeholder="Поиск по логину или email..."
                  className="w-full"
                />
              </div>
              <Button onClick={openUserModal} variant="primary">
                Добавить пользователя
              </Button>
            </div>

            {usersLoading ? (
              <Skeleton label="Загрузка пользователей" />
            ) : (
              <>
                <DataTable
                  caption="Пользователи"
                  error={pageError || undefined}
                  rows={users}
                  rowKey={(u) => u.id}
                  columns={[
                    {
                      id: "name",
                      label: "Пользователь",
                      render: (u: AdminUser) => <strong>{u.username}</strong>,
                      sortValue: (u) => u.username,
                    },
                    {
                      id: "email",
                      label: "Email",
                      render: (u: AdminUser) => u.email,
                      sortValue: (u) => u.email,
                    },
                    {
                      id: "roles",
                      label: "Роли",
                      render: (u: AdminUser) => (
                        <div className="flex flex-wrap gap-1">
                          {u.roles.map((role) => (
                            <Badge key={role}>{role}</Badge>
                          ))}
                        </div>
                      ),
                    },
                    {
                      id: "status",
                      label: "Статус",
                      render: (u: AdminUser) => (
                        <Badge tone={u.is_active ? "success" : "danger"}>
                          {u.is_active ? "Активен" : "Заблокирован"}
                        </Badge>
                      ),
                    },
                    {
                      id: "actions",
                      label: "Действия",
                      render: (u: AdminUser) => (
                        <ActionMenu
                          label={`Действия: ${u.username}`}
                          actions={[
                            {
                              label: u.is_active
                                ? "Заблокировать"
                                : "Разблокировать",
                              danger: u.is_active,
                              run: () => void handleToggleBlock(u),
                            },
                            {
                              label: "Отозвать сессии",
                              danger: true,
                              run: () => void handleRevokeUserSessions(u.id),
                            },
                          ]}
                        />
                      ),
                    },
                  ]}
                />
                <Pagination
                  offset={usersOffset}
                  size={50}
                  count={users.length}
                  loading={usersLoading}
                  onChange={setUsersOffset}
                />
              </>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* 2. ВКЛАДКА OIDC КЛИЕНТЫ */}
        {/* ========================================================================= */}
        {activeTab === "clients" && (
          <div className="section-panel space-y-4">
            <div className="flex flex-wrap gap-3 justify-between items-center">
              <div>
                <h2 className="text-lg font-bold text-primary">
                  Зарегистрированные OIDC приложения
                </h2>
                <p className="text-xs text-secondary">
                  Клиенты Single Sign-On (Authorization Code + PKCE)
                </p>
              </div>
              <Button onClick={openClientModal} variant="primary">
                Зарегистрировать клиента
              </Button>
            </div>

            {clientsLoading ? (
              <Skeleton label="Загрузка приложений" />
            ) : (
              <DataTable
                caption="Приложения"
                rows={clients}
                error={pageError || undefined}
                rowKey={(c) => c.id}
                columns={[
                  {
                    id: "name",
                    label: "Название",
                    render: (c: AdminClient) => (
                      <strong>{c.client_name}</strong>
                    ),
                    sortValue: (c) => c.client_name,
                  },
                  {
                    id: "id",
                    label: "Client ID",
                    render: (c: AdminClient) => (
                      <span className="font-mono text-xs">{c.client_id}</span>
                    ),
                  },
                  {
                    id: "type",
                    label: "Тип",
                    render: (c: AdminClient) => <Badge>{c.client_type}</Badge>,
                  },
                  {
                    id: "redirect",
                    label: "Redirect URIs",
                    render: (c: AdminClient) => (
                      <ul className="font-mono text-xs space-y-1">
                        {c.redirect_uris.map((uri) => (
                          <li key={uri}>{uri}</li>
                        ))}
                      </ul>
                    ),
                  },
                  {
                    id: "actions",
                    label: "Действия",
                    render: (c: AdminClient) => (
                      <ActionMenu
                        label={`Действия: ${c.client_name}`}
                        actions={[
                          ...(c.client_type === "confidential"
                            ? [
                                {
                                  label: "Сменить секрет",
                                  run: () =>
                                    void handleRotateSecret(c.client_id),
                                },
                              ]
                            : []),
                          {
                            label: "Удалить",
                            danger: true,
                            run: () => void handleDeleteClient(c.client_id),
                          },
                        ]}
                      />
                    ),
                  },
                ]}
              />
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* 3. ВКЛАДКА АУДИТ */}
        {/* ========================================================================= */}
        {activeTab === "audit" && (
          <div className="section-panel space-y-4">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
              <h2 className="text-lg font-bold text-primary">
                Журнал событий безопасности (Audit Log)
              </h2>
              <div className="flex gap-2 w-full sm:w-auto">
                <Input
                  type="text"
                  aria-label="Фильтр аудита"
                  placeholder="Фильтр по типу события или IP..."
                  value={auditFilter}
                  onChange={(e) => {
                    setAuditOffset(0);
                    setAuditFilter(e.target.value);
                  }}
                  className="w-full sm:w-64"
                  data-testid="audit-filter-input"
                />
                <Button onClick={loadAudit} disabled={auditLoading}>
                  Обновить
                </Button>
                <Button
                  onClick={() => handleAuditExport("jsonl")}
                  disabled={auditExporting}
                  variant="primary"
                >
                  Скачать JSONL
                </Button>
                <Button
                  onClick={() => handleAuditExport("csv")}
                  disabled={auditExporting}
                  variant="primary"
                >
                  Скачать CSV
                </Button>
              </div>
            </div>
            {auditError && (
              <div role="alert" className="text-sm text-danger">
                {auditError}
              </div>
            )}
            {auditLoading ? (
              <Skeleton label="Загрузка аудита" />
            ) : (
              <DataTable
                caption="Аудит"
                rows={auditEvents}
                error={auditError}
                rowKey={(e) => e.id}
                empty="События не найдены"
                columns={[
                  {
                    id: "time",
                    label: "Время",
                    render: (e: AuditEventItem) =>
                      new Date(e.created_at).toLocaleString("ru-RU"),
                    sortValue: (e) => e.created_at,
                  },
                  {
                    id: "type",
                    label: "Тип события",
                    render: (e: AuditEventItem) => (
                      <span className="font-mono text-xs">{e.event_type}</span>
                    ),
                    sortValue: (e) => e.event_type,
                  },
                  {
                    id: "ip",
                    label: "IP адрес",
                    render: (e: AuditEventItem) => (
                      <span className="font-mono text-xs">
                        {e.ip_address || "—"}
                      </span>
                    ),
                  },
                  {
                    id: "details",
                    label: "Детали",
                    render: (e: AuditEventItem) => (
                      <Button onClick={() => setSelectedAudit(e)}>
                        Показать детали
                      </Button>
                    ),
                  },
                ]}
              />
            )}
            <div className="flex items-center gap-3 text-sm">
              <Button
                type="button"
                disabled={auditOffset === 0 || auditLoading}
                onClick={() => setAuditOffset(Math.max(0, auditOffset - 50))}
              >
                Назад
              </Button>
              <span>Страница {Math.floor(auditOffset / 50) + 1}</span>
              <Button
                type="button"
                disabled={auditEvents.length < 50 || auditLoading}
                onClick={() => setAuditOffset(auditOffset + 50)}
              >
                Далее
              </Button>
            </div>
          </div>
        )}

        {selectedAudit && (
          <div
            className="contents"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setSelectedAudit(null);
            }}
          >
            <AccessibleDialog
              label="Детали события аудита"
              onClose={() => setSelectedAudit(null)}
              className="max-w-2xl"
            >
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-lg font-bold">Детали события аудита</h2>
                <Button
                  type="button"
                  onClick={() => setSelectedAudit(null)}
                  aria-label="Закрыть детали"
                >
                  Закрыть
                </Button>
              </div>
              <dl className="text-sm space-y-2">
                <div>
                  <dt className="font-semibold">ID</dt>
                  <dd>{selectedAudit.id}</dd>
                </div>
                <div>
                  <dt className="font-semibold">Время</dt>
                  <dd>
                    {new Date(selectedAudit.created_at).toLocaleString("ru-RU")}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold">Тип</dt>
                  <dd>{selectedAudit.event_type}</dd>
                </div>
                <div>
                  <dt className="font-semibold">Пользователь</dt>
                  <dd>{selectedAudit.user_id || "—"}</dd>
                </div>
                <div>
                  <dt className="font-semibold">IP</dt>
                  <dd>{selectedAudit.ip_address || "—"}</dd>
                </div>
                <div>
                  <dt className="font-semibold">User Agent</dt>
                  <dd className="break-all">
                    {selectedAudit.user_agent || "—"}
                  </dd>
                </div>
                <div>
                  <dt className="font-semibold">Данные</dt>
                  <dd>
                    <pre className="whitespace-pre-wrap break-all bg-canvas rounded p-3">
                      {JSON.stringify(selectedAudit.details, null, 2)}
                    </pre>
                  </dd>
                </div>
              </dl>
            </AccessibleDialog>
          </div>
        )}

        {/* ========================================================================= */}
        {/* 4. ВКЛАДКА КОНФИГУРАЦИЯ СИСТЕМЫ */}
        {/* ========================================================================= */}
        {activeTab === "system" && (
          <div className="space-y-6">
            {/* Блок статуса системы */}
            <div className="section-panel space-y-4">
              <div className="flex justify-between items-center border-b pb-3">
                <h2 className="text-lg font-bold text-primary">
                  Состояние системы ALXPRGS SSO
                </h2>
                <Button onClick={loadSystemStatus} disabled={systemLoading}>
                  {systemLoading ? "Обновление..." : "Обновить статус"}
                </Button>
              </div>

              {systemStatus && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <div className="p-4 bg-canvas rounded-lg border border-line">
                    <div className="text-xs text-secondary font-medium uppercase tracking-wider">
                      Режим регистрации
                    </div>
                    <div className="mt-1 text-lg font-bold">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                          systemStatus.registration_mode === "open"
                            ? "bg-success-soft text-success"
                            : "bg-warning-soft text-warning"
                        }`}
                      >
                        {systemStatus.registration_mode === "open"
                          ? "Открыта (open)"
                          : "Закрыта (closed)"}
                      </span>
                    </div>
                  </div>

                  <div className="p-4 bg-canvas rounded-lg border border-line">
                    <div className="text-xs text-secondary font-medium uppercase tracking-wider">
                      Первичный запуск (Bootstrap)
                    </div>
                    <div className="mt-1 text-sm font-semibold text-primary">
                      {systemStatus.bootstrap_completed
                        ? "Завершён"
                        : "Не завершён"}
                    </div>
                    {systemStatus.bootstrap_completed_at && (
                      <div className="text-xs text-secondary mt-0.5">
                        {new Date(
                          systemStatus.bootstrap_completed_at,
                        ).toLocaleString("ru-RU")}
                      </div>
                    )}
                  </div>

                  <div className="p-4 bg-canvas rounded-lg border border-line">
                    <div className="text-xs text-secondary font-medium uppercase tracking-wider">
                      Всего пользователей
                    </div>
                    <div className="mt-1 text-2xl font-bold text-primary">
                      {systemStatus.total_users}
                    </div>
                  </div>

                  <div className="p-4 bg-canvas rounded-lg border border-line">
                    <div className="text-xs text-secondary font-medium uppercase tracking-wider">
                      Активных администраторов
                    </div>
                    <div className="mt-1 text-2xl font-bold text-brand">
                      {systemStatus.total_active_admins}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Блок управления режимом регистрации */}
            <div className="section-panel space-y-4">
              <h2 className="text-lg font-bold text-primary">
                Управление политикой самостоятельной регистрации (REG-02)
              </h2>
              <p className="text-sm text-secondary leading-relaxed">
                Переключение режима регулирует доступность публичной формы
                регистрации для новых пользователей. Изменение сохраняется
                централизованно в PostgreSQL, моментально действует для всех
                экземпляров и регистрируется в журнале аудита безопасности.
              </p>

              {modeUpdateMsg && (
                <div
                  className={`p-4 rounded-lg text-sm border-l-4 ${
                    modeUpdateMsg.type === "success"
                      ? "bg-success-soft border-success text-success"
                      : "bg-danger-soft border-danger text-danger"
                  }`}
                >
                  {modeUpdateMsg.text}
                </div>
              )}

              <form
                onSubmit={handleUpdateRegistrationMode}
                className="space-y-4 max-w-xl"
              >
                <div>
                  <label className="block text-sm font-medium text-primary mb-2">
                    Выберите желаемый режим регистрации:
                  </label>
                  <div className="space-y-2">
                    <label className="flex items-center space-x-3 p-3 border rounded-lg hover:bg-canvas cursor-pointer">
                      <Radio
                        type="radio"
                        name="registration_mode"
                        value="closed"
                        checked={selectedMode === "closed"}
                        onChange={() => setSelectedMode("closed")}
                        className="text-brand focus:ring-blue-500"
                      />
                      <div>
                        <div className="text-sm font-semibold text-primary">
                          Закрытый режим (closed) — рекомендуется
                        </div>
                        <div className="text-xs text-secondary">
                          Самостоятельная регистрация заблокирована на уровне
                          API. Пользователей создаёт администратор.
                        </div>
                      </div>
                    </label>

                    <label className="flex items-center space-x-3 p-3 border rounded-lg hover:bg-canvas cursor-pointer">
                      <Radio
                        type="radio"
                        name="registration_mode"
                        value="open"
                        checked={selectedMode === "open"}
                        onChange={() => setSelectedMode("open")}
                        className="text-brand focus:ring-blue-500"
                      />
                      <div>
                        <div className="text-sm font-semibold text-primary">
                          Открытый режим (open)
                        </div>
                        <div className="text-xs text-secondary">
                          Свободная регистрация обычных пользователей с защитой
                          от флуда и коллизий.
                        </div>
                      </div>
                    </label>
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="adminpage-field-1"
                    className="block text-sm font-medium text-primary"
                  >
                    Текущий пароль администратора (re-authentication)
                  </label>
                  <PasswordInput
                    id="adminpage-field-1"
                    type="password"
                    required
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    placeholder="Введите ваш пароль для подтверждения смены режима"
                    className="mt-1 w-full"
                  />
                  <p className="mt-1 text-xs text-secondary">
                    В соответствии с инвариантом REG-02 операция защищена
                    повторной аутентификацией администратора.
                  </p>
                </div>

                <div>
                  <Button
                    type="submit"
                    disabled={modeUpdating}
                    variant="primary"
                  >
                    {modeUpdating
                      ? "Применение изменения..."
                      : "Применить режим регистрации"}
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Модальное окно разового показа секрета клиента (USR-09) */}
        {secretModal && (
          <div className="contents">
            <AccessibleDialog
              label="Секрет клиента OIDC"
              onClose={() => setSecretModal(null)}
              className="max-w-lg space-y-4"
            >
              <div className="flex items-center space-x-3 text-warning">
                <h3 className="text-lg font-bold text-primary">
                  Секрет клиента OIDC (Client Secret)
                </h3>
              </div>
              <p className="text-sm text-secondary">
                Секрет генерируется и отображается{" "}
                <strong>только один раз</strong>. Скопируйте и сохраните его в
                безопасном хранилище. В базе данных хранится только необратимый
                хэш.
              </p>
              <div className="bg-raised p-3 rounded-lg border font-mono text-sm break-all select-all text-brand">
                {secretModal.secret}
              </div>
              <CopyButton
                value={secretModal.secret}
                label="Копировать секрет"
              />
              <Button
                onClick={() => setSecretModal(null)}
                className="w-full"
                variant="primary"
              >
                Я сохранил секрет, закрыть
              </Button>
            </AccessibleDialog>
          </div>
        )}

        {/* Модальное окно создания пользователя */}
        {showCreateUserModal && (
          <div className="contents">
            <AccessibleDialog
              label="Новый пользователь"
              busy={mutationBusy}
              onClose={() => closeUserModal()}
              className="max-w-md space-y-4"
            >
              <h3 className="text-lg font-bold text-primary">
                Новый пользователь
              </h3>
              {pageError && <Alert>{pageError}</Alert>}
              <form onSubmit={handleCreateUser} className="space-y-3">
                <fieldset disabled={mutationBusy} className="space-y-3">
                  <div>
                    <label
                      htmlFor="adminpage-field-2"
                      className="block text-xs font-medium text-primary"
                    >
                      Имя пользователя (username)
                    </label>
                    <Input
                      id="adminpage-field-2"
                      minLength={3}
                      maxLength={64}
                      autoComplete="off"
                      type="text"
                      required
                      value={newUsername}
                      onChange={(e) => setNewUsername(e.target.value)}
                      className="mt-1 w-full"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="adminpage-field-3"
                      className="block text-xs font-medium text-primary"
                    >
                      Email
                    </label>
                    <Input
                      id="adminpage-field-3"
                      maxLength={255}
                      autoComplete="off"
                      type="email"
                      required
                      value={newEmail}
                      onChange={(e) => setNewEmail(e.target.value)}
                      className="mt-1 w-full"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="adminpage-field-4"
                      className="block text-xs font-medium text-primary"
                    >
                      Пароль
                    </label>
                    <PasswordInput
                      id="adminpage-field-4"
                      minLength={15}
                      maxLength={128}
                      autoComplete="new-password"
                      type="password"
                      required
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="mt-1 w-full"
                    />
                  </div>
                  <div className="flex items-center space-x-2 pt-2">
                    <Checkbox
                      type="checkbox"
                      id="isAdmin"
                      checked={newIsAdmin}
                      onChange={(e) => setNewIsAdmin(e.target.checked)}
                      className="rounded text-brand"
                    />
                    <label
                      htmlFor="isAdmin"
                      className="text-xs font-medium text-primary"
                    >
                      Назначить администратором (роль admin + superuser)
                    </label>
                  </div>
                  <div className="flex space-x-3 pt-3">
                    <Button
                      type="submit"
                      loading={mutationBusy}
                      className="w-full"
                      variant="primary"
                    >
                      Создать
                    </Button>
                    <Button
                      type="button"
                      onClick={() => closeUserModal()}
                      className="w-full"
                    >
                      Отмена
                    </Button>
                  </div>
                </fieldset>
              </form>
            </AccessibleDialog>
          </div>
        )}

        {/* Модальное окно создания OIDC клиента */}
        {showCreateClientModal && (
          <div className="contents">
            <AccessibleDialog
              label="Регистрация OIDC-клиента"
              busy={mutationBusy}
              onClose={() => closeClientModal()}
              className="max-w-md space-y-4"
            >
              <h3 className="text-lg font-bold text-primary">
                Регистрация OIDC-клиента
              </h3>
              {pageError && <Alert>{pageError}</Alert>}
              <form onSubmit={handleCreateClient} className="space-y-3">
                <fieldset disabled={mutationBusy} className="space-y-3">
                  <div>
                    <label
                      htmlFor="adminpage-field-5"
                      className="block text-xs font-medium text-primary"
                    >
                      Название приложения
                    </label>
                    <Input
                      id="adminpage-field-5"
                      minLength={2}
                      maxLength={128}
                      type="text"
                      required
                      value={newClientName}
                      onChange={(e) => setNewClientName(e.target.value)}
                      placeholder="Портал аналитики"
                      className="mt-1 w-full"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="adminpage-field-6"
                      className="block text-xs font-medium text-primary"
                    >
                      Тип клиента
                    </label>
                    <Select
                      id="adminpage-field-6"
                      value={newClientType}
                      onChange={(e) => setNewClientType(e.target.value)}
                      className="mt-1 w-full"
                    >
                      <option value="confidential">
                        Confidential (с секретом: бэкенд, веб-приложение)
                      </option>
                      <option value="public">
                        Public (без секрета: SPA, мобильное приложение)
                      </option>
                    </Select>
                  </div>
                  <fieldset>
                    <legend className="text-xs font-medium text-primary">
                      Разрешения клиента
                    </legend>
                    <p className="text-xs text-secondary">
                      openid обязателен. Выберите данные, доступные приложению.
                    </p>
                    {["profile", "email"].map((scope) => (
                      <label key={scope} className="mr-4 text-sm">
                        <Checkbox
                          type="checkbox"
                          checked={newClientScopes.includes(scope)}
                          onChange={(event) =>
                            setNewClientScopes((current) =>
                              event.target.checked
                                ? [...current, scope]
                                : current.filter((value) => value !== scope),
                            )
                          }
                        />{" "}
                        {scope === "profile" ? "Профиль" : "Email"}
                      </label>
                    ))}
                  </fieldset>
                  <div>
                    <label
                      htmlFor="adminpage-field-7"
                      className="block text-xs font-medium text-primary"
                    >
                      Разрешенные Redirect URIs (по одному на строку)
                    </label>
                    <Textarea
                      id="adminpage-field-7"
                      required
                      rows={3}
                      value={newRedirectUris}
                      onChange={(e) => setNewRedirectUris(e.target.value)}
                      placeholder="https://app.alxprgs.tech/callback"
                      className="mt-1 w-full"
                    />
                  </div>
                  <div className="flex space-x-3 pt-3">
                    <Button
                      type="submit"
                      loading={mutationBusy}
                      className="w-full"
                      variant="primary"
                    >
                      Зарегистрировать
                    </Button>
                    <Button
                      type="button"
                      onClick={() => closeClientModal()}
                      className="w-full"
                    >
                      Отмена
                    </Button>
                  </div>
                </fieldset>
              </form>
            </AccessibleDialog>
          </div>
        )}
      </div>
    </SectionNavigation>
  );
};
