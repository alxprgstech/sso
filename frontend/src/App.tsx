import { lazy, Suspense, useEffect, useRef } from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router";
import { MotionConfig } from "motion/react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { VerifyEmailPage } from "./pages/VerifyEmailPage";
import { AcceptancePage, LegalPage } from "./pages/LegalPage";
import { AccountDeletionPage } from "./pages/AccountDeletionPage";
import { ForcedPasswordPage } from "./pages/ForcedPasswordPage";
import { ReauthenticationDialog } from "./components/ReauthenticationDialog";
import { AppShell } from "./components/AppShell";
import { Navbar } from "./components/Navbar";
import { FeedbackProvider } from "./components/ui/Feedback";
import { Skeleton } from "./components/ui/controls";
import { navigationBreadcrumb } from "./telemetry/sentry";
import { sessionGate } from "./routing/gates";
const DashboardPage = lazy(() =>
  import("./pages/DashboardPage").then((module) => ({
    default: module.DashboardPage,
  })),
);
const AdminPage = lazy(() =>
  import("./pages/AdminPage").then((module) => ({ default: module.AdminPage })),
);
const CommandPalette = lazy(() =>
  import("./components/CommandPalette").then((module) => ({
    default: module.CommandPalette,
  })),
);
const publicDocuments = ["/privacy", "/terms", "/cookies", "/data-consent"];
function RouteFocus() {
  const location = useLocation();
  const mounted = useRef(false);
  useEffect(() => {
    const shouldFocus = mounted.current;
    mounted.current = true;
    let previousTitle = "";
    let focusedHeading: HTMLElement | null = null;
    navigationBreadcrumb(
      location.pathname.startsWith("/admin")
        ? "admin"
        : location.pathname === "/register"
          ? "register"
          : location.pathname === "/login"
            ? "login"
            : "dashboard",
    );
    const main = document.getElementById("main-content");
    const focusHeading = () => {
      const heading = document.querySelector<HTMLElement>("#main-content h1");
      if (!heading) return false;
      if (heading.textContent !== previousTitle) {
        previousTitle = heading.textContent || "";
        document.title = `${heading.textContent} — ALXPRGS SSO`;
        focusedHeading = null;
      }
      heading.tabIndex = -1;
      if (
        shouldFocus &&
        focusedHeading !== heading &&
        !document.querySelector('[role="dialog"]')
      ) {
        heading.focus({ preventScroll: true });
        if (document.activeElement === heading) focusedHeading = heading;
      }
      return true;
    };
    // Lazy routes and legal/session gates may resolve after this effect.
    const observer = new MutationObserver(focusHeading);
    if (main)
      observer.observe(main, {
        childList: true,
        subtree: true,
        characterData: true,
      });
    const frame = requestAnimationFrame(focusHeading);
    window.addEventListener("alxprgs-dialog-closed", focusHeading);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("alxprgs-dialog-closed", focusHeading);
    };
  }, [location.pathname]);
  return null;
}
function NotFound() {
  return (
    <section className="legal-page">
      <h1>Страница не найдена</h1>
      <p>Проверьте адрес или вернитесь к своей учётной записи.</p>
      <Link className="ui-button ui-secondary" to="/">
        На главную
      </Link>
    </section>
  );
}
function SessionRoutes() {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const gate = sessionGate(user, isLoading, location.pathname, location.search);
  const registration = () => navigate(`/register${location.search}`);
  if (gate === "loading")
    return (
      <section className="legal-page">
        <Skeleton label="Загрузка данных сессии" />
      </section>
    );
  if (gate === "password") return <ForcedPasswordPage />;
  if (gate === "login")
    return (
      <Routes>
        <Route
          path="/register"
          element={
            <RegisterPage
              onNavigateToLogin={() => navigate(`/login${location.search}`)}
            />
          }
        />
        <Route
          path="/"
          element={<LoginPage onNavigateToRegister={registration} />}
        />
        <Route
          path="/login"
          element={<LoginPage onNavigateToRegister={registration} />}
        />
        <Route
          path="/admin/*"
          element={<LoginPage onNavigateToRegister={registration} />}
        />
        <Route
          path="/account/*"
          element={<LoginPage onNavigateToRegister={registration} />}
        />
        <Route
          path="/account-deletion"
          element={<LoginPage onNavigateToRegister={registration} />}
        />
        <Route
          path="/accept-terms"
          element={<LoginPage onNavigateToRegister={registration} />}
        />
        <Route
          path="/change-password"
          element={<LoginPage onNavigateToRegister={registration} />}
        />
        <Route path="*" element={<NotFound />} />
      </Routes>
    );
  if (gate === "deletion") return <AccountDeletionPage />;
  if (gate === "legal") return <AcceptancePage />;
  const admin = Boolean(
    user && (user.is_superuser || user.roles.includes("admin")),
  );
  return (
    <>
      <Navbar />
      <Suspense fallback={null}>
        <CommandPalette />
      </Suspense>
      <Suspense
        fallback={
          <section className="legal-page">
            <Skeleton />
          </section>
        }
      >
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/account/:section" element={<DashboardPage />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="/register" element={<Navigate to="/" replace />} />
          <Route path="/accept-terms" element={<Navigate to="/" replace />} />
          <Route
            path="/change-password"
            element={<Navigate to="/" replace />}
          />
          <Route
            path="/admin"
            element={
              admin ? (
                <AdminPage />
              ) : (
                <section className="legal-page">
                  <h1>Доступ ограничен</h1>
                  <p>Этот раздел доступен администратору.</p>
                </section>
              )
            }
          />
          <Route
            path="/admin/:section"
            element={
              admin ? (
                <AdminPage />
              ) : (
                <section className="legal-page">
                  <h1>Доступ ограничен</h1>
                  <p>Этот раздел доступен администратору.</p>
                </section>
              )
            }
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </>
  );
}
function Content() {
  const { pathname } = useLocation();
  if (publicDocuments.includes(pathname)) return <LegalPage path={pathname} />;
  if (pathname === "/verify-email") return <VerifyEmailPage />;
  return (
    <AuthProvider>
      <SessionRoutes />
      <ReauthenticationDialog />
    </AuthProvider>
  );
}
export function App() {
  return (
    <BrowserRouter>
      <MotionConfig reducedMotion="user" transition={{ duration: 0.22 }}>
        <FeedbackProvider>
          <AppShell>
            <RouteFocus />
            <Content />
          </AppShell>
        </FeedbackProvider>
      </MotionConfig>
    </BrowserRouter>
  );
}
export default App;
