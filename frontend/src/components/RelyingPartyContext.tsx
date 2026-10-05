import { useEffect, useState } from "react";
import { AppWindow } from "lucide-react";
import { api } from "../api/client";
import { sanitizeReturnTo } from "../utils/security";
import { Alert, Skeleton } from "./ui/controls";

type ClientContext = { client_name: string; redirect_origin: string };

function clientRequest(returnTo: string | null) {
  const safe = sanitizeReturnTo(returnTo);
  if (!safe) return null;
  const url = new URL(safe, window.location.origin);
  if (url.pathname !== "/oauth/authorize") return null;
  const clientId = url.searchParams.get("client_id");
  const redirectUri = url.searchParams.get("redirect_uri");
  if (!clientId || !redirectUri) return null;
  return { clientId, redirectUri };
}

function useClientContext(clientId?: string, redirectUri?: string) {
  const [context, setContext] = useState<ClientContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
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
  return { context, loading, failed };
}

function ClientContextContent({
  context,
  loading,
  failed,
}: {
  context: ClientContext | null;
  loading: boolean;
  failed: boolean;
}) {
  if (loading) return <Skeleton label="Загрузка приложения" rows={1} />;
  if (failed)
    return (
      <Alert tone="warning">
        Не удалось подтвердить сведения о приложении. Проверьте адрес страницы
        входа.
      </Alert>
    );
  if (!context) return null;
  return (
    <div className="flex gap-3 rounded-lg border border-line bg-raised p-4">
      <AppWindow size={20} className="text-brand shrink-0" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-xs text-secondary">Продолжить в приложении</p>
        <p className="font-medium break-words">{context.client_name}</p>
        <p className="text-xs text-secondary break-all">
          {context.redirect_origin}
        </p>
      </div>
    </div>
  );
}

export function RelyingPartyContext({ returnTo }: { returnTo: string | null }) {
  const request = clientRequest(returnTo);
  const state = useClientContext(request?.clientId, request?.redirectUri);
  if (!request) return null;
  return (
    <div className="mb-6">
      <ClientContextContent {...state} />
    </div>
  );
}
