import { useEffect, useState } from "react";
import { AppWindow } from "lucide-react";
import { api } from "../api/client";
import { sanitizeReturnTo } from "../utils/security";
import { Alert, Skeleton } from "./ui/controls";

export function RelyingPartyContext({ returnTo }: { returnTo: string | null }) {
  const [context, setContext] = useState<{
    client_name: string;
    redirect_origin: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const safe = sanitizeReturnTo(returnTo);
  const url = safe ? new URL(safe, window.location.origin) : null;
  const clientId =
    url?.pathname === "/oauth/authorize"
      ? url.searchParams.get("client_id")
      : null;
  const redirectUri = clientId ? url?.searchParams.get("redirect_uri") : null;
  useEffect(() => {
    setContext(null);
    setFailed(false);
    if (!clientId || !redirectUri) return;
    let active = true;
    setLoading(true);
    void api
      .getClientContext(clientId, redirectUri)
      .then((value) => {
        if (active) setContext(value);
      })
      .catch(() => {
        if (active) setFailed(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [clientId, redirectUri]);
  if (!clientId || !redirectUri) return null;
  return (
    <div className="mb-6">
      {loading ? (
        <Skeleton label="Загрузка приложения" rows={1} />
      ) : failed ? (
        <Alert tone="warning">
          Не удалось подтвердить сведения о приложении. Проверьте адрес страницы
          входа.
        </Alert>
      ) : (
        context && (
          <div className="flex gap-3 rounded-lg border border-line bg-raised p-4">
            <AppWindow
              size={20}
              className="text-brand shrink-0"
              aria-hidden="true"
            />
            <div className="min-w-0">
              <p className="text-xs text-secondary">Продолжить в приложении</p>
              <p className="font-medium break-words">{context.client_name}</p>
              <p className="text-xs text-secondary break-all">
                {context.redirect_origin}
              </p>
            </div>
          </div>
        )
      )}
    </div>
  );
}
