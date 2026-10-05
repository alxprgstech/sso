import { lazy, Suspense, useState, type ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { ErrorBoundary } from "@sentry/react";
import { Brand } from "./Brand";
const Infrastructure = lazy(() => import("./Infrastructure"));
export function AuthSurface({
  title,
  description,
  step,
  children,
}: {
  title: string;
  description: string;
  step: string;
  children: ReactNode;
}) {
  const reduced = useReducedMotion();
  const [decorationFailed, setDecorationFailed] = useState(false);
  return (
    <div
      className={
        decorationFailed
          ? "auth-layout auth-layout-without-decoration"
          : "auth-layout"
      }
    >
      <section className="auth-form-region">
        <div className="auth-form">
          <div className="mb-6">
            <Brand variant="auth" />
          </div>
          <motion.div layout={!reduced} transition={{ duration: 0.28 }}>
            <motion.div
              key={step}
              initial={{ opacity: 0, y: reduced ? 0 : 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: reduced ? 0 : 0.22 }}
            >
              <h1 className="auth-heading">{title}</h1>
              <p className="mt-3 mb-8 text-secondary text-base">
                {description}
              </p>
              {children}
            </motion.div>
          </motion.div>
        </div>
      </section>
      {!decorationFailed && (
        <aside className="auth-decoration" aria-hidden="true">
          <ErrorBoundary
            fallback={<></>}
            showDialog={false}
            onError={() => setDecorationFailed(true)}
          >
            <Suspense fallback={null}>
              <Infrastructure />
            </Suspense>
          </ErrorBoundary>
        </aside>
      )}
    </div>
  );
}
