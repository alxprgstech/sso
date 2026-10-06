import { lazy, Suspense, type ComponentProps } from "react";
import type { Dialog } from "./ui/Dialog";

const LazyDialog = lazy(() =>
  import("./ui/Dialog").then((module) => ({ default: module.Dialog })),
);

// Keep security handlers registered synchronously; load the modal only when shown.
export function DeferredDialog(props: ComponentProps<typeof Dialog>) {
  return (
    <Suspense fallback={<p role="status">Загрузка подтверждения…</p>}>
      <LazyDialog {...props} />
    </Suspense>
  );
}
