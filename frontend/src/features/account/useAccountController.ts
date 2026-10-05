import { useParams } from "react-router";
import React, { useEffect, useRef, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { useFeedback } from "../../components/ui/Feedback";
import { api } from "../../api/client";
import { errorMessage } from "../../utils/error";
import type { SessionInfo, TOTPSetupResponse } from "../../types/api";
import {
  prepareCreationOptions,
  serializeCreationResponse,
} from "../../utils/webauthn";
export function useAccountController() {
  const { section = "profile" } = useParams();
  const { user, capabilities, refreshUser } = useAuth();

  const { confirm, notify } = useFeedback();
  const [pageError, setPageError] = useState("");
  // Состояние смены пароля
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const passwordTriggerRef = useRef<HTMLButtonElement>(null);
  const currentPasswordRef = useRef<HTMLInputElement>(null);

  const closePasswordModal = () => {
    if (passwordLoading) return;
    setShowPasswordModal(false);
    setPasswordError(null);
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    window.setTimeout(() => passwordTriggerRef.current?.focus(), 0);
  };

  // Состояние сессий
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // Состояние Passkeys (G4-PASSKEY)
  const [passkeys, setPasskeys] = useState<
    Array<{ id: string; name: string; sign_count: number }>
  >([]);
  const [passkeyName, setPasskeyName] = useState("");
  const [passkeyLoading, setPasskeyLoading] = useState(false);
  const [passkeySuccess, setPasskeySuccess] = useState<string | null>(null);
  const [passkeyError, setPasskeyError] = useState<string | null>(null);
  const [passkeysReadState, setPasskeysReadState] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");

  // Состояние TOTP (SEC-FLAG-01)
  const [totpSetupData, setTotpSetupData] = useState<TOTPSetupResponse | null>(
    null,
  );
  const [totpCode, setTotpCode] = useState("");
  const [totpLoading, setTotpLoading] = useState(false);
  const [totpSuccess, setTotpSuccess] = useState<string | null>(null);
  const [totpError, setTotpError] = useState<string | null>(null);
  const [totpCopyMessage, setTotpCopyMessage] = useState<string | null>(null);

  // Состояние Recovery Codes (SEC-FLAG-02)
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const [recoverySuccess, setRecoverySuccess] = useState<string | null>(null);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);

  // Состояние Email Verification (SEC-FLAG-07)
  const [emailToken, setEmailToken] = useState("");
  const [emailLoading, setEmailLoading] = useState(false);
  const [emailSuccess, setEmailSuccess] = useState<string | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);

  const handleSetupTotp = async () => {
    setTotpLoading(true);
    setTotpError(null);
    setTotpSuccess(null);
    setTotpCopyMessage(null);
    try {
      const data = await api.setupTotp();
      setTotpSetupData(data);
    } catch (err: unknown) {
      setTotpError(errorMessage(err, "Не удалось настроить TOTP"));
    } finally {
      setTotpLoading(false);
    }
  };

  const handleCopyTotpSecret = async () => {
    if (!totpSetupData) return;
    try {
      await navigator.clipboard.writeText(totpSetupData.secret);
      setTotpCopyMessage("Ключ скопирован");
    } catch {
      setTotpCopyMessage(
        "Не удалось скопировать ключ. Выделите его и скопируйте вручную.",
      );
    }
  };

  const handleConfirmTotp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!totpCode.trim()) return;
    setTotpLoading(true);
    setTotpError(null);
    try {
      const res = await api.confirmTotp(totpCode.trim());
      setTotpSuccess(res.message || "TOTP успешно активирован");
      setTotpSetupData(null);
      setTotpCode("");
      setTotpCopyMessage(null);
      await refreshUser();
    } catch (err: unknown) {
      setTotpError(errorMessage(err, "Неверный код TOTP"));
    } finally {
      setTotpLoading(false);
    }
  };

  const handleDeleteTotp = async () => {
    if (
      !(await confirm(
        "Вы уверены, что хотите отключить TOTP? Связанные резервные коды также будут отозваны.",
      ))
    )
      return;
    setTotpLoading(true);
    setTotpError(null);
    try {
      const res = await api.deleteTotp();
      setTotpSuccess(res.message || "TOTP успешно отключен");
      setTotpSetupData(null);
      setRecoveryCodes(null);
      await refreshUser();
    } catch (err: unknown) {
      setTotpError(errorMessage(err, "Ошибка при отключении TOTP"));
    } finally {
      setTotpLoading(false);
    }
  };

  const handleGenerateRecoveryCodes = async () => {
    setRecoveryLoading(true);
    setRecoveryError(null);
    setRecoverySuccess(null);
    try {
      const data = await api.generateRecoveryCodes();
      setRecoveryCodes(data.recovery_codes);
      setRecoverySuccess(
        "Резервные коды успешно сформированы. Сохраните их в безопасном месте!",
      );
    } catch (err: unknown) {
      setRecoveryError(errorMessage(err, "Ошибка генерации резервных кодов"));
    } finally {
      setRecoveryLoading(false);
    }
  };

  const handleRequestEmailVerification = async () => {
    setEmailLoading(true);
    setEmailError(null);
    setEmailSuccess(null);
    try {
      const res = await api.requestEmailVerification();
      setEmailSuccess(res.message || "Письмо с подтверждением отправлено");
    } catch (err: unknown) {
      setEmailError(errorMessage(err, "Ошибка отправки подтверждения"));
    } finally {
      setEmailLoading(false);
    }
  };

  const handleConfirmEmailVerification = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user || !emailToken.trim()) return;
    setEmailLoading(true);
    setEmailError(null);
    setEmailSuccess(null);
    try {
      const res = await api.confirmEmailCode(user.email, emailToken.trim());
      setEmailSuccess(res.message || "Email успешно подтвержден!");
      setEmailToken("");
      await refreshUser();
    } catch (err: unknown) {
      setEmailError(
        errorMessage(err, "Неверный или просроченный код подтверждения"),
      );
    } finally {
      setEmailLoading(false);
    }
  };

  const fetchSessions = async () => {
    setSessionError(null);
    setSessionsLoading(true);
    try {
      const data = await api.getSessions();
      setSessions(data);
    } catch (err: unknown) {
      setSessionError(errorMessage(err, "Не удалось загрузить список сессий"));
    } finally {
      setSessionsLoading(false);
    }
  };

  const fetchPasskeys = async () => {
    if (!capabilities?.passkey_enabled) return;
    setPasskeysReadState("loading");
    try {
      const data = await api.getPasskeyCredentials();
      setPasskeys(data);
      setPasskeysReadState("ready");
    } catch {
      setPasskeysReadState("error");
    }
  };

  useEffect(() => {
    if (section === "sessions") void fetchSessions();
    if (section === "security") void fetchPasskeys();
    setTotpSetupData(null);
    setRecoveryCodes(null);
    setTotpCode("");
    setEmailToken("");
    setShowPasswordModal(false);
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
  }, [section, capabilities?.passkey_enabled]);

  const handleRegisterPasskey = async () => {
    setPasskeyLoading(true);
    setPasskeyError(null);
    setPasskeySuccess(null);
    try {
      const serverOptions = await api.getPasskeyRegistrationOptions();
      const creationOptions = prepareCreationOptions(serverOptions);
      const credential = await navigator.credentials.create(creationOptions);
      if (!credential) {
        throw new Error("Аутентификатор не вернул учетные данные");
      }
      const serialized = serializeCreationResponse(credential);
      const res = await api.verifyPasskeyRegistration(
        serialized,
        passkeyName.trim() || "Passkey",
      );
      setPasskeySuccess(res.message || "Passkey успешно зарегистрирован");
      setPasskeyName("");
      await fetchPasskeys();
    } catch (err: unknown) {
      setPasskeyError(errorMessage(err, "Ошибка при регистрации Passkey"));
    } finally {
      setPasskeyLoading(false);
    }
  };

  const handleDeletePasskey = async (id: string) => {
    const key = passkeys.find((item) => item.id === id);
    if (
      !(await confirm(
        `Удалить ключ доступа «${key?.name || "Ключ доступа"}»? Вход с ним станет недоступен.`,
      ))
    )
      return;
    setPasskeyLoading(true);
    setPasskeyError(null);
    setPasskeySuccess(null);
    try {
      await api.deletePasskeyCredential(id);
      setPasskeySuccess("Passkey успешно удален");
      await fetchPasskeys();
    } catch (err: unknown) {
      setPasskeyError(errorMessage(err, "Ошибка при удалении Passkey"));
    } finally {
      setPasskeyLoading(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError(null);
    setPasswordSuccess(null);

    if (newPassword !== confirmPassword) {
      setPasswordError("Новые пароли не совпадают");
      return;
    }
    if (newPassword.length < 15) {
      setPasswordError("Пароль должен содержать минимум 15 символов");
      return;
    }

    setPasswordLoading(true);
    try {
      const res = await api.changePassword(currentPassword, newPassword);
      setPasswordSuccess(res.message || "Пароль успешно обновлён");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      await fetchSessions();
      setShowPasswordModal(false);
      window.setTimeout(() => passwordTriggerRef.current?.focus(), 0);
    } catch (err: unknown) {
      setPasswordError(errorMessage(err, "Ошибка смены пароля"));
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleRevokeSession = async (sessionId: string) => {
    try {
      await api.revokeSession(sessionId);
      await fetchSessions();
    } catch (err: unknown) {
      setPageError(errorMessage(err, "Не удалось завершить сессию"));
    }
  };

  const handleRevokeOtherSessions = async () => {
    if (
      !(await confirm(
        "Вы уверены, что хотите завершить все остальные активные сессии?",
      ))
    )
      return;
    try {
      const res = await api.revokeOtherSessions();
      notify(`Отозвано сессий: ${res.revoked_count}`);
      await fetchSessions();
    } catch (err: unknown) {
      setPageError(errorMessage(err, "Не удалось отозвать сессии"));
    }
  };

  return {
    user,
    capabilities,
    pageError,
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    confirmPassword,
    setConfirmPassword,
    passwordSuccess,
    setPasswordSuccess,
    passwordError,
    passwordLoading,
    showPasswordModal,
    setShowPasswordModal,
    passwordTriggerRef,
    currentPasswordRef,
    closePasswordModal,
    sessions,
    sessionsLoading,
    sessionError,
    passkeys,
    passkeyName,
    setPasskeyName,
    passkeyLoading,
    passkeySuccess,
    passkeyError,
    passkeysReadState,
    fetchPasskeys,
    totpSetupData,
    setTotpSetupData,
    totpCode,
    setTotpCode,
    totpLoading,
    totpSuccess,
    totpError,
    totpCopyMessage,
    recoveryCodes,
    recoveryLoading,
    recoverySuccess,
    recoveryError,
    emailToken,
    setEmailToken,
    emailLoading,
    emailSuccess,
    emailError,
    handleSetupTotp,
    handleCopyTotpSecret,
    handleConfirmTotp,
    handleDeleteTotp,
    handleGenerateRecoveryCodes,
    handleRequestEmailVerification,
    handleConfirmEmailVerification,
    handleRegisterPasskey,
    handleDeletePasskey,
    handleChangePassword,
    handleRevokeSession,
    handleRevokeOtherSessions,
  };
}
