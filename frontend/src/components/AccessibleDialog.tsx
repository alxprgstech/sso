import { useEffect, useRef, type ReactNode, type RefObject } from "react";
const activeDialogs: HTMLElement[] = [];

function controlsIn(dialog: HTMLElement): HTMLElement[] {
  const selector = "button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex='0']";
  return Array.from(dialog.querySelectorAll<HTMLElement>(selector)).filter(element => !element.closest("[hidden]"));
}

function tabDestination(dialog: HTMLElement, backwards: boolean): HTMLElement | undefined {
  const controls = controlsIn(dialog);
  const first = controls[0];
  if (!first) return dialog;
  const last = controls[controls.length - 1];
  if (!dialog.contains(document.activeElement)) return backwards ? last : first;
  if (backwards) return document.activeElement === first ? last : undefined;
  return document.activeElement === last ? first : undefined;
}

function trapTab(event: KeyboardEvent, dialog: HTMLElement) {
  const destination = tabDestination(dialog, event.shiftKey);
  if (!destination) return;
  event.preventDefault();
  destination.focus();
}

function useDialogFocus(onClose: () => void, busy: boolean, initialFocus?: RefObject<HTMLElement>) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); close.current = onClose;
  const loading = useRef(busy); loading.current = busy;
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const underneath = activeDialogs[activeDialogs.length - 1];
    const previousInert = underneath?.inert;
    if (underneath) underneath.inert = true;
    activeDialogs.push(dialog);
    (initialFocus?.current ?? controlsIn(dialog)[0] ?? dialog).focus();
    const key = (event: KeyboardEvent) => {
      if (activeDialogs[activeDialogs.length - 1] !== dialog) return;
      if (event.key === "Tab") trapTab(event, dialog);
      if (event.key !== "Escape") return;
      event.preventDefault(); event.stopPropagation();
      if (!loading.current) close.current();
    };
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("keydown", key, true);
      const index = activeDialogs.indexOf(dialog);
      if (index >= 0) activeDialogs.splice(index, 1);
      if (underneath) underneath.inert = previousInert ?? false;
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return ref;
}

export function AccessibleDialog({ label, onClose, children, className, busy = false, initialFocus }: { label: string; onClose: () => void; children: ReactNode; className: string; busy?: boolean; initialFocus?: RefObject<HTMLElement> }) {
  const ref = useDialogFocus(onClose, busy, initialFocus);
  return <div ref={ref} role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} className={className} onClick={event => event.stopPropagation()}>{children}</div>;
}
