import type { ReactNode } from "react";


export function DashboardLayout({
  hero,
  sidebar,
  content
}: {
  hero: ReactNode;
  sidebar: ReactNode;
  content: ReactNode;
}) {
  return (
    <section className="dashboard-shell">
      <div className="dashboard-hero">{hero}</div>
      <div className="dashboard-body">
        <div className="dashboard-main">{content}</div>
        <aside className="dashboard-sidebar">{sidebar}</aside>
      </div>
    </section>
  );
}
