import { expect, test } from "@playwright/test";

// UI contract only: protocol, PKCE, one-use redemption and JWT checks are
// exercised against real PostgreSQL in tests/integration/test_external_step_up_pg.py.
const TOKEN = "abcdefghijklmnopqrstuvwxyz123456"; // pragma: allowlist secret
const USER = {
  id: "11111111-1111-4111-8111-111111111111",
  username: "step_up_e2e",
  email: "step-up-e2e@example.test",
  is_active: true,
  is_superuser: false,
  email_verified: true,
  roles: ["user"],
  has_totp: true,
  has_passkey: false,
  created_at: "2026-10-26T10:00:00+00:00",
  legal_acceptance_required: false,
  deletion_pending: false,
  deletion_scheduled_for: null,
  session_purpose: "full",
};

test("hosted step-up shows the trusted action and asks for the required factors", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/capabilities", (route) =>
    route.fulfill({
      json: {
        totp_enabled: true,
        passkey_enabled: false,
        recovery_codes_enabled: false,
        email_verification_enabled: true,
        require_verified_email: false,
        external_step_up_enabled: true,
        registration_mode: "closed",
      },
    }),
  );
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: USER }));
  await page.route("**/api/v1/step-up/requests/**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      return route.fulfill({
        json: {
          client_name: "Synthetic RP",
          action: "critical_settings_change",
          description: "Изменение критических настроек приложения",
          payload_hash: "a".repeat(64),
          assurance: "reauth_password_mfa",
          assurance_label: "Пароль и второй фактор",
          plans: [
            {
              id: "password_totp",
              label: "Пароль и код из аутентификатора",
              methods: ["password", "totp"],
            },
          ],
          verified_methods: [],
          plan: null,
          status: "pending",
          passkey_enabled: false,
          expires_at: new Date(Date.now() + 120000).toISOString(),
        },
      });
    }
    if (request.method() === "POST" && request.url().endsWith("/verify")) {
      const body = request.postDataJSON() as { method: string };
      if (body.method === "password") {
        return route.fulfill({
          json: {
            completed: false,
            status: "pending",
            verified_methods: ["password"],
            remaining_methods: ["totp"],
            redirect_to: null,
            expires_at: new Date(Date.now() + 120000).toISOString(),
          },
        });
      }
      return route.fulfill({
        json: {
          completed: true,
          status: "approved",
          verified_methods: ["password", "totp"],
          remaining_methods: [],
          redirect_to: "https://rp.example.test/step-up/callback?code=synthetic&state=synthetic",
          expires_at: new Date(Date.now() + 120000).toISOString(),
        },
      });
    }
    if (request.method() === "POST" && request.url().endsWith("/deny")) {
      return route.fulfill({ json: { status: "denied" } });
    }
    return route.fulfill({ status: 404, json: { error: "not_found" } });
  });

  await page.goto(`/step-up/${TOKEN}`);
  await expect(
    page.getByRole("heading", { name: "Подтверждение действия" }),
  ).toBeVisible();
  await expect(page.getByText("Synthetic RP")).toBeVisible();
  await expect(page.getByText("Изменение критических настроек приложения")).toBeVisible();
  await expect(page.getByText("critical_settings_change")).toBeVisible();

  await page.getByLabel("Текущий пароль").fill("SyntheticPassword2026!");
  await page.getByRole("button", { name: "Подтвердить пароль" }).click();
  await expect(page.getByLabel("Код из приложения-аутентификатора")).toBeVisible();
  await expect(page.getByRole("button", { name: "Подтвердить код" })).toBeVisible();
});
