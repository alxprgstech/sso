import * as Menu from "@radix-ui/react-dropdown-menu";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Ellipsis } from "lucide-react";
import { IconButton } from "./controls";
export function ActionMenu({
  label,
  actions,
}: {
  label: string;
  actions: Array<{
    label: string;
    danger?: boolean;
    disabled?: boolean;
    run: () => void;
  }>;
}) {
  return (
    <Tooltip.Provider delayDuration={400}>
      <Menu.Root modal={false}>
        <Tooltip.Root>
          <Tooltip.Trigger asChild>
            <Menu.Trigger asChild>
              <IconButton label={label}>
                <Ellipsis size={18} aria-hidden="true" />
              </IconButton>
            </Menu.Trigger>
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content data-sentry-block className="tooltip-content">
              {label}
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
        <Menu.Portal>
          <Menu.Content
            data-sentry-block
            className="sso-sensitive menu-content"
            align="end"
            sideOffset={6}
          >
            {actions.map((action) => (
              <Menu.Item
                key={action.label}
                disabled={action.disabled}
                onSelect={action.run}
                className={action.danger ? "text-danger" : undefined}
              >
                {action.label}
              </Menu.Item>
            ))}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
    </Tooltip.Provider>
  );
}
