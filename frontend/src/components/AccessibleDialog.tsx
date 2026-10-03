import { useEffect, useRef, type ReactNode } from "react";

export function AccessibleDialog({ label, onClose, children, className, busy = false }: { label: string; onClose: () => void; children: ReactNode; className: string; busy?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); close.current = onClose;
  const loading = useRef(busy); loading.current = busy;
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = ref.current;
    const controls = () => Array.from(dialog?.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex='0']") ?? []).filter(element => !element.closest("[hidden]"));
    (controls()[0] ?? dialog)?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); if (!loading.current) close.current(); }
      if (event.key === "Tab") {
        const elements = controls(); const first = elements[0]; const last = elements[elements.length - 1];
        if (!first) { event.preventDefault(); dialog?.focus(); }
        else if (!dialog?.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("keydown", key, true); if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div ref={ref} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} className={className} onClick={event => event.stopPropagation()}>{children}</div>;
}
