import * as Primitive from "@radix-ui/react-dialog";
import {
  useLayoutEffect,
  useState,
  useRef,
  type ReactNode,
  type RefObject,
} from "react";
import { motion, useReducedMotion } from "motion/react";
import { cx } from "./controls";
let mountedDialogs = 0;
let priorInert = false;
const dialogStack: HTMLDivElement[] = [];

export function Dialog({
  label,
  onClose,
  children,
  className,
  busy = false,
  initialFocus,
}: {
  label: string;
  onClose: () => void;
  children: ReactNode;
  className?: string;
  busy?: boolean;
  initialFocus?: RefObject<HTMLElement>;
}) {
  const previous = useRef(
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  );
  const openingPath = useRef(window.location.pathname);
  const [content, setContent] = useState<HTMLDivElement | null>(null);
  const reduced = useReducedMotion();
  useLayoutEffect(() => {
    if (!content) return;
    const shell = document.querySelector<HTMLElement>(".app-shell");
    const element = content;
    if (element) {
      dialogStack.push(element);
      dialogStack.forEach((dialog) => {
        dialog.inert = dialog !== element;
      });
    }
    if (mountedDialogs++ === 0) {
      priorInert = shell?.inert || false;
      if (shell) shell.inert = true;
      document.documentElement.dataset.dialogOpen = "true";
    }
    return () => {
      if (element) {
        const index = dialogStack.indexOf(element);
        if (index >= 0) dialogStack.splice(index, 1);
        dialogStack.forEach((dialog, index) => {
          dialog.inert = index !== dialogStack.length - 1;
        });
      }
      if (--mountedDialogs === 0) {
        if (shell) shell.inert = priorInert;
        delete document.documentElement.dataset.dialogOpen;
      }
    };
  }, [content]);
  return (
    <Primitive.Root
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <Primitive.Portal>
        {/* Modal Content retains Radix focus isolation. A static overlay avoids
        the scroll-lock style tag that conflicts with the enforced CSP. */}
        <div className="dialog-overlay" data-sentry-block aria-hidden="true" />
        <Primitive.Content
          asChild
          aria-describedby={undefined}
          onEscapeKeyDown={(event) => {
            if (busy) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            event.preventDefault();
          }}
          onOpenAutoFocus={(event) => {
            if (initialFocus?.current) {
              event.preventDefault();
              initialFocus.current.focus();
            }
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            // Navigation hands focus to the destination route. Ordinary dismissal
            // still restores the initiating control, including nested dialogs.
            if (
              openingPath.current === window.location.pathname &&
              previous.current?.isConnected
            )
              previous.current.focus();
            window.dispatchEvent(new Event("alxprgs-dialog-closed"));
          }}
        >
          <motion.div
            ref={setContent}
            data-sentry-block
            className={cx("sso-sensitive dialog-content", className)}
            initial={{ opacity: 0, y: reduced ? 0 : 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: reduced ? 0 : 0.24 }}
          >
            <Primitive.Title className="sr-only">{label}</Primitive.Title>
            {children}
          </motion.div>
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
