"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
type SidebarItem = {
  href: string;
  indent?: boolean;
  key: string;
  label: string;
};

function isItemActive(pathname: string, item: SidebarItem) {
  if (item.key === "dashboard") {
    return pathname === "/";
  }
  if (item.key === "detail") {
    return pathname.startsWith("/gradings/");
  }
  return false;
}

export function Sidebar({
  currentUserEmail,
}: {
  currentUserEmail?: string | null;
}) {
  const pathname = usePathname();
  const isDetailPage = pathname.startsWith("/gradings/");
  const items: SidebarItem[] = [
    { href: "/", key: "dashboard", label: isDetailPage ? "Back to dashboard" : "Dashboard" },
    ...(isDetailPage
      ? []
      : [
          { href: "/#new-grading", indent: true, key: "new-grading", label: "New grading" },
          { href: "/#history", indent: true, key: "history", label: "History" },
        ]),
  ];

  return (
    <aside className="app-sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-mark">AI</div>
        <div>
          <p className="sidebar-brand-label">Zanista</p>
          <h1>Exam Grader</h1>
        </div>
      </div>

      <nav className="sidebar-nav" aria-label="Primary">
        {items.map((item) => (
          <Link
            className={`sidebar-link${isItemActive(pathname, item) ? " active" : ""}${item.indent ? " sidebar-link-child" : ""}`}
            href={item.href}
            key={item.key}
          >
            <span className="sidebar-link-dot" />
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="sidebar-info-card">
        <p className="sidebar-section-title">Workspace</p>
        <strong>{currentUserEmail ?? "Signed in"}</strong>
        <p>Upload exam papers, review AI scoring, and export saved grading runs.</p>
      </div>
    </aside>
  );
}
