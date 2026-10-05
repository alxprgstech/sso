import {
  forwardRef,
  useId,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import {
  Check,
  Copy,
  Eye,
  EyeOff,
  LoaderCircle,
  AlertCircle,
} from "lucide-react";

export function cx(...values: Array<string | false | undefined>) {
  return values.filter(Boolean).join(" ");
}
export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "secondary" | "ghost" | "danger";
    loading?: boolean;
  }
>(function Button(
  {
    variant = "secondary",
    loading,
    disabled,
    className,
    children,
    type = "button",
    ...props
  },
  ref,
) {
  return (
    <button
      {...props}
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx("ui-button", `ui-${variant}`, className)}
    >
      {loading && (
        <LoaderCircle className="loading-icon" size={18} aria-hidden="true" />
      )}
      {children}
    </button>
  );
});
export const IconButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string }
>(function IconButton({ label, className, ...props }, ref) {
  return (
    <Button
      {...props}
      ref={ref}
      aria-label={label}
      className={cx("icon-button", className)}
    />
  );
});
export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(function Input({ className, ...props }, ref) {
  return <input {...props} ref={ref} className={cx("ui-input", className)} />;
});
export const PasswordInput = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(function PasswordInput({ className, ...props }, ref) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="password-control">
      <Input
        {...props}
        ref={ref}
        type={visible ? "text" : "password"}
        className={cx("pr-12", className)}
      />
      <IconButton
        label={visible ? "Скрыть пароль" : "Показать пароль"}
        aria-pressed={visible}
        disabled={props.disabled}
        onClick={() => setVisible(!visible)}
      >
        {visible ? (
          <EyeOff size={18} aria-hidden="true" />
        ) : (
          <Eye size={18} aria-hidden="true" />
        )}
      </IconButton>
    </div>
  );
});
export function OTPInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <Input
      inputMode="numeric"
      autoComplete="one-time-code"
      pattern="[0-9]{6}"
      maxLength={6}
      {...props}
      className={cx("otp-input", props.className)}
    />
  );
}
export function Field({
  label,
  description,
  error,
  children,
  id,
}: {
  label: string;
  description?: string;
  error?: string;
  id: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children}
      {description && (
        <p id={`${id}-description`} className="field-description">
          {description}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
export function Select({
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx("ui-input", className)} />;
}
export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx("ui-input", className)} />;
}
export function Checkbox(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      type="checkbox"
      className={cx("ui-check", props.className)}
    />
  );
}
export function Radio(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      type="radio"
      className={cx("ui-check", props.className)}
    />
  );
}
export function Alert({
  children,
  tone = "danger",
}: {
  children: ReactNode;
  tone?: "danger" | "success" | "warning" | "info";
}) {
  return (
    <div
      className={`ui-alert alert-${tone}`}
      role={tone === "danger" ? "alert" : "status"}
    >
      <AlertCircle size={18} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  return <span className={`ui-badge badge-${tone}`}>{children}</span>;
}
export function Skeleton({
  label = "Загрузка",
  rows = 3,
}: {
  label?: string;
  rows?: number;
}) {
  return (
    <div role="status" aria-label={label} className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="ui-skeleton" />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}
export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <p className="text-base font-semibold text-primary">{title}</p>
      {children && <p>{children}</p>}
    </div>
  );
}
export function CopyButton({
  value,
  label = "Копировать",
}: {
  value: string;
  label?: string;
}) {
  const [message, setMessage] = useState("");
  const id = useId();
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setMessage("Скопировано");
    } catch {
      setMessage("Копирование недоступно. Выделите текст вручную.");
    }
  }
  return (
    <span>
      <Button onClick={() => void copy()} aria-describedby={id}>
        {message === "Скопировано" ? (
          <Check size={16} aria-hidden="true" />
        ) : (
          <Copy size={16} aria-hidden="true" />
        )}
        {label}
      </Button>
      <span id={id} role="status" className="field-description">
        {message}
      </span>
    </span>
  );
}
