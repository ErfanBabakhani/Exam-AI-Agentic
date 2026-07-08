import type { ReactNode } from "react";

export function AppShell({
  children,
  sidebar,
  topbar,
}: {
  children: ReactNode;
  sidebar: ReactNode;
  topbar: ReactNode;
}) {
  return (
    <div className="app-shell">
      {sidebar}
      <div className="app-main">
        <div className="app-topbar-shell">{topbar}</div>
        <div className="app-content">{children}</div>
      </div>
    </div>
  );
}
