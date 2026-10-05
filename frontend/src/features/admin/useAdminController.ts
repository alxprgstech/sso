import React, { useEffect, useState, useRef } from "react";
import { useAuth } from "../../context/AuthContext";
import { useFeedback } from "../../components/ui/Feedback";
import { api } from "../../api/client";
import { errorMessage } from "../../utils/error";
import type {
  AdminClient,
  AdminUser,
  AuditEventItem,
  SystemStatus,
} from "../../types/api";

async function loadLatestRequest<T>(request: {
  load: () => Promise<T>;
  isCurrent: () => boolean;
  success: (value: T) => void;
  failure: (error: unknown) => void;
  setLoading: (loading: boolean) => void;
}) {
  request.setLoading(true);
  try {
    const value = await request.load();
    if (request.isCurrent()) request.success(value);
  } catch (error: unknown) {
    if (request.isCurrent()) request.failure(error);
  } finally {
    if (request.isCurrent()) request.setLoading(false);
  }
}

export function useAdminController(section: string | undefined) {
  const { confirm, notify } = useFeedback();
  const [pageError, setPageError] = useState("");
  const [mutationBusy, setMutationBusy] = useState(false);
  const requestIds = useRef({ users: 0, clients: 0, audit: 0, system: 0 });
  const { refreshCapabilities, capabilities } = useAuth();
  const activeTab =
    section === "applications" ? "clients" : section || "overview";
  const [usersOffset, setUsersOffset] = useState(0);

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
  const [newClientScopes, setNewClientScopes] = useState([
    "openid",
    "profile",
    "email",
  ]);
  const [newRedirectUris, setNewRedirectUris] = useState("");

  // Модальное окно разового показа секрета (USR-09)
  const [secretModal, setSecretModal] = useState<{
    clientId: string;
    secret: string;
  } | null>(null);

  // --- 3. Аудит ---
  const [auditEvents, setAuditEvents] = useState<AuditEventItem[]>([]);
  const [auditFilter, setAuditFilter] = useState("");
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditOffset, setAuditOffset] = useState(0);
  const [selectedAudit, setSelectedAudit] = useState<AuditEventItem | null>(
    null,
  );
  const [auditExporting, setAuditExporting] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);

  // --- 4. Конфигурация системы и режим регистрации ---
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [systemLoading, setSystemLoading] = useState(false);
  const [selectedMode, setSelectedMode] = useState<"closed" | "open">("closed");
  const [adminPassword, setAdminPassword] = useState("");
  const [modeUpdateMsg, setModeUpdateMsg] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [modeUpdating, setModeUpdating] = useState(false);

  // Загрузчики данных
  const loadUsers = () => {
    const requestId = ++requestIds.current.users;
    setPageError("");
    return loadLatestRequest({
      load: () => api.getAdminUsers(usersOffset, 50, search || undefined),
      isCurrent: () => requestId === requestIds.current.users,
      success: setUsers,
      failure: (error) => {
        setUsers([]);
        setPageError(errorMessage(error, "Ошибка загрузки пользователей"));
      },
      setLoading: setUsersLoading,
    });
  };

  const loadClients = () => {
    const requestId = ++requestIds.current.clients;
    setPageError("");
    return loadLatestRequest({
      load: () => api.getAdminClients(),
      isCurrent: () => requestId === requestIds.current.clients,
      success: setClients,
      failure: (error) => {
        setClients([]);
        setPageError(errorMessage(error, "Ошибка загрузки клиентов"));
      },
      setLoading: setClientsLoading,
    });
  };

  const loadAudit = () => {
    const requestId = ++requestIds.current.audit;
    setAuditError(null);
    return loadLatestRequest({
      load: () => api.getAuditEvents(auditOffset, 50, auditFilter),
      isCurrent: () => requestId === requestIds.current.audit,
      success: setAuditEvents,
      failure: (error) => {
        setAuditEvents([]);
        setAuditError(errorMessage(error, "Ошибка загрузки аудита"));
      },
      setLoading: setAuditLoading,
    });
  };

  const loadSystemStatus = () => {
    const requestId = ++requestIds.current.system;
    setPageError("");
    return loadLatestRequest({
      load: () => api.getSystemStatus(),
      isCurrent: () => requestId === requestIds.current.system,
      success: (value) => {
        setSystemStatus(value);
        setSelectedMode(value.registration_mode as "closed" | "open");
      },
      failure: (error) => {
        setSystemStatus(null);
        setPageError(errorMessage(error, "Ошибка загрузки состояния системы"));
      },
      setLoading: setSystemLoading,
    });
  };

  useEffect(() => {
    if (activeTab === "users" || activeTab === "sessions") loadUsers();
    if (activeTab === "clients") loadClients();
    if (activeTab === "system" || activeTab === "overview") loadSystemStatus();
  }, [activeTab, usersOffset, search]);

  useEffect(() => {
    if (activeTab === "audit" || activeTab === "overview") loadAudit();
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

  useEffect(
    () => () => {
      Object.keys(requestIds.current).forEach((key) => {
        requestIds.current[key as keyof typeof requestIds.current]++;
      });
    },
    [activeTab],
  );

  useEffect(() => {
    setSecretModal(null);
    setNewPassword("");
    setAdminPassword("");
    setShowCreateUserModal(false);
    setShowCreateClientModal(false);
    setSelectedAudit(null);
  }, [activeTab]);

  // Обработчики пользователей
  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mutationBusy) return;
    setMutationBusy(true);
    setPageError("");
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
      setPageError(errorMessage(err, "Ошибка создания пользователя"));
    } finally {
      setMutationBusy(false);
    }
  };

  const handleToggleBlock = async (u: AdminUser) => {
    const actionName = u.is_active ? "заблокировать" : "разблокировать";
    if (
      !(await confirm(
        `Вы действительно хотите ${actionName} пользователя ${u.username}?`,
      ))
    )
      return;
    try {
      await api.updateAdminUser(u.id, { is_active: !u.is_active });
      await loadUsers();
    } catch (err: unknown) {
      setPageError(errorMessage(err, "Ошибка изменения статуса"));
    }
  };

  const handleRevokeUserSessions = async (userId: string) => {
    if (
      !(await confirm(
        "Завершить все сессии этого пользователя? Ему потребуется войти заново.",
      ))
    )
      return;
    try {
      const res = await api.revokeUserSessions(userId);
      notify(`Отозвано активных сессий: ${res.revoked_count}`);
    } catch (err: unknown) {
      setPageError(errorMessage(err, "Ошибка отзыва сессий"));
    }
  };

  // Обработчики клиентов
  const handleCreateClient = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mutationBusy) return;
    setPageError("");
    const uris = newRedirectUris
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);
    if (uris.length === 0) {
      setPageError("Укажите хотя бы один Redirect URI");
      return;
    }
    setMutationBusy(true);
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
      setPageError(errorMessage(err, "Ошибка создания клиента"));
    } finally {
      setMutationBusy(false);
    }
  };

  const handleRotateSecret = async (clientId: string) => {
    if (
      !(await confirm(
        `Выпустить новый секрет для клиента ${clientId}? Старый секрет станет недействителен.`,
      ))
    )
      return;
    try {
      const res = await api.rotateClientSecret(clientId);
      if (res.client_secret) {
        setSecretModal({ clientId: res.client_id, secret: res.client_secret });
      }
    } catch (err: unknown) {
      setPageError(errorMessage(err, "Ошибка ротации секрета"));
    }
  };

  const handleDeleteClient = async (clientId: string) => {
    if (!(await confirm(`Удалить OIDC клиента ${clientId}?`))) return;
    try {
      await api.deleteClient(clientId);
      await loadClients();
    } catch (err: unknown) {
      setPageError(errorMessage(err, "Ошибка удаления клиента"));
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
      const updated = await api.updateRegistrationMode(
        selectedMode,
        adminPassword,
      );
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

  const openUserModal = () => {
    setPageError("");
    setShowCreateUserModal(true);
  };
  const openClientModal = () => {
    setPageError("");
    setShowCreateClientModal(true);
  };
  const closeUserModal = () => {
    if (!mutationBusy) {
      setShowCreateUserModal(false);
      setNewPassword("");
      setPageError("");
    }
  };
  const closeClientModal = () => {
    if (!mutationBusy) {
      setShowCreateClientModal(false);
      setPageError("");
    }
  };
  return {
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
    setShowCreateUserModal,
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
    setShowCreateClientModal,
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
  };
}
