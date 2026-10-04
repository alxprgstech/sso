import { errorMessage } from "../utils/error";
import React, { useEffect, useState } from "react";
import { AccessibleDialog } from "../components/AccessibleDialog";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { AdminClient, AdminUser, AuditEventItem, SystemStatus } from "../types/api";

export const AdminPage: React.FC = () => {
  const { refreshCapabilities } = useAuth();
  const [activeTab, setActiveTab] = useState<"users" | "clients" | "audit" | "system">("users");

  // --- 1. Пользователи ---
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [search, setSearch] = useState("");
  const [usersLoading, setUsersLoading] = useState(false);

  // Форма создания пользователя
  const [showCreateUserModal, setShowCreateUserModal] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newIsAdmin, setNewIsAdmin] = useState(false);

  // --- 2. OIDC Клиенты ---
  const [clients, setClients] = useState<AdminClient[]>([]);
  const [clientsLoading, setClientsLoading] = useState(false);

  // Создание клиента
  const [showCreateClientModal, setShowCreateClientModal] = useState(false);
  const [newClientName, setNewClientName] = useState("");
  const [newClientType, setNewClientType] = useState("confidential");
  const [newClientScopes, setNewClientScopes] = useState(["openid", "profile", "email"]);
  const [newRedirectUris, setNewRedirectUris] = useState("");

  // Модальное окно разового показа секрета (USR-09)
  const [secretModal, setSecretModal] = useState<{ clientId: string; secret: string } | null>(null);

  // --- 3. Аудит ---
  const [auditEvents, setAuditEvents] = useState<AuditEventItem[]>([]);
  const [auditFilter, setAuditFilter] = useState("");
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditOffset, setAuditOffset] = useState(0);
  const [selectedAudit, setSelectedAudit] = useState<AuditEventItem | null>(null);
  const [auditExporting, setAuditExporting] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);

  // --- 4. Конфигурация системы и режим регистрации ---
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [systemLoading, setSystemLoading] = useState(false);
  const [selectedMode, setSelectedMode] = useState<"closed" | "open">("closed");
  const [adminPassword, setAdminPassword] = useState("");
  const [modeUpdateMsg, setModeUpdateMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [modeUpdating, setModeUpdating] = useState(false);

  // Загрузчики данных
  const loadUsers = async () => {
    setUsersLoading(true);
    try {
      const data = await api.getAdminUsers(0, 50, search || undefined);
      setUsers(data);
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка загрузки пользователей"));
    } finally {
      setUsersLoading(false);
    }
  };

  const loadClients = async () => {
    setClientsLoading(true);
    try {
      const data = await api.getAdminClients();
      setClients(data);
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка загрузки клиентов"));
    } finally {
      setClientsLoading(false);
    }
  };

  const loadAudit = async () => {
    setAuditLoading(true);
    try {
      const data = await api.getAuditEvents(auditOffset, 50, auditFilter);
      setAuditEvents(data);
    } catch (err: unknown) {
      setAuditError(errorMessage(err, "Ошибка загрузки аудита"));
    } finally {
      setAuditLoading(false);
    }
  };

  const loadSystemStatus = async () => {
    setSystemLoading(true);
    try {
      const data = await api.getSystemStatus();
      setSystemStatus(data);
      setSelectedMode(data.registration_mode as "closed" | "open");
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка загрузки состояния системы"));
    } finally {
      setSystemLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === "users") loadUsers();
    if (activeTab === "clients") loadClients();
    if (activeTab === "system") loadSystemStatus();
  }, [activeTab]);

  useEffect(() => {
    if (activeTab === "audit") loadAudit();
  }, [activeTab, auditOffset, auditFilter]);

  const handleAuditExport = async (format: "jsonl" | "csv") => {
    setAuditExporting(true);
    setAuditError(null);
    try {
      await api.downloadAudit(format, auditFilter);
    } catch (err: unknown) {
      setAuditError(errorMessage(err, "Не удалось скачать аудит"));
    } finally {
      setAuditExporting(false);
    }
  };

  // Обработчики пользователей
  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createAdminUser({
        username: newUsername,
        email: newEmail,
        password: newPassword,
        roles: newIsAdmin ? ["admin", "user"] : ["user"],
        is_superuser: newIsAdmin,
      });
      setShowCreateUserModal(false);
      setNewUsername("");
      setNewEmail("");
      setNewPassword("");
      setNewIsAdmin(false);
      await loadUsers();
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка создания пользователя"));
    }
  };

  const handleToggleBlock = async (u: AdminUser) => {
    const actionName = u.is_active ? "заблокировать" : "разблокировать";
    if (!confirm(`Вы действительно хотите ${actionName} пользователя ${u.username}?`)) return;
    try {
      await api.updateAdminUser(u.id, { is_active: !u.is_active });
      await loadUsers();
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка изменения статуса"));
    }
  };

  const handleRevokeUserSessions = async (userId: string) => {
    try {
      const res = await api.revokeUserSessions(userId);
      alert(`Отозвано активных сессий: ${res.revoked_count}`);
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка отзыва сессий"));
    }
  };

  // Обработчики клиентов
  const handleCreateClient = async (e: React.FormEvent) => {
    e.preventDefault();
    const uris = newRedirectUris
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);
    if (uris.length === 0) {
      alert("Укажите хотя бы один Redirect URI");
      return;
    }
    try {
      const res = await api.createAdminClient({
        client_name: newClientName,
        client_type: newClientType,
        allowed_scopes: newClientScopes,
        redirect_uris: uris,
      });
      setShowCreateClientModal(false);
      setNewClientName("");
      setNewRedirectUris("");
      await loadClients();

      if (res.client_secret) {
        setSecretModal({ clientId: res.client_id, secret: res.client_secret });
      }
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка создания клиента"));
    }
  };

  const handleRotateSecret = async (clientId: string) => {
    if (!confirm(`Выпустить новый секрет для клиента ${clientId}? Старый секрет станет недействителен.`)) return;
    try {
      const res = await api.rotateClientSecret(clientId);
      if (res.client_secret) {
        setSecretModal({ clientId: res.client_id, secret: res.client_secret });
      }
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка ротации секрета"));
    }
  };

  const handleDeleteClient = async (clientId: string) => {
    if (!confirm(`Удалить OIDC клиента ${clientId}?`)) return;
    try {
      await api.deleteClient(clientId);
      await loadClients();
    } catch (err: unknown) {
      alert(errorMessage(err, "Ошибка удаления клиента"));
    }
  };

  // Обработчик переключения режима регистрации (REG-02)
  const handleUpdateRegistrationMode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adminPassword) {
      setModeUpdateMsg({
        type: "error",
        text: "Для смены режима регистрации введите пароль администратора (требование безопасности REG-02).",
      });
      return;
    }

    setModeUpdating(true);
    setModeUpdateMsg(null);

    try {
      const updated = await api.updateRegistrationMode(selectedMode, adminPassword);
      setSystemStatus(updated);
      await refreshCapabilities();
      setAdminPassword("");
      setModeUpdateMsg({
        type: "success",
        text: `Режим регистрации успешно изменён на "${updated.registration_mode}". Изменение действует для всех процессов без перезапуска.`,
      });
    } catch (err: unknown) {
      setModeUpdateMsg({
        type: "error",
        text: errorMessage(err, "Ошибка обновления режима регистрации"),
      });
    } finally {
      setModeUpdating(false);
    }
  };

  return (
    <div className="admin-page max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div className="flex justify-between items-center border-b pb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Административная панель</h1>
          <p className="text-sm text-gray-500">Управление пользователями, OIDC-клиентами и аудит безопасности</p>
        </div>

        {/* Табы */}
        <div className="admin-tabs flex gap-3 bg-gray-100 p-1 rounded-lg">
          <button
            onClick={() => setActiveTab("users")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === "users" ? "bg-white text-blue-600 shadow-sm" : "text-gray-600 hover:text-gray-900"
            }`}
          >
            Пользователи
          </button>
          <button
            onClick={() => setActiveTab("clients")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === "clients" ? "bg-white text-blue-600 shadow-sm" : "text-gray-600 hover:text-gray-900"
            }`}
          >
            OIDC Клиенты
          </button>
          <button
            onClick={() => setActiveTab("audit")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === "audit" ? "bg-white text-blue-600 shadow-sm" : "text-gray-600 hover:text-gray-900"
            }`}
          >
            Журнал аудита
          </button>
          <button
            onClick={() => setActiveTab("system")}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === "system" ? "bg-white text-blue-600 shadow-sm" : "text-gray-600 hover:text-gray-900"
            }`}
          >
            Конфигурация
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 1. ВКЛАДКА ПОЛЬЗОВАТЕЛИ */}
      {/* ========================================================================= */}
      {activeTab === "users" && (
        <div className="bg-white shadow rounded-xl p-6 border border-gray-100 space-y-4">
          <div className="flex justify-between items-center">
            <div className="w-72">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && loadUsers()}
                placeholder="Поиск по логину или email..."
                className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <button
              onClick={() => setShowCreateUserModal(true)}
              className="py-2 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
            >
              + Добавить пользователя
            </button>
          </div>

          {usersLoading ? (
            <div className="py-8 text-center text-sm text-gray-500">Загрузка пользователей...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Пользователь</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Email</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Роли</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Статус</th>
                    <th className="px-4 py-2 text-right font-medium text-gray-500">Действия</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td className="px-4 py-3 font-semibold text-gray-900">{u.username}</td>
                      <td className="px-4 py-3 text-gray-600">{u.email}</td>
                      <td className="px-4 py-3">
                        <div className="flex space-x-1">
                          {u.roles.map((r) => (
                            <span key={r} className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700">
                              {r}
                            </span>
                          ))}
                          {u.is_superuser && (
                            <span className="px-2 py-0.5 rounded text-xs bg-purple-100 text-purple-800 font-semibold">
                              Admin
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-semibold ${
                            u.is_active ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
                          }`}
                        >
                          {u.is_active ? "Активен" : "Заблокирован"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right space-x-2">
                        <button
                          onClick={() => handleToggleBlock(u)}
                          className={`text-xs font-medium ${
                            u.is_active ? "text-red-600 hover:text-red-800" : "text-green-600 hover:text-green-800"
                          }`}
                        >
                          {u.is_active ? "Заблокировать" : "Разблокировать"}
                        </button>
                        <button
                          onClick={() => handleRevokeUserSessions(u.id)}
                          className="text-xs text-gray-600 hover:text-gray-900 font-medium"
                        >
                          Отозвать сессии
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* 2. ВКЛАДКА OIDC КЛИЕНТЫ */}
      {/* ========================================================================= */}
      {activeTab === "clients" && (
        <div className="bg-white shadow rounded-xl p-6 border border-gray-100 space-y-4">
          <div className="flex justify-between items-center">
            <div>
              <h2 className="text-lg font-bold text-gray-900">Зарегистрированные OIDC приложения</h2>
              <p className="text-xs text-gray-500">Клиенты Single Sign-On (Authorization Code + PKCE)</p>
            </div>
            <button
              onClick={() => setShowCreateClientModal(true)}
              className="py-2 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
            >
              + Зарегистрировать клиента
            </button>
          </div>

          {clientsLoading ? (
            <div className="py-8 text-center text-sm text-gray-500">Загрузка клиентов...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Название</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Client ID</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Тип</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Разрешенные Redirect URIs</th>
                    <th className="px-4 py-2 text-right font-medium text-gray-500">Действия</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {clients.map((c) => (
                    <tr key={c.id}>
                      <td className="px-4 py-3 font-semibold text-gray-900">{c.client_name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-blue-600">{c.client_id}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700 uppercase font-medium">
                          {c.client_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        <ul className="list-disc list-inside">
                          {c.redirect_uris.map((uri) => (
                            <li key={uri} className="font-mono">{uri}</li>
                          ))}
                        </ul>
                      </td>
                      <td className="px-4 py-3 text-right space-x-2">
                        {c.client_type === "confidential" && (
                          <button
                            onClick={() => handleRotateSecret(c.client_id)}
                            className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                          >
                            Сменить секрет
                          </button>
                        )}
                        <button
                          onClick={() => handleDeleteClient(c.client_id)}
                          className="text-xs text-red-600 hover:text-red-800 font-medium"
                        >
                          Удалить
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* 3. ВКЛАДКА АУДИТ */}
      {/* ========================================================================= */}
      {activeTab === "audit" && (
        <div className="bg-white shadow rounded-xl p-6 border border-gray-100 space-y-4">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
            <h2 className="text-lg font-bold text-gray-900">Журнал событий безопасности (Audit Log)</h2>
            <div className="flex gap-2 w-full sm:w-auto">
              <input
                type="text"
                placeholder="Фильтр по типу события или IP..."
                value={auditFilter}
                onChange={(e) => { setAuditOffset(0); setAuditFilter(e.target.value); }}
                className="text-xs border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-500 w-full sm:w-64"
                data-testid="audit-filter-input"
              />
              <button
                onClick={loadAudit}
                disabled={auditLoading}
                className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg whitespace-nowrap"
              >
                Обновить
              </button>
              <button onClick={() => handleAuditExport("jsonl")} disabled={auditExporting} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg disabled:opacity-50 whitespace-nowrap">Скачать JSONL</button>
              <button onClick={() => handleAuditExport("csv")} disabled={auditExporting} className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg disabled:opacity-50 whitespace-nowrap">Скачать CSV</button>
            </div>
          </div>
          {auditError && <div role="alert" className="text-sm text-red-700">{auditError}</div>}
          {auditLoading ? (
            <div className="py-8 text-center text-sm text-gray-500">Загрузка журнала аудита...</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Дата и время</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Тип события</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">IP адрес</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-500">Детали</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {auditEvents.map((e) => (
                      <tr key={e.id}>
                        <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">
                          {new Date(e.created_at).toLocaleString("ru-RU")}
                        </td>
                        <td className="px-4 py-2">
                          <span className="font-mono text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-800 font-medium">
                            {e.event_type}
                          </span>
                        </td>
                        <td className="px-4 py-2 font-mono text-xs text-gray-500">{e.ip_address || "—"}</td>
                        <td className="px-4 py-2 font-mono text-xs text-gray-600">
                          <button type="button" onClick={() => setSelectedAudit(e)} className="text-blue-700 underline">Показать детали</button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex items-center gap-3 text-sm">
            <button type="button" disabled={auditOffset === 0 || auditLoading} onClick={() => setAuditOffset(Math.max(0, auditOffset - 50))} className="disabled:opacity-40">Назад</button>
            <span>Страница {Math.floor(auditOffset / 50) + 1}</span>
            <button type="button" disabled={auditEvents.length < 50 || auditLoading} onClick={() => setAuditOffset(auditOffset + 50)} className="disabled:opacity-40">Далее</button>
          </div>
        </div>
      )}

      {selectedAudit && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) setSelectedAudit(null); }}>
          <AccessibleDialog label="Детали события аудита" onClose={() => setSelectedAudit(null)} className="bg-white rounded-xl p-6 w-full max-w-2xl max-h-[85vh] overflow-auto">
            <div className="flex justify-between items-center mb-4"><h2 className="text-lg font-bold">Детали события аудита</h2><button type="button" onClick={() => setSelectedAudit(null)} aria-label="Закрыть детали">✕</button></div>
            <dl className="text-sm space-y-2">
              <div><dt className="font-semibold">ID</dt><dd>{selectedAudit.id}</dd></div>
              <div><dt className="font-semibold">Время</dt><dd>{new Date(selectedAudit.created_at).toLocaleString("ru-RU")}</dd></div>
              <div><dt className="font-semibold">Тип</dt><dd>{selectedAudit.event_type}</dd></div>
              <div><dt className="font-semibold">Пользователь</dt><dd>{selectedAudit.user_id || "—"}</dd></div>
              <div><dt className="font-semibold">IP</dt><dd>{selectedAudit.ip_address || "—"}</dd></div>
              <div><dt className="font-semibold">User Agent</dt><dd className="break-all">{selectedAudit.user_agent || "—"}</dd></div>
              <div><dt className="font-semibold">Данные</dt><dd><pre className="whitespace-pre-wrap break-all bg-gray-50 rounded p-3">{JSON.stringify(selectedAudit.details, null, 2)}</pre></dd></div>
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
          <div className="bg-white shadow rounded-xl p-6 border border-gray-100 space-y-4">
            <div className="flex justify-between items-center border-b pb-3">
              <h2 className="text-lg font-bold text-gray-900">Состояние системы ALXPRGS SSO</h2>
              <button
                onClick={loadSystemStatus}
                disabled={systemLoading}
                className="text-sm text-blue-600 hover:text-blue-800 font-medium"
              >
                {systemLoading ? "Обновление..." : "Обновить статус"}
              </button>
            </div>

            {systemStatus && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                  <div className="text-xs text-gray-500 font-medium uppercase tracking-wider">
                    Режим регистрации
                  </div>
                  <div className="mt-1 text-lg font-bold">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                        systemStatus.registration_mode === "open"
                          ? "bg-green-100 text-green-800"
                          : "bg-amber-100 text-amber-800"
                      }`}
                    >
                      {systemStatus.registration_mode === "open" ? "Открыта (open)" : "Закрыта (closed)"}
                    </span>
                  </div>
                </div>

                <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                  <div className="text-xs text-gray-500 font-medium uppercase tracking-wider">
                    Первичный запуск (Bootstrap)
                  </div>
                  <div className="mt-1 text-sm font-semibold text-gray-900">
                    {systemStatus.bootstrap_completed ? "Завершён" : "Не завершён"}
                  </div>
                  {systemStatus.bootstrap_completed_at && (
                    <div className="text-xs text-gray-500 mt-0.5">
                      {new Date(systemStatus.bootstrap_completed_at).toLocaleString("ru-RU")}
                    </div>
                  )}
                </div>

                <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                  <div className="text-xs text-gray-500 font-medium uppercase tracking-wider">
                    Всего пользователей
                  </div>
                  <div className="mt-1 text-2xl font-bold text-gray-900">
                    {systemStatus.total_users}
                  </div>
                </div>

                <div className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                  <div className="text-xs text-gray-500 font-medium uppercase tracking-wider">
                    Активных администраторов
                  </div>
                  <div className="mt-1 text-2xl font-bold text-blue-600">
                    {systemStatus.total_active_admins}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Блок управления режимом регистрации */}
          <div className="bg-white shadow rounded-xl p-6 border border-gray-100 space-y-4">
            <h2 className="text-lg font-bold text-gray-900">
              Управление политикой самостоятельной регистрации (REG-02)
            </h2>
            <p className="text-sm text-gray-600 leading-relaxed">
              Переключение режима регулирует доступность публичной формы регистрации для новых пользователей.
              Изменение сохраняется централизованно в PostgreSQL, моментально действует для всех экземпляров
              и регистрируется в журнале аудита безопасности.
            </p>

            {modeUpdateMsg && (
              <div
                className={`p-4 rounded-lg text-sm border-l-4 ${
                  modeUpdateMsg.type === "success"
                    ? "bg-green-50 border-green-500 text-green-800"
                    : "bg-red-50 border-red-500 text-red-800"
                }`}
              >
                {modeUpdateMsg.text}
              </div>
            )}

            <form onSubmit={handleUpdateRegistrationMode} className="space-y-4 max-w-xl">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Выберите желаемый режим регистрации:
                </label>
                <div className="space-y-2">
                  <label className="flex items-center space-x-3 p-3 border rounded-lg hover:bg-gray-50 cursor-pointer">
                    <input
                      type="radio"
                      name="registration_mode"
                      value="closed"
                      checked={selectedMode === "closed"}
                      onChange={() => setSelectedMode("closed")}
                      className="text-blue-600 focus:ring-blue-500"
                    />
                    <div>
                      <div className="text-sm font-semibold text-gray-900">
                        Закрытый режим (closed) — рекомендуется
                      </div>
                      <div className="text-xs text-gray-500">
                        Самостоятельная регистрация заблокирована на уровне API. Пользователей создаёт администратор.
                      </div>
                    </div>
                  </label>

                  <label className="flex items-center space-x-3 p-3 border rounded-lg hover:bg-gray-50 cursor-pointer">
                    <input
                      type="radio"
                      name="registration_mode"
                      value="open"
                      checked={selectedMode === "open"}
                      onChange={() => setSelectedMode("open")}
                      className="text-blue-600 focus:ring-blue-500"
                    />
                    <div>
                      <div className="text-sm font-semibold text-gray-900">
                        Открытый режим (open)
                      </div>
                      <div className="text-xs text-gray-500">
                        Свободная регистрация обычных пользователей с защитой от флуда и коллизий.
                      </div>
                    </div>
                  </label>
                </div>
              </div>

              <div>
                <label htmlFor="adminpage-field-1" className="block text-sm font-medium text-gray-700">
                  Текущий пароль администратора (re-authentication)
                </label>
                <input id="adminpage-field-1"
                  type="password"
                  required
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                  placeholder="Введите ваш пароль для подтверждения смены режима"
                  className="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-lg text-sm shadow-sm focus:ring-blue-500 focus:border-blue-500"
                />
                <p className="mt-1 text-xs text-gray-500">
                  В соответствии с инвариантом REG-02 операция защищена повторной аутентификацией администратора.
                </p>
              </div>

              <div>
                <button
                  type="submit"
                  disabled={modeUpdating}
                  className="py-2.5 px-5 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm"
                >
                  {modeUpdating ? "Применение изменения..." : "Применить режим регистрации"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Модальное окно разового показа секрета клиента (USR-09) */}
      {secretModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <AccessibleDialog label="Секрет клиента OIDC" onClose={() => setSecretModal(null)} className="bg-white rounded-xl max-w-lg w-full p-6 shadow-2xl space-y-4 border border-gray-100">
            <div className="flex items-center space-x-3 text-amber-600">
              <span className="text-2xl">⚠️</span>
              <h3 className="text-lg font-bold text-gray-900">Секрет клиента OIDC (Client Secret)</h3>
            </div>
            <p className="text-sm text-gray-600">
              Секрет генерируется и отображается <strong>только один раз</strong>. Скопируйте и сохраните его в безопасном
              хранилище. В базе данных хранится только необратимый хэш.
            </p>
            <div className="bg-gray-100 p-3 rounded-lg border font-mono text-sm break-all select-all text-blue-900">
              {secretModal.secret}
            </div>
            <button
              onClick={() => setSecretModal(null)}
              className="w-full py-2.5 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
            >
              Я сохранил секрет, закрыть
            </button>
          </AccessibleDialog>
        </div>
      )}

      {/* Модальное окно создания пользователя */}
      {showCreateUserModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <AccessibleDialog label="Новый пользователь" onClose={() => setShowCreateUserModal(false)} className="bg-white rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4 border border-gray-100">
            <h3 className="text-lg font-bold text-gray-900">Новый пользователь</h3>
            <form onSubmit={handleCreateUser} className="space-y-3">
              <div>
                <label htmlFor="adminpage-field-2" className="block text-xs font-medium text-gray-700">Имя пользователя (username)</label>
                <input id="adminpage-field-2"
                  type="text"
                  required
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  className="mt-1 block w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div>
                <label htmlFor="adminpage-field-3" className="block text-xs font-medium text-gray-700">Email</label>
                <input id="adminpage-field-3"
                  type="email"
                  required
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  className="mt-1 block w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div>
                <label htmlFor="adminpage-field-4" className="block text-xs font-medium text-gray-700">Пароль</label>
                <input id="adminpage-field-4"
                  type="password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="mt-1 block w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div className="flex items-center space-x-2 pt-2">
                <input
                  type="checkbox"
                  id="isAdmin"
                  checked={newIsAdmin}
                  onChange={(e) => setNewIsAdmin(e.target.checked)}
                  className="rounded text-blue-600"
                />
                <label htmlFor="isAdmin" className="text-xs font-medium text-gray-700">
                  Назначить администратором (роль admin + superuser)
                </label>
              </div>
              <div className="flex space-x-3 pt-3">
                <button
                  type="submit"
                  className="w-full py-2 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
                >
                  Создать
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreateUserModal(false)}
                  className="w-full py-2 px-4 rounded-lg text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200"
                >
                  Отмена
                </button>
              </div>
            </form>
          </AccessibleDialog>
        </div>
      )}

      {/* Модальное окно создания OIDC клиента */}
      {showCreateClientModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <AccessibleDialog label="Регистрация OIDC-клиента" onClose={() => setShowCreateClientModal(false)} className="bg-white rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4 border border-gray-100">
            <h3 className="text-lg font-bold text-gray-900">Регистрация OIDC-клиента</h3>
            <form onSubmit={handleCreateClient} className="space-y-3">
              <div>
                <label htmlFor="adminpage-field-5" className="block text-xs font-medium text-gray-700">Название приложения</label>
                <input id="adminpage-field-5"
                  type="text"
                  required
                  value={newClientName}
                  onChange={(e) => setNewClientName(e.target.value)}
                  placeholder="Портал аналитики"
                  className="mt-1 block w-full px-3 py-2 border rounded-lg text-sm"
                />
              </div>
              <div>
                <label htmlFor="adminpage-field-6" className="block text-xs font-medium text-gray-700">Тип клиента</label>
                <select id="adminpage-field-6"
                  value={newClientType}
                  onChange={(e) => setNewClientType(e.target.value)}
                  className="mt-1 block w-full px-3 py-2 border rounded-lg text-sm"
                >
                  <option value="confidential">Confidential (с секретом: бэкенд, веб-приложение)</option>
                  <option value="public">Public (без секрета: SPA, мобильное приложение)</option>
                </select>
              </div>
              <fieldset><legend className="text-xs font-medium text-gray-700">Разрешения клиента</legend>
                <p className="text-xs text-gray-600">openid обязателен. Выберите данные, доступные приложению.</p>
                {["profile", "email"].map(scope => <label key={scope} className="mr-4 text-sm"><input type="checkbox" checked={newClientScopes.includes(scope)} onChange={event => setNewClientScopes(current => event.target.checked ? [...current, scope] : current.filter(value => value !== scope))} /> {scope === "profile" ? "Профиль" : "Email"}</label>)}
              </fieldset>
              <div>
                <label htmlFor="adminpage-field-7" className="block text-xs font-medium text-gray-700">
                  Разрешенные Redirect URIs (по одному на строку)
                </label>
                <textarea id="adminpage-field-7"
                  required
                  rows={3}
                  value={newRedirectUris}
                  onChange={(e) => setNewRedirectUris(e.target.value)}
                  placeholder="https://app.alxprgs.tech/callback"
                  className="mt-1 block w-full px-3 py-2 border rounded-lg text-sm font-mono"
                />
              </div>
              <div className="flex space-x-3 pt-3">
                <button
                  type="submit"
                  className="w-full py-2 px-4 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-700"
                >
                  Зарегистрировать
                </button>
                <button
                  type="button"
                  onClick={() => setShowCreateClientModal(false)}
                  className="w-full py-2 px-4 rounded-lg text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200"
                >
                  Отмена
                </button>
              </div>
            </form>
          </AccessibleDialog>
        </div>
      )}
    </div>
  );
};
