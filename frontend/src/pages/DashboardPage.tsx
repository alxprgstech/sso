import React from "react";
import { Link, useParams } from "react-router";
import { SectionNavigation } from "../components/SectionNavigation";
import { Alert } from "../components/ui/controls";
import { useAccountController } from "../features/account/useAccountController";
import {
  AccountProfile,
  AccountSecurity,
  AccountSessions,
  AccountPrivacy,
} from "../features/account/AccountSections";
const sections = {
  profile: AccountProfile,
  security: AccountSecurity,
  sessions: AccountSessions,
  privacy: AccountPrivacy,
};
export const DashboardPage: React.FC = () => {
  const state = useAccountController();
  const { user, pageError } = state;
  const { section = "profile" } = useParams();
  const titles: Record<string, string> = {
    profile: "Профиль",
    security: "Безопасность",
    sessions: "Активные сессии",
    privacy: "Конфиденциальность",
  };
  if (!user) return null;
  if (!Object.prototype.hasOwnProperty.call(sections, section))
    return (
      <SectionNavigation mode="account">
        <h1>Раздел не найден</h1>
        <Link to="/">К профилю</Link>
      </SectionNavigation>
    );

  const controller = { ...state, user };
  const Section = sections[section as keyof typeof sections];
  return (
    <SectionNavigation mode="account">
      <div className="space-y-8 max-w-5xl">
        <header>
          <h1>{titles[section]}</h1>
          <p className="mt-2 text-secondary">
            Управление учётной записью и доступом к сервисам.
          </p>
        </header>
        {pageError && <Alert>{pageError}</Alert>}
        <Section controller={controller} />
      </div>
    </SectionNavigation>
  );
};
