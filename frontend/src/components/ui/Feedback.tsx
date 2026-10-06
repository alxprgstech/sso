import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Check, X } from "lucide-react";
import { DeferredDialog as Dialog } from "../DeferredDialog";
import { Button, IconButton } from "./controls";
interface Confirmation {
  message: string;
  resolve: (confirmed: boolean) => void;
}
interface Feedback {
  confirm: (message: string) => Promise<boolean>;
  notify: (message: string) => void;
}
const Context = createContext<Feedback | null>(null);
export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const current = useRef<Confirmation | null>(null);
  const [toast, setToast] = useState("");
  useEffect(
    () => () => {
      current.current?.resolve(false);
    },
    [],
  );
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 5000);
    return () => clearTimeout(timer);
  }, [toast]);
  function finish(value: boolean) {
    current.current?.resolve(value);
    current.current = null;
    setConfirmation(null);
  }
  function confirm(message: string) {
    return new Promise<boolean>((resolve) => {
      if (current.current) {
        resolve(false);
        return;
      }
      const next = { message, resolve };
      current.current = next;
      setConfirmation(next);
    });
  }
  return (
    <Context.Provider value={{ confirm, notify: setToast }}>
      {children}
      {confirmation && (
        <Dialog label="Подтверждение действия" onClose={() => finish(false)}>
          <h2>Подтвердите действие</h2>
          <p className="mt-3 text-secondary">{confirmation.message}</p>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <Button onClick={() => finish(false)} autoFocus>
              Отмена
            </Button>
            <Button variant="danger" onClick={() => finish(true)}>
              Подтвердить
            </Button>
          </div>
        </Dialog>
      )}
      {toast && (
        <div data-sentry-block className="sso-sensitive toast" role="status">
          <Check size={18} aria-hidden="true" />
          <span>{toast}</span>
          <IconButton label="Закрыть уведомление" onClick={() => setToast("")}>
            <X size={16} />
          </IconButton>
        </div>
      )}
    </Context.Provider>
  );
}
export function useFeedback() {
  const value = useContext(Context);
  if (!value) throw new Error("FeedbackProvider required");
  return value;
}
