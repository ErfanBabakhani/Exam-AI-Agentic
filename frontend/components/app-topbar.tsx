import type { ReactNode } from "react";

export function AppTopbar({
  actions,
  eyebrow,
  meta,
  subtitle,
  title,
}: {
  actions?: ReactNode;
  eyebrow: string;
  meta?: ReactNode;
  subtitle: string;
  title: string;
}) {
  return (
    <div className="app-topbar">
      <div className="app-topbar-copy">
        <p className="eyebrow">{eyebrow}</p>
        <h2 className="topbar-title">{title}</h2>
        <p className="topbar-subtitle">{subtitle}</p>
        {meta ? <div className="app-topbar-meta">{meta}</div> : null}
      </div>
      {actions ? <div className="app-topbar-actions">{actions}</div> : null}
    </div>
  );
}
